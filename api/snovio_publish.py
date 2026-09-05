"""Checkpointed, draft-only Snov.io publication with bounded worker deliveries."""

from copy import deepcopy

from csv_processor import parse_csv
from snovio_campaigns import (
    build_campaign_payload, build_campaign_sequence, build_touch_content,
    detect_touch_count, map_email_step_contents,
)
from snovio_workflows import build_job_rows, summarize_report


TERMINAL = {"completed", "partial", "failed", "needs_review"}
CHUNK_SIZE = 20


class MissingProspectConfirmation(ValueError):
    def __init__(self, row_index):
        self.row_index = row_index
        super().__init__(f"Snov.io currently has no prospect for row {row_index + 1}. No write was replayed.")


def new_state(payload, credential_key):
    return {
        "version": 1, "payload": deepcopy(payload), "credentialKey": credential_key,
        "status": "queued", "stage": "preflight", "rows": {}, "steps": {},
    }


def retry_failed(state):
    if state["status"] not in {"partial", "failed"}:
        raise ValueError("Only failed or partially completed operations can be retried.")
    if state.get("inFlight"):
        raise ValueError("An ambiguous write must be reviewed before retrying.")
    state["rows"] = {key: row for key, row in state["rows"].items() if row.get("status") in {"added", "updated"}}
    state.pop("candidates", None)
    state["steps"] = {key: row for key, row in state["steps"].items() if row.get("status") == "written"}
    state["status"] = "queued"
    state["error"] = ""


def report_for(state, job_id):
    rows = sorted(state["rows"].values(), key=lambda row: row["rowIndex"])
    summary = summarize_report(rows)
    return {
        "jobId": job_id, "status": state["status"], "stage": state["stage"],
        "listId": state["payload"].get("listId", ""),
        "campaignId": state.get("campaignId"), "summary": summary,
        "total": state.get("total", 0), "processed": len(rows), "rows": rows,
        "stepContent": list(state["steps"].values()), "error": state.get("error", ""),
        "mode": state["payload"].get("mode", "list"),
    }


def reconcile(state, client, csv_bytes, confirm_missing=False):
    """Adopt only a provable result of the interrupted write; never create resources."""
    if state.get("status") != "needs_review" or not state.get("inFlight"):
        raise ValueError("This operation has no uncertain write to reconcile.")
    payload = state["payload"]
    stage = state["inFlight"]
    if stage == "create_list":
        matches = [item for item in client.get_user_lists()
                   if item.get("name") == payload["listName"] and not item.get("isDeleted")]
        if len(matches) != 1 or not matches[0].get("id"):
            raise ValueError("Cannot identify exactly one created list. Review the account before continuing.")
        payload["listId"] = str(matches[0]["id"])
    elif stage == "create_campaign":
        title = payload.get("campaignTitle") or payload["listName"]
        matches = [item for item in client.get_user_campaigns() if (item.get("campaign") or item.get("title")) == title]
        if len(matches) != 1 or not matches[0].get("id") or not state.get("emailRefs"):
            raise ValueError("Cannot identify the exact draft and saved sequence. Manual review is required.")
        response = client.get_campaign(matches[0]["id"])
        campaign = response.get("data", response)
        list_id = str(campaign.get("list_id") or campaign.get("listId") or "")
        if list_id != str(payload["listId"]) or str(campaign.get("status", "")).lower() not in {"new", "draft"}:
            raise ValueError("The campaign is not the expected inactive draft for this list.")
        steps = map_email_step_contents(response, state["emailRefs"])
        if len(steps) != state["touches"] or any(item.get("stepId") is None or item.get("contentId") is None for item in steps):
            raise ValueError("Draft sequence cannot be matched exactly. Manual review is required.")
        state.update(campaignId=campaign["id"], stepMap=steps)
    elif stage.startswith("prospect:"):
        index = int(stage.split(":", 1)[1])
        rows, _ = build_job_rows(parse_csv(csv_bytes))
        row = next((item for item in rows if item["rowIndex"] == index), None)
        if not row or not row.get("email"):
            raise ValueError("The saved recipient cannot be identified.")
        result = client.get_prospects_by_email(row["email"])
        matches = [prospect for prospect in result.get("data", [])
                   if any(str(item.get("id")) == str(payload["listId"]) for item in prospect.get("lists", []))]
        if not result.get("data"):
            if not confirm_missing:
                raise MissingProspectConfirmation(index)
        elif len(matches) != 1:
            raise ValueError("The uncertain recipient cannot be confirmed uniquely in this list. No write was replayed.")
        safe_rows = payload.setdefault("_noDuplicateRows", [])
        if index not in safe_rows:
            safe_rows.append(index)
        state["rows"].pop(str(index), None)
        payload["updateExisting"] = True
    else:
        raise ValueError("Unknown interrupted write. Manual review is required.")
    state.pop("inFlight", None)
    state.update(status="failed", error="")
    retry_failed(state)


def run_chunk(state, client, job_id, csv_bytes, save, sync):
    if state["status"] in TERMINAL:
        return
    if state.get("inFlight"):
        state.update(status="needs_review", error="A previous write has an unknown outcome. Review the destination before starting another export.")
        save(state)
        return
    payload = state["payload"]
    state["status"] = "running"
    if "candidates" not in state:
        preview, error = sync(client, job_id, {**payload, "dryRun": True}, csv_bytes=csv_bytes)
        if error is not None:
            raise ValueError(error.get_body().decode("utf-8"))
        state["total"] = len(preview["rows"])
        state["candidates"] = [row["rowIndex"] for row in preview["rows"] if row["eligible"]]
        state["rows"].update({str(row["rowIndex"]): row for row in preview["rows"]
                     if not row["eligible"] and str(row["rowIndex"]) not in state["rows"]})
        if preview.get("listId"):
            payload["listId"] = preview["listId"]
        if payload.get("mode") == "draft":
            touches = detect_touch_count(list(parse_csv(csv_bytes).columns))
            if not touches or not payload.get("senderAccountIds"):
                raise ValueError("Generated emails and an explicitly selected sender are required.")
            senders = client.get_sender_accounts()
            valid = {str(sender["id"]) for sender in senders if sender.get("valid") is True}
            if not set(map(str, payload["senderAccountIds"])).issubset(valid):
                raise ValueError("The selected sender is unavailable or not valid in this Snov.io account.")
            state["touches"] = touches
        save(state)

    pending = [index for index in state["candidates"] if str(index) not in state["rows"]]
    if pending and not payload.get("listId"):
        state["stage"] = "list"
        state["inFlight"] = "create_list"
        save(state)
        response = client.create_prospect_list(payload["listName"])
        data = response[0] if isinstance(response, list) and response else response
        list_id = (data.get("data") or {}).get("id") or data.get("id")
        if not list_id:
            raise ValueError("Snov.io did not return a list ID; check the account before retrying.")
        payload["listId"] = str(list_id)
        state.pop("inFlight", None)
        save(state)

    if pending:
        state["stage"] = "prospects"

        def before_write(row):
            state["inFlight"] = f"prospect:{row['rowIndex']}"
            save(state)

        def completed(row):
            state["rows"][str(row["rowIndex"])] = row
            if row.get("uncertain"):
                state.update(status="needs_review", error="A prospect write has an unknown outcome. Review this row in Snov.io before retrying.")
                save(state)
                raise RuntimeError(state["error"])
            state.pop("inFlight", None)
            save(state)

        _, error = sync(
            client, job_id, {**payload, "dryRun": False, "_rowIndices": pending[:CHUNK_SIZE]},
            on_row=completed, before_write=before_write, csv_bytes=csv_bytes,
        )
        if error is not None:
            raise ValueError(error.get_body().decode("utf-8"))
        if any(str(index) not in state["rows"] for index in state["candidates"]):
            state["status"] = "queued"
            save(state)
            return

    summary = report_for(state, job_id)["summary"]
    if summary["failed"] or summary["blocked"] or not state["candidates"]:
        state.update(status="partial", error="Some leads were not exported. Review the row results; retry failed rows only.")
        save(state)
        return
    if payload.get("mode") == "draft":
        state["stage"] = "campaign"
        if not state.get("campaignId"):
            valid_senders = {str(sender["id"]) for sender in client.get_sender_accounts() if sender.get("valid") is True}
            if not payload.get("senderAccountIds") or not set(map(str, payload["senderAccountIds"])).issubset(valid_senders):
                raise ValueError("The selected sender is no longer valid in this account.")
            delay = int(payload.get("delayDays", 3))
            if not 0 <= delay <= 365:
                raise ValueError("Delay must be between 0 and 365 days.")
            sequence, references = build_campaign_sequence(state["touches"], delay_days=int(payload.get("delayDays", 3)))
            campaign_payload = build_campaign_payload(
                title=payload.get("campaignTitle") or payload["listName"],
                email_account_ids=payload["senderAccountIds"], list_id=payload["listId"], sequence=sequence,
                track_opens=bool(payload.get("trackOpens", True)), track_clicks=bool(payload.get("trackClicks", True)),
                schedule_id=int(payload["scheduleId"]) if payload.get("scheduleId") else None,
                timezone=payload.get("timezone") or None,
            )
            state["inFlight"] = "create_campaign"
            state["emailRefs"] = references
            save(state)
            response = client.create_campaign(campaign_payload)
            data = response.get("data", response)
            if not data.get("id"):
                raise ValueError("Snov.io did not return a campaign ID; check the account before retrying.")
            state["campaignId"] = data["id"]
            state["stepMap"] = map_email_step_contents(response, references)
            state.pop("inFlight", None)
            save(state)
        state["stage"] = "content"
        for position, content in enumerate(build_touch_content(state["touches"])):
            key = str(content["touch"])
            if state["steps"].get(key, {}).get("status") == "written":
                continue
            entries = state["stepMap"]
            entry = entries[position] if position < len(entries) else {}
            result = {"touch": content["touch"], **entry}
            if entry.get("stepId") is None or entry.get("contentId") is None:
                result.update(status="failed", error="Missing campaign step/content ID.")
            else:
                try:
                    save(state)
                    campaign = client.get_campaign(state["campaignId"])
                    campaign_data = campaign.get("data", campaign)
                    if str(campaign_data.get("status") or "").lower() not in {"new", "draft"}:
                        raise ValueError("The campaign is no longer a draft. Content updates are blocked.")
                    client.create_email_step_content(
                        state["campaignId"], entry["stepId"], int(entry["contentId"]),
                        subject=content["subject"], body=content["body"], plain_text=content["plain_text"],
                    )
                    result["status"] = "written"
                except Exception as error:
                    result.update(status="failed", error=str(error))
            state["steps"][key] = result
            save(state)
        if any(step["status"] != "written" for step in state["steps"].values()):
            state.update(status="partial", error="Draft content is incomplete. Retry the failed steps; the existing campaign will be reused.")
            save(state)
            return
    state.update(status="completed", stage="done", error="")
    save(state)