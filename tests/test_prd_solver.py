from datetime import timedelta

import pytest

from rules import coverage, load_rules, validate_transition
from solver import search


def solve(roster, target, **kwargs):
    settings = dict(days_before=0, days_after=0, timeout=8, top=20)
    return search(roster, target, **(settings | kwargs))


def changed(plan):
    return {(change.member_id, change.date): change.new_shift for change in plan.changes}


def test_tc01_normal_schedule_returns_no_plans(healthy, target):
    result = solve(healthy, target)
    assert not result.plans
    assert result.status == "NO_CHANGE"


def test_tc03_evening_restoration_preserves_degraded_warning(make_roster, target):
    roster = make_roster(target, dict(A="D", B="D", C="S", D="N", E="N", F="N"))
    result = solve(roster, target)
    assert result.plans
    options = {(change.old_shift, change.new_shift)
               for plan in result.plans for change in plan.changes}
    assert ("S", "D") in options or ("S", "S_OT") in options
    assert ("N", "N_EARLY") in options
    for plan in result.plans:
        overrides = changed(plan)
        assert validate_transition(roster, overrides, [target]).ok
        assert coverage(roster, [target], shifts=roster.effective() | overrides)[target].status == "DEGRADED"


def test_tc12_multi_person_restoration_is_ranked_and_unique(make_roster, target):
    roster = make_roster(target, dict(A="D", B="D", C="R", D="N", E="N", F="N", G="O"))
    result = solve(roster, target, max_members=2, max_changes=2)
    assert result.plans and len(result.plans[0].changes) == 2
    best = changed(result.plans[0])
    assert coverage(roster, [target], shifts=roster.effective() | best)[target].status == "NORMAL"
    assert all(validate_transition(roster, changed(plan), [target]).ok for plan in result.plans)
    assignments = [frozenset(changed(plan).items()) for plan in result.plans]
    assert len(assignments) == len(set(assignments))
    assert [plan.score for plan in result.plans] == sorted(plan.score for plan in result.plans)


@pytest.mark.parametrize("known", [True, False])
def test_tc13_tc14_tc34_leave_request_is_conditional(make_roster, target, known):
    roster = make_roster(
        target, dict(A="D", B="D", C="D", D="N", E="N", F="N", G="D"),
        senior=("D", "G"))
    roster = roster.with_leave("G", target, target)
    if not known:
        roster.leaves["G", target] = None
    result = solve(roster, target)
    assert not result.plans
    assert roster.effective()["G", target] == "L"
    if known:
        assert len(result.conditional) == 1
        change = result.conditional[0].changes[0]
        assert (change.member_id, change.new_shift, change.action) == ("G", "D", "cancel_leave_request")
    else:
        assert not result.conditional


def test_tc18_zero_budget_makes_no_completeness_claim(make_roster, target):
    roster = make_roster(target, dict(A="D", B="D", C="O", D="N", E="N", F="N"))
    assert solve(roster, target, timeout=0).status == "UNKNOWN"


def test_tc21_reset_standby_is_candidate(make_roster, target):
    roster = make_roster(target, dict(A="D", B="D", C="D", D="N", E="N", F="N", G="R"))
    result = solve(roster, target, max_members=1)
    assert any(plan.changes[0].action == "reset_standby" for plan in result.plans)


def test_tc31_senior_replacement_with_normal_headcount(make_roster, target):
    roster = make_roster(
        target, dict(A="D", B="D", C="D", D="N", E="N", F="N", G="D", H="S"),
        senior=("D", "G", "H"))
    roster = roster.with_leave("G", target, target)
    before = coverage(roster, [target])[target]
    assert before.status == "CRITICAL"
    assert before.shortage_types == ("SENIOR_SHORTAGE",)
    result = solve(roster, target, max_members=1)
    assert result.plans
    assert all(changed(plan)["H", target] in {"D", "S_OT"} for plan in result.plans)


def test_tc33_cross_date_swap_and_recall_repair_both_gaps(make_roster, target):
    tomorrow = target + timedelta(days=1)
    roster = make_roster(
        target,
        dict(A="D", B="D", C="R", D="N", E="N", F="N", G="N", H="D"),
        senior=("D", "G", "H"),
        extra={("A", tomorrow): "D", ("B", tomorrow): "D", ("C", tomorrow): "D",
               ("D", tomorrow): "N", ("E", tomorrow): "N", ("F", tomorrow): "N",
               ("G", tomorrow): "O", ("H", tomorrow): "D"},
    ).with_leave("H", target, target)
    rules = load_rules()
    # G cannot start a day shift via direct reassignment. C can cover the
    # remaining headcount gap via reset standby, but cannot cover H14.
    assert coverage(roster, [target])[target].shortage_types == ("HEADCOUNT_SHORTAGE", "SENIOR_SHORTAGE")
    result = solve(roster, target, days_after=1, max_members=3, max_changes=3,
                   top=30, rules=rules)
    assert result.plans
    cross_date = [plan for plan in result.plans
                  if {change.date for change in plan.changes} == {target, tomorrow}]
    assert cross_date
    for plan in cross_date:
        after = coverage(roster, [target, tomorrow], shifts=roster.effective() | changed(plan))
        assert all(not any(day.deficits) for day in after.values())
        assert validate_transition(roster, changed(plan), [target]).ok


def test_complete_search_matches_small_exhaustive_assignment_oracle(make_roster, target):
    from itertools import product

    roster = make_roster(
        target, dict(A="D", B="D", C="S", D="N", E="N", F="N", G="R"),
    )
    rules = load_rules()
    rules["actions"].update(cross_team_swap=False, cross_date_swap=False)
    # One changed assignment rules out atomic swaps. The following choices are
    # enumerated from the PRD's confirmed action list independently of the solver.
    choices = {"C": ("S", "D"), "D": ("N", "N_EARLY"), "E": ("N", "N_EARLY"),
               "F": ("N", "N_EARLY"), "G": ("R", "D", "N", "S")}
    expected = set()
    for values in product(*choices.values()):
        changes = {(member, target): shift
                   for member, shift in zip(choices, values)
                   if shift != roster.effective()[member, target]}
        if len(changes) == 1 and validate_transition(roster, changes, [target], rules=rules).ok:
            expected.add(frozenset(changes.items()))
    result = solve(roster, target, max_members=1, max_changes=1, rules=rules)
    assert result.status == "COMPLETE"
    assert {frozenset(changed(plan).items()) for plan in result.plans} == expected


def test_standby_ot_still_available_when_conversion_disabled(make_roster, target):
    roster = make_roster(target, dict(A="D", B="D", C="D", D="N", E="N", F="N", G="S"),
                         senior=("D", "G"))
    rules = load_rules()
    rules["actions"].update(standby_conversion=False, standby_ot=True)
    result = solve(roster, target, max_changes=1, rules=rules)
    assert result.plans
    assert all(changed(plan) == {("G", target): "S_OT"} for plan in result.plans)
    roster.unavailability.append(
        {"member_id": "G", "date": target.isoformat(), "action": "standby_conversion", "status": "active"}
    )
    assert not solve(roster, target, max_changes=1, rules=rules).plans
