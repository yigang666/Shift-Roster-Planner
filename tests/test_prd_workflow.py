import os
from collections import Counter
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from roster import DataError, StaleRevisionError, Store, export_roster, import_roster, read_members, sample_roster
from rules import coverage
from service import cancel_leave, commit_plan, plan_status, record_response, save_plan
from solver import Change, Plan, search


@pytest.fixture
def swap_case(tmp_path, make_roster, target):
    roster = make_roster(target, dict(A="D", B="D", C="D", D="N", E="N", F="N"),
                         senior=("D", "E"))
    store = Store(tmp_path / "data")
    baseline = store.update(0, lambda _: roster, actor="Alice", event="seed")
    proposal = Plan((
        Change("B", target, "D", "N", "same_day_swap"),
        Change("D", target, "N", "D", "same_day_swap"),
    ), (1, 2, 0, 0, 0, 2))
    awaiting = save_plan(store, baseline.revision, target, proposal, "Alice")
    return store, awaiting, next(iter(awaiting.plans))


def accept_swap(store, awaiting, plan_id):
    first = record_response(store, awaiting.revision, plan_id, "B", True, "Alice")
    return record_response(store, first.revision, plan_id, "D", True, "Bob")


def test_tc02_existing_leave_import_is_idempotent(tmp_path):
    members = read_members("member_id,name,team,experience_level\nA,Ada,A,SENIOR\n")
    source = "member_id,2026-06-15,2026-06-16\nA,ABS,D\n"
    store = Store(tmp_path)
    first = store.import_schedule(0, source, members, actor="Alice", leave_codes=("ABS",))
    second = store.import_schedule(first.revision, source, members, actor="Bob", leave_codes=("ABS",))
    assert len(first.leaves) == 1
    assert second.revision == first.revision and second.audit == first.audit
    assert store.load().import_csv == source
    assert [first.effective()[key] for key in sorted(first.shifts)] == ["L", "D"]


def test_tc15_rejecting_a_cross_team_swap_blocks_commit_and_recalculates(swap_case, target):
    store, awaiting, plan_id = swap_case
    assert awaiting.members["B"].team != awaiting.members["D"].team
    rejected = record_response(store, awaiting.revision, plan_id, "B", False, "Alice")
    assert rejected.plans[plan_id]["status"] == "REJECTED"
    with pytest.raises(ValueError, match="status"):
        commit_plan(store, rejected.revision, plan_id, "Bob")
    assert store.load().effective() == awaiting.effective()
    candidates = search(rejected, target, days_before=0, days_after=0, timeout=8)
    assert candidates.plans
    assert all(not any(change.member_id == "B" and change.action == "same_day_swap"
                       for change in plan.changes) for plan in candidates.plans)


def test_tc16_two_managers_cannot_commit_same_revision(swap_case):
    store, awaiting, plan_id = swap_case
    ready = accept_swap(store, awaiting, plan_id)
    gate = Barrier(2, timeout=5)

    def commit(actor):
        gate.wait()
        try:
            return commit_plan(store, ready.revision, plan_id, actor).plans[plan_id]["status"]
        except StaleRevisionError:
            return "STALE"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(commit, ("Alice", "Bob"))) == ["COMMITTED", "STALE"]
    events = store.load().audit
    assert sum(item["event_type"] == "plan_committed" for item in events) == 1


def test_tc17_manifest_failure_never_exposes_half_swap(swap_case, target, monkeypatch):
    store, awaiting, plan_id = swap_case
    ready = accept_swap(store, awaiting, plan_id)
    current_before = (store.path / "CURRENT").read_text()
    original_replace = os.replace

    def fail_manifest(source, destination, *args, **kwargs):
        if os.fspath(destination) == os.fspath(store.path / "CURRENT"):
            raise OSError("simulated manifest failure")
        return original_replace(source, destination, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", fail_manifest)
        with pytest.raises(OSError, match="manifest failure"):
            commit_plan(store, ready.revision, plan_id, "Bob")
    assert (store.path / "CURRENT").read_text() == current_before
    restored = store.load()
    assert restored.revision == ready.revision
    assert restored.effective()["B", target] == "D"
    assert restored.effective()["D", target] == "N"
    committed = commit_plan(store, ready.revision, plan_id, "Bob")
    assert committed.effective()["B", target] == "N"
    assert committed.effective()["D", target] == "D"


@pytest.mark.parametrize("seniority", ["", "UNKNOWN"])
def test_tc32_member_requires_valid_seniority(seniority):
    with pytest.raises(DataError, match="experience_level"):
        read_members("member_id,name,team,experience_level\nA,Ada,A,%s\n" % seniority)


def test_tc35_synthetic_schedule_matches_team_distribution():
    roster = sample_roster()
    assert len(roster.members) == 19
    assert Counter((member.team, member.experience_level) for member in roster.members.values()) == {
        ("A", "SENIOR"): 4, ("A", "JUNIOR"): 1,
        ("B", "SENIOR"): 4, ("B", "JUNIOR"): 1,
        ("C", "SENIOR"): 3, ("C", "JUNIOR"): 2,
        ("D", "SENIOR"): 3, ("D", "JUNIOR"): 1,
    }
    assert roster.leaves


def test_all_consents_required_and_export_preserves_complete_swap(swap_case, target):
    store, awaiting, plan_id = swap_case
    first = record_response(store, awaiting.revision, plan_id, "B", True, "Alice")
    with pytest.raises(ValueError, match="status"):
        commit_plan(store, first.revision, plan_id, "Alice")
    ready = record_response(store, first.revision, plan_id, "D", True, "Bob")
    final = commit_plan(store, ready.revision, plan_id, "Bob")
    assert final.plans[plan_id]["status"] == "COMMITTED"
    assert coverage(final, [target])[target].day_seniors == ("D",)
    assert final.shifts["B", target] == "D"
    for wide in (False, True):
        reimported = import_roster(export_roster(final, wide=wide), final.members)
        assert reimported.effective() == final.effective()


def test_tc34_conditional_request_cannot_be_saved_as_consented_plan(tmp_path, make_roster, target):
    roster = make_roster(
        target, dict(A="D", B="D", C="D", D="N", E="N", F="N", G="D"),
        senior=("D", "G")).with_leave("G", target, target)
    store = Store(tmp_path)
    baseline = store.update(0, lambda _: roster, actor="Alice", event="seed")
    result = search(baseline, target, days_before=0, days_after=0)
    assert result.conditional
    with pytest.raises(ValueError):
        save_plan(store, baseline.revision, target, result.conditional[0], "Alice")
    assert store.load().effective()["G", target] == "L"


def test_restoring_leave_cannot_introduce_continuous_work(tmp_path, make_roster, target):
    tomorrow = target + timedelta(days=1)
    roster = make_roster(
        target, dict(A="D", B="D", C="D", D="N", E="N", F="N", G="N"),
        extra={("G", tomorrow): "D"},
    ).with_leave("G", target, target)
    store = Store(tmp_path)
    baseline = store.update(0, lambda _: roster, actor="Alice", event="seed")
    with pytest.raises(ValueError, match="H01"):
        cancel_leave(store, baseline.revision, "G", target, target, None, "Bob")
    current = store.load()
    assert current.revision == baseline.revision
    assert current.effective()["G", target] == "L"
    assert current.effective()["G", tomorrow] == "D"


def test_reverting_a_roster_change_does_not_revive_a_stale_plan(swap_case, target):
    store, awaiting, plan_id = swap_case
    ready = accept_swap(store, awaiting, plan_id)
    changed = store.update(
        ready.revision, lambda roster: roster.with_leave("A", target, target),
        actor="Bob", event="leave_added",
    )
    reverted = cancel_leave(store, changed.revision, "A", target, target, None, "Bob")
    assert reverted.effective() == ready.effective()
    assert plan_status(reverted, reverted.plans[plan_id]) == "STALE"
    with pytest.raises(ValueError, match="status|stale"):
        commit_plan(store, reverted.revision, plan_id, "Alice")
