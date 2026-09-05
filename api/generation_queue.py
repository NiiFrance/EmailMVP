"""Persistent admission and fair, paced generation reservations for one app."""

import math

VERSION = 2
MAX_JOBS = 100
REQUESTS_PER_MINUTE = 180
TOKENS_PER_MINUTE = 180000


class Busy(ValueError):
    pass


def initial_state():
    return {"version": VERSION, "sequence": 0, "nextRequest": 0, "nextToken": 0, "jobs": {}, "reservations": []}


def _copy(current):
    return {**current, "jobs": {key: dict(value) for key, value in current["jobs"].items()},
            "reservations": list(current["reservations"])}


def admit(current, job_id, owner, config_hash, now):
    state = _copy(current or initial_state())
    existing = state["jobs"].get(job_id)
    if existing:
        if existing["owner"] != owner or existing["config"] != config_hash:
            raise Busy("This job already has a different generation request. Open its saved status.")
        return state, {"accepted": True, "created": False}
    if len(state["jobs"]) >= MAX_JOBS:
        raise Busy("The generation queue is full. Please retry later; no work was started.")
    if any(job["owner"] == owner for job in state["jobs"].values()):
        raise Busy("Your account already has a generation job in progress. Wait for it to finish.")
    state["sequence"] += 1
    state["jobs"][job_id] = {"owner": owner, "config": config_hash, "order": state["sequence"],
                              "waiting": False, "readyAt": now, "dispatchUntil": 0, "waitingUntil": 0}
    return state, {"accepted": True, "created": True}


def reserve(current, job_id, estimated_tokens, now):
    if type(estimated_tokens) is not int or estimated_tokens < 1 or estimated_tokens > TOKENS_PER_MINUTE:
        raise ValueError("The lead and template exceed the per-request token budget.")
    state = _copy(current)
    job = state["jobs"].get(job_id)
    if not job:
        raise Busy("Generation admission is missing. No provider request was made.")
    job["waiting"] = True
    job["tokens"] = estimated_tokens
    if job["waitingUntil"] < now + 60:
        job["waitingUntil"] = now + 120
    if job["readyAt"] > now:
        return state, {"granted": False, "retryAfter": max(1, math.ceil(job["readyAt"] - now))}
    waiting = [(entry["order"], key) for key, entry in state["jobs"].items()
               if entry["waiting"] and entry["readyAt"] <= now and entry["waitingUntil"] > now]
    state["reservations"] = [reservation for reservation in state["reservations"] if reservation[0] > now - 60]
    next_time = max(state["nextRequest"], state["nextToken"])
    tokens = sum(reservation[1] for reservation in state["reservations"])
    remaining_requests = len(state["reservations"])
    for timestamp, cost in state["reservations"]:
        if tokens + estimated_tokens <= TOKENS_PER_MINUTE and remaining_requests < REQUESTS_PER_MINUTE:
            break
        next_time = max(next_time, timestamp + 60)
        tokens -= cost
        remaining_requests -= 1
    if min(waiting)[1] != job_id or next_time > now:
        ahead = [state["jobs"][key] for order, key in waiting if order < job["order"]]
        queue_delay = sum(max(60 / REQUESTS_PER_MINUTE, entry.get("tokens", estimated_tokens) * 60 / TOKENS_PER_MINUTE) for entry in ahead)
        delay = max(next_time - now, min(60, queue_delay))
        return state, {"granted": False, "retryAfter": max(3, math.ceil(delay))}
    state["nextRequest"] = now + 60 / REQUESTS_PER_MINUTE
    state["nextToken"] = now + estimated_tokens * 60 / TOKENS_PER_MINUTE
    state["reservations"].append([now, estimated_tokens])
    state["sequence"] += 1
    job.update(order=state["sequence"], waiting=False)
    return state, {"granted": True, "retryAfter": 0}


def defer(current, job_id, now, retry_after):
    state = _copy(current)
    state["jobs"][job_id]["readyAt"] = now + max(1, retry_after)
    state["jobs"][job_id]["waiting"] = False
    state["nextRequest"] = max(state["nextRequest"], now + max(1, retry_after))
    return state


def release(current, job_id):
    state = _copy(current)
    state["jobs"].pop(job_id, None)
    return state


def claim_dispatch(current, job_id, now):
    state = _copy(current)
    job = state["jobs"].get(job_id)
    if not job or job["dispatchUntil"] > now:
        return state, False
    job["dispatchUntil"] = now + 120
    return state, True