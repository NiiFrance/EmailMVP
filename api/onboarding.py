"""Versioned, side-effect-free onboarding transitions; storage supplies atomicity."""

from copy import deepcopy
import re

VERSION = "2026-09-v1"
ACCOUNT_KEY = "walkthroughs"
VISIT_SECONDS = 1800
LEASE_SECONDS = 90
TOURS = {
    "first-campaign": ("choose", "upload", "mapping", "generate", "review"),
    "snovio-draft": ("connection", "sender", "readiness", "submit", "progress"),
    "recovery": ("history", "result", "retry", "resolved"),
    "admin-template": ("brief", "preview", "save", "published"),
}


class Conflict(ValueError):
    pass


def initial_state():
    return {"version": VERSION, "revision": 0, "invitations": 0, "optOut": False,
            "visitUntil": 0, "claimId": "", "leaseUntil": 0, "runId": "", "activeTour": "", "tours": {}}


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", value):
        raise ValueError("Invalid request identifier.")
    return value


def transition(current, payload, role, now):
    if not isinstance(payload, dict):
        raise ValueError("Expected an object.")
    state = deepcopy(current or initial_state())
    if payload.get("version") != VERSION:
        raise Conflict("Reload Help to use the current walkthrough version.")
    action = payload.get("action")
    granted = False
    if action == "invite":
        request_id = identifier(payload.get("requestId"))
        if state["optOut"] or state["tours"].get("first-campaign", {}).get("completed"):
            return state, {"granted": False}
        if request_id == state["claimId"]:
            return state, {"granted": state["visitUntil"] > now}
        if state["invitations"] >= 2 or state["visitUntil"] > now or state["leaseUntil"] > now:
            return state, {"granted": False}
        state.update(invitations=state["invitations"] + 1, visitUntil=now + VISIT_SECONDS, claimId=request_id)
        granted = True
    elif action == "visit":
        if state["visitUntil"] <= now:
            return state, {}
        state["visitUntil"] = now + VISIT_SECONDS
    elif action == "preferences":
        if type(payload.get("optOut")) is not bool:
            raise ValueError("optOut must be a boolean.")
        state["optOut"] = payload["optOut"]
    elif action in {"start", "step", "pause", "complete"}:
        tour = payload.get("tourId")
        if tour not in TOURS:
            raise ValueError("Unknown walkthrough.")
        if tour == "admin-template" and role != "admin":
            raise PermissionError("This walkthrough requires an administrator.")
        run_id = identifier(payload.get("runId"))
        if state["leaseUntil"] > now and state["runId"] != run_id:
            raise Conflict("A walkthrough is active in another tab. Pause it first or wait for it to expire.")
        if type(payload.get("revision")) is not int or payload["revision"] != state["revision"]:
            raise Conflict("Walkthrough progress changed. Reload its saved state.")
        progress = state["tours"].setdefault(tour, {"step": 0, "status": "idle", "completed": False})
        if action == "start":
            if payload.get("restart") is True:
                progress["step"] = 0
            progress["status"] = "active"
            state.update(activeTour=tour, runId=run_id, leaseUntil=now + LEASE_SECONDS)
        else:
            if state["activeTour"] != tour or state["runId"] != run_id or state["leaseUntil"] <= now:
                raise Conflict("This walkthrough is paused. Resume it from Help.")
            step = payload.get("step")
            if type(step) is not int or not 0 <= step < len(TOURS[tour]):
                raise ValueError("Unknown walkthrough step.")
            if step < progress["step"] or step > progress["step"] + 1:
                raise Conflict("Walkthrough steps must be completed in order.")
            progress["step"] = step
            state["leaseUntil"] = now + LEASE_SECONDS
            if action == "complete":
                if step != len(TOURS[tour]) - 1:
                    raise ValueError("The walkthrough has unfinished steps.")
                progress.update(status="completed", completed=True)
                state.update(activeTour="", runId="", leaseUntil=0)
            elif action == "pause":
                progress["status"] = "paused"
                state.update(activeTour="", runId="", leaseUntil=0)
        progress["updatedAt"] = now
    else:
        raise ValueError("Unknown onboarding action.")
    state["revision"] += 1
    return state, {"granted": granted} if action == "invite" else {}


def public_state(state, role):
    result = deepcopy(state)
    result.pop("claimId", None)
    result.pop("runId", None)
    if role != "admin":
        result["tours"].pop("admin-template", None)
        if result["activeTour"] == "admin-template":
            result["activeTour"] = ""
    result["availableTours"] = [tour for tour in TOURS if role == "admin" or tour != "admin-template"]
    return result