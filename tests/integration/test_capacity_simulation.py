"""Accelerated scheduling proof; this is not a deployed API load test."""

import heapq
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))
import generation_queue as queue


def test_100_accounts_1000_leads_fair_drain_with_provider_cooldown():
    start = time.perf_counter()
    state = None
    events = []
    counts = [0] * 100
    seen = set()
    reservations = []
    first_grant = {}
    largest_gap = 0
    fault_injected = False
    for owner in range(100):
        state, _ = queue.admit(state, f"job-{owner:03d}", f"owner-{owner:03d}", "config", 0)
        heapq.heappush(events, (0, owner))
    while events:
        now, owner = heapq.heappop(events)
        job = f"job-{owner:03d}"
        state, grant = queue.reserve(state, job, 5000, now)
        if not grant["granted"]:
            heapq.heappush(events, (now + grant["retryAfter"], owner))
            continue
        first_grant.setdefault(owner, now)
        reservations.append((now, 5000))
        if len(seen) == 12345 and not fault_injected:
            state = queue.defer(state, job, now, 3600)
            fault_injected = True
            heapq.heappush(events, (now + 3600, owner))
            continue
        key = (owner, counts[owner])
        assert key not in seen
        seen.add(key)
        counts[owner] += 1
        active_counts = [count for count in counts if count < 1000]
        if active_counts:
            largest_gap = max(largest_gap, max(active_counts) - min(active_counts))
        if counts[owner] < 1000:
            heapq.heappush(events, (now + 1, owner))
        else:
            state = queue.release(state, job)
    assert len(seen) == 100000 and all(count == 1000 for count in counts)
    assert not state["jobs"] and len(first_grant) == 100
    assert largest_gap <= 2
    left = 0
    tokens = 0
    for right, (timestamp, cost) in enumerate(reservations):
        tokens += cost
        while reservations[left][0] <= timestamp - 60:
            tokens -= reservations[left][1]
            left += 1
        assert tokens <= queue.TOKENS_PER_MINUTE
        assert right - left + 1 <= queue.REQUESTS_PER_MINUTE
    print(json.dumps({"kind": "accelerated-scheduler-only", "accounts": 100, "leads": len(seen),
        "equivalentEmailsAtFourTouchesNotGenerated": len(seen) * 4, "virtualHours": round(now / 3600, 2),
        "elapsedSeconds": round(time.perf_counter() - start, 2), "maxLeadCountGap": largest_gap,
        "maxFirstTurnSeconds": max(first_grant.values()), "realProviderCalls": 0}))