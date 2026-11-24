from datetime import date, timedelta

import pytest

from rules import coverage, monthly_hours, validate_transition, work_interval


def test_tc01_baseline_is_normal(healthy, target):
    day = coverage(healthy, [target])[target]
    assert day.status == "NORMAL"
    assert [segment.headcount for segment in day.segments] == [4, 3, 3]
    assert day.day_seniors == ("A",)
    assert day.night_seniors == ("D",)


@pytest.mark.parametrize("replacement", ["D", "S"], ids=["day", "standby"])
def test_tc04_night_cannot_flow_into_morning(make_roster, target, replacement):
    yesterday = target - timedelta(days=1)
    roster = make_roster(target, dict(A="D", B="D", C="D", D="N", E="N", F="N", X="R"),
                         extra={("X", yesterday): "N"})
    result = validate_transition(roster, {("X", target): replacement}, [target])
    assert any("H01" in error for error in result.errors)
    assert not result.ok


def test_tc05_night_early_only_exception(healthy, target):
    start, end = work_interval(target, "N_EARLY")
    assert (end - start).total_seconds() == 14 * 3600
    assert start.hour == 18 and end.hour == 8
    assert validate_transition(healthy, {("D", target): "N_EARLY"}, [target]).ok


def test_tc06_ordinary_continuous_overtime_rejected(make_roster, target):
    yesterday = target - timedelta(days=1)
    roster = make_roster(target, dict(A="D", B="D", C="D", D="N", E="N", F="N", X="O"),
                         extra={("X", yesterday): "O"})
    changes = {("X", yesterday): "N", ("X", target): "D"}
    assert any("H07" in error for error in validate_transition(roster, changes, [target]).errors)


@pytest.mark.parametrize("last_shift,expected,valid", [("D", 264, True), ("N_EARLY", 266, False)])
def test_tc07_tc08_monthly_limit(make_roster, target, last_shift, expected, valid):
    days = [date(2026, 6, i) for i in range(1, 23) if i != target.day]
    extra = {("X", day): "D" for day in days}
    extra["X", days[-1]] = last_shift
    roster = make_roster(target, dict(A="D", B="D", C="D", D="N", E="N", F="N", X="O"),
                         extra=extra)
    shifts = roster.effective() | {("X", target): "D"}
    assert monthly_hours(shifts, "X")[(2026, 6)] == expected
    result = validate_transition(roster, {("X", target): "D"}, [target])
    assert result.ok is valid
    if not valid:
        assert any("H10" in error for error in result.errors)


def test_tc09_night_hours_split_at_month_boundary():
    shifts = {("A", date(2026, 6, 30)): "N"}
    assert monthly_hours(shifts, "A") == {(2026, 6): 4, (2026, 7): 8}


def test_tc10_same_day_swap_must_leave_a_covered_night(make_roster, target):
    assignments = dict(A="D", B="D", C="D", D="N", E="N", F="N", G="S")
    healthy = make_roster(target, assignments)
    swap = {("E", target): "S", ("G", target): "N"}
    assert validate_transition(healthy, swap, [target]).ok
    # Exchanging shifts on one date preserves aggregate headcount, so a
    # full reciprocal swap cannot repair a pre-existing night shortage.
    short = make_roster(target, assignments | {"F": "O"})
    result = validate_transition(short, swap, [target])
    assert not result.ok and any("target shortage" in error for error in result.errors)
    # An incomplete exchange would introduce a new minimum headcount gap.
    assert validate_transition(healthy, {("E", target): "S"}, [target]).errors


def test_tc11_cross_date_swap_cannot_create_future_gap(make_roster, target):
    tomorrow = target + timedelta(days=1)
    roster = make_roster(
        target, dict(A="D", B="D", C="O", D="N", E="N", F="N", X="O"),
        extra={("A", tomorrow): "D", ("B", tomorrow): "D", ("C", tomorrow): "D",
               ("D", tomorrow): "N", ("E", tomorrow): "N", ("F", tomorrow): "N"})
    assert validate_transition(
        roster, {("X", target): "D", ("C", tomorrow): "O"}, [target]
    ).errors


def test_tc19_missing_month_is_unverified(make_roster, target):
    roster = make_roster(target, dict(A="D", B="D", C="O", D="N", E="N", F="N", X="O"),
                         complete=False)
    result = validate_transition(roster, {("X", target): "D"}, [target])
    assert result.unverified
    assert not result.ok


def test_tc22_early_night_cannot_stack_with_adjacent_shift(healthy, target):
    result = validate_transition(
        healthy, {("D", target): "N_EARLY", ("D", target + timedelta(days=1)): "D"},
        [target])
    assert result.errors and not result.ok


@pytest.mark.parametrize(
    "day_codes,night_code,senior,status,day_seniors,night_seniors",
    [
        pytest.param(("D", "D", "D", "O"), "N", ("D",), "CRITICAL", (), ("D",), id="TC23"),
        pytest.param(("D", "D", "D", "O"), "N", ("A",), "CRITICAL", ("A",), (), id="TC24"),
        pytest.param(("D", "D", "D", "O"), "N", ("A", "D"), "DEGRADED", ("A",), ("D",), id="TC20-TC25"),
        pytest.param(("D", "D", "D", "S"), "N", ("D", "G"), "CRITICAL", (), ("D",), id="TC26"),
        pytest.param(("D", "D", "D", "S_OT"), "N", ("D", "G"), "NORMAL", ("G",), ("D",), id="TC27-ot"),
        pytest.param(("D", "D", "D", "D"), "N", ("D", "G"), "NORMAL", ("G",), ("D",), id="TC27-conversion"),
        pytest.param(("D", "D", "D", "O"), "N_EARLY", ("D",), "CRITICAL", (), ("D",), id="TC28"),
        pytest.param(("D", "D", "D", "S"), "N_EARLY", ("D", "G"), "CRITICAL", (), ("D",), id="TC30"),
    ],
)
def test_prd_senior_coverage(make_roster, target, day_codes, night_code, senior, status,
                             day_seniors, night_seniors):
    shifts = dict(zip("ABCG", day_codes)) | dict(D=night_code, E="N", F="N")
    roster = make_roster(target, shifts, senior=senior)
    day = coverage(roster, [target])[target]
    assert day.status == status
    assert day.day_seniors == day_seniors
    assert day.night_seniors == night_seniors


def test_tc29_swap_of_sole_seniors_invalid(make_roster, target):
    roster = make_roster(target, dict(A="D", B="D", C="D", D="N", E="N", F="N", X="S"))
    result = validate_transition(roster, {("A", target): "N", ("E", target): "D"}, [target])
    assert result.errors
    assert not result.ok


def test_affected_non_target_shift_requires_its_own_senior(make_roster, target):
    tomorrow = target + timedelta(days=1)
    assignments = dict(A="D", B="D", C="D", D="N", E="N", F="N", G="S")
    summer = {("A", tomorrow): "O", ("B", tomorrow): "D", ("C", tomorrow): "D",
              ("G", tomorrow): "S"}
    roster = make_roster(target, assignments, extra=summer)
    change = {("G", tomorrow): "D"}
    invalid = validate_transition(roster, change, [target])
    assert any("H14" in error for error in invalid.errors)

    roster = make_roster(target, assignments, extra=summer | {("A", tomorrow): "D"})
    assert coverage(roster, [tomorrow])[tomorrow].night_senior_gap == 1
    # A pre-existing night gap remains visible and the change only touches day.
    assert validate_transition(roster, change, [target]).ok
