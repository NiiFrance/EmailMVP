import pytest

import onboarding


def action(state, kind, now=1000, **kwargs):
    return onboarding.transition(state, {"version": onboarding.VERSION, "action": kind, **kwargs}, "user", now)


def test_at_most_two_visits_not_two_refreshes():
    state, result = action(None, "invite", requestId="request-one")
    assert result["granted"]
    repeat, result = action(state, "invite", requestId="request-one")
    assert result["granted"] and repeat == state
    repeat, result = action(state, "invite", requestId="another-tab")
    assert not result["granted"] and repeat == state
    state, result = action(state, "invite", now=3000, requestId="second-visit")
    assert result["granted"] and state["invitations"] == 2
    state, result = action(state, "invite", now=6000, requestId="third-visit")
    assert not result["granted"] and state["invitations"] == 2


def test_opt_out_and_completion_suppress_invites_but_allow_manual_replay():
    state, _ = action(None, "preferences", optOut=True)
    state, result = action(state, "invite", requestId="request-one")
    assert not result["granted"]
    state, _ = action(state, "start", tourId="first-campaign", runId="manual-run", revision=state["revision"])
    for step in range(1, 5):
        state, _ = action(state, "step", tourId="first-campaign", runId="manual-run", revision=state["revision"], step=step)
    state, _ = action(state, "complete", tourId="first-campaign", runId="manual-run", revision=state["revision"], step=4)
    assert state["optOut"] and state["invitations"] == 0
    state, _ = action(state, "start", tourId="first-campaign", runId="second-run", revision=state["revision"], restart=True)
    assert state["tours"]["first-campaign"]["completed"]


def test_another_tab_cannot_take_an_active_walkthrough():
    state, _ = action(None, "start", tourId="first-campaign", runId="first-tab", revision=0)
    with pytest.raises(onboarding.Conflict):
        action(state, "start", tourId="recovery", runId="other-tab", revision=state["revision"])
    resumed, _ = action(state, "start", now=1200, tourId="recovery", runId="other-tab", revision=state["revision"])
    assert resumed["activeTour"] == "recovery"


def test_stale_progress_cannot_overwrite_opt_out():
    state, _ = action(None, "start", tourId="first-campaign", runId="first-tab", revision=0)
    old_revision = state["revision"]
    state, _ = action(state, "preferences", optOut=True)
    with pytest.raises(onboarding.Conflict):
        action(state, "step", tourId="first-campaign", runId="first-tab", revision=old_revision, step=1)
    assert state["optOut"]


def test_admin_tour_requires_current_role():
    with pytest.raises(PermissionError):
        action(None, "start", tourId="admin-template", runId="first-tab", revision=0)


@pytest.mark.parametrize("step", [-1, 2, 99, True, "1"])
def test_invalid_or_skipped_step_is_rejected(step):
    state, _ = action(None, "start", tourId="first-campaign", runId="first-tab", revision=0)
    with pytest.raises(ValueError):
        action(state, "step", tourId="first-campaign", runId="first-tab", revision=state["revision"], step=step)


def test_visit_activity_extends_same_invitation_window():
    state, _ = action(None, "invite", requestId="request-one")
    state, _ = action(state, "visit", now=2500)
    state, result = action(state, "invite", now=3000, requestId="refresh-tab")
    assert not result["granted"] and state["invitations"] == 1


def test_completion_suppresses_invitation_without_opt_out():
    state = onboarding.initial_state()
    state["tours"]["first-campaign"] = {"step": 4, "status": "completed", "completed": True}
    updated, result = action(state, "invite", requestId="request-one")
    assert not result["granted"] and updated["invitations"] == 0


def test_boolean_revision_is_not_an_integer_revision():
    with pytest.raises(onboarding.Conflict):
        action(None, "start", tourId="first-campaign", runId="first-tab", revision=False)


def test_expired_lease_cannot_write_and_state_is_not_mutated():
    state, _ = action(None, "start", tourId="first-campaign", runId="first-tab", revision=0)
    with pytest.raises(onboarding.Conflict):
        action(state, "step", now=2000, tourId="first-campaign", runId="first-tab", revision=1, step=1)
    assert state["tours"]["first-campaign"]["step"] == 0


def test_downgraded_admin_cannot_update_admin_tour():
    state, _ = onboarding.transition(None, {"version": onboarding.VERSION, "action": "start", "tourId": "admin-template", "runId": "admin-run", "revision": 0}, "admin", 1000)
    with pytest.raises(PermissionError):
        action(state, "step", tourId="admin-template", runId="admin-run", revision=1, step=1)
    public = onboarding.public_state(state, "user")
    assert public["activeTour"] == "" and "admin-template" not in public["tours"]