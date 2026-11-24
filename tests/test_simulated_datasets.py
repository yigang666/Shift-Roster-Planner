from datetime import date
from pathlib import Path

import pytest

from roster import Store, export_roster, import_roster, read_members
from rules import coverage
from service import commit_plan, record_response, save_plan
from solver import search

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


@pytest.mark.parametrize(
    "filename, day, leave_codes, deficits, expected_action",
    [
        ("normal_long.csv", 3, ("L",), (0, 0, 0, 0, 0), "NO_CHANGE"),
        ("day_senior_gap_long.csv", 3, ("L",), (0, 1, 0, 1, 0), "standby_conversion"),
        ("night_gap_wide.csv", 3, ("AL",), (0, 0, 1, 0, 0), "off_recall"),
        ("month_end_incomplete_long.csv", 31, ("L",), (0, 0, 1, 0, 0), "UNVERIFIED"),
    ],
)
def test_simulated_source_csv(tmp_path, filename, day, leave_codes, deficits, expected_action):
    members = read_members((EXAMPLES / "members.csv").read_text(encoding="utf-8"))
    source = (EXAMPLES / "simulated" / filename).read_text(encoding="utf-8")
    target = date(2026, 12, day)
    manager = "Manager 1"
    store = Store(tmp_path)
    saved = store.import_schedule(0, source, members, actor=manager, leave_codes=leave_codes)
    roster = store.load()
    assert roster.revision == saved.revision
    assert len(roster.members) == 19
    assert coverage(roster, [target])[target].deficits == deficits

    if filename.endswith("_wide.csv"):
        assert roster.source_shifts["B01", target] == "AL"
        assert roster.leaves["B01", target] is None
    elif filename == "day_senior_gap_long.csv":
        assert roster.leaves["C01", target] == "D"

    result = search(roster, target, days_before=0, days_after=0, max_members=1,
                    max_changes=1, top=2, timeout=10)
    if expected_action in {"NO_CHANGE", "UNVERIFIED"}:
        assert result.status == expected_action
        assert not result.plans
        if expected_action == "UNVERIFIED":
            assert any("2027-01 lacks complete month data" in reason for reason in result.unverified)
        assert store.load().revision == roster.revision
        return

    plan = result.plans[0]
    change, = plan.changes
    assert change.action == expected_action
    pending = save_plan(store, roster.revision, target, plan, manager)
    plan_id, = pending.plans
    with pytest.raises(ValueError):
        commit_plan(store, pending.revision, plan_id, manager)
    assert store.load().effective() == roster.effective()

    accepted = record_response(store, pending.revision, plan_id, change.member_id, True, manager)
    committed = commit_plan(store, accepted.revision, plan_id, manager)
    assert committed.plans[plan_id]["status"] == "COMMITTED"
    effective_csv = export_roster(store.load())
    reimported = import_roster(effective_csv, members)
    assert reimported.effective()[change.member_id, target] == change.new_shift
    assert coverage(reimported, [target])[target].status == "NORMAL"
