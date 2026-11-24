"""Deterministic bounded search over roster changes and atomic swap pairs."""

from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from itertools import product
from datetime import date, timedelta
from time import monotonic

from ortools.sat.python import cp_model

from rules import at, coverage, load_rules, validate_transition, work_interval


@dataclass(frozen=True, order=True)
class Change:
    member_id: str
    date: date
    old_shift: str
    new_shift: str
    action: str


@dataclass(frozen=True)
class Plan:
    changes: tuple[Change, ...]
    score: tuple[int, ...]


@dataclass(frozen=True)
class SearchResult:
    status: str
    plans: tuple[Plan, ...] = ()
    conditional: tuple[Plan, ...] = ()
    unverified: tuple[str, ...] = ()
    remaining_dates: tuple[date, ...] = ()


# Standby conversion represents both administratively equivalent extensions.
ACTIONS = {
    "S": (("D", "standby_conversion"), ("S_OT", "standby_ot")),
    "N": (("N_EARLY", "night_early"), ("D", "direct_reassignment")),
    "D": (("N", "direct_reassignment"),),
    "O": (("D", "off_recall"), ("N", "off_recall"), ("S", "off_standby")),
    "R": (("D", "reset_recall"), ("N", "reset_recall"), ("S", "reset_standby")),
}
SWAPPABLE = {"D", "N", "O", "R", "S"}
DAY = timedelta(days=1)
STANDBY_EXTENSIONS = {"standby_conversion", "standby_ot"}


def refused(roster, key, action):
    member_id, day = key
    scope = STANDBY_EXTENSIONS if action in STANDBY_EXTENSIONS else {action}
    return any(
        row["member_id"] == member_id
        and str(row["date"]) == day.isoformat()
        and row.get("status", "active").lower() == "active"
        and (row.get("action") in (None, "", "*") or row.get("action") in scope)
        for row in roster.unavailability
    )


def swap_action(first, second):
    return "same_day_swap" if first[1] == second[1] else "cross_date_swap"


def legal_swap(roster, first, second, old_first, old_second, settings):
    return (
        first[0] != second[0]
        and old_first != old_second
        and old_first in SWAPPABLE and old_second in SWAPPABLE
        and (first[1] == second[1] or settings.get("cross_date_swap", True))
        and (
            roster.members[first[0]].team == roster.members[second[0]].team
            or settings.get("cross_team_swap", True)
        )
    )


def _hours(day, shift):
    interval = work_interval(day, shift)
    return int((interval[1] - interval[0]).total_seconds() // 3600) if interval else 0


def _schedule_model(roster, baseline, days, settings, deadline):
    model = cp_model.CpModel()
    keys = sorted(key for key in baseline if key[1] in days and baseline[key] != "L"
                  and roster.members[key[0]].active)
    incoming = defaultdict(list)
    details = defaultdict(list)
    for index, key in enumerate(keys):
        if monotonic() >= deadline:
            return None
        old = baseline[key]
        conversion = settings.get("standby_conversion", True) and not refused(roster, key, "standby_conversion")
        for new, action in ACTIONS.get(old, ()):
            if action == "standby_ot" and conversion:
                continue
            if settings.get(action, action not in {"off_standby", "direct_reassignment"}) and not refused(roster, key, action):
                flag = model.new_bool_var(f"change_{index}_{new}")
                incoming[key, new].append(flag)
                details[key].append((flag, Change(*key, old, new, action)))
        for other_index in range(index):
            other = keys[other_index]
            other_old = baseline[other]
            action = swap_action(key, other)
            if not legal_swap(roster, key, other, old, other_old, settings):
                continue
            if refused(roster, key, action) or refused(roster, other, action):
                continue
            flag = model.new_bool_var(f"swap_{index}_{other_index}")
            incoming[key, other_old].append(flag)
            incoming[other, old].append(flag)
            details[key].append((flag, Change(*key, old, other_old, action)))
            details[other].append((flag, Change(*other, other_old, old, action)))

    choices = {}
    for index, key in enumerate(keys):
        old = baseline[key]
        options = {old: model.new_bool_var(f"keep_{index}")}
        for new in sorted({change.new_shift for _, change in details[key]}):
            options[new] = model.new_bool_var(f"assign_{index}_{new}")
            model.add(options[new] == sum(incoming[key, new]))
        model.add_exactly_one(options.values())
        choices[key] = options
    return model, choices, details


def _add_coverage(model, roster, baseline, choices, before, target, rules):
    # PRD shifts change coverage only at 08:00, 18:00 and 20:00.
    intervals = []
    for key, old in baseline.items():
        if not roster.members[key[0]].active:
            continue
        for shift, presence in choices.get(key, {old: 1}).items():
            interval = work_interval(key[1], shift)
            if interval:
                intervals.append((key[0], *interval, presence))

    def count(start, end, senior=False):
        return sum(
            presence for member_id, begins, ends, presence in intervals
            if begins <= start and ends >= end
            and (not senior or roster.members[member_id].experience_level == "SENIOR")
        )

    deficit = []
    for day, report in before.items():
        for segment in report.segments:
            total = count(segment.start, segment.end)
            minimum = segment.minimum if day == target else min(segment.minimum, segment.headcount)
            model.add(total >= minimum)
            if day == target:
                gap = model.new_int_var(0, segment.normal, f"gap_{segment.label}")
                model.add_max_equality(gap, [segment.normal - total, 0])
                deficit.append(gap)
        for name, start, end, seniors in (
            ("day", at(day, 8), at(day, 20), report.day_seniors),
            ("night", at(day, 20), at(day, 32), report.night_seniors),
        ):
            minimum = max(1, rules["senior_coverage"][f"{name}_min"])
            required = minimum if day == target else min(minimum, len(seniors))
            senior_total = count(start, end, senior=True)
            model.add(senior_total >= required)
            if required < minimum:
                for key, options in choices.items():
                    if key[1] != day:
                        continue
                    old_interval = work_interval(day, baseline[key])
                    for shift, selected in options.items():
                        if shift == baseline[key]:
                            continue
                        new_interval = work_interval(day, shift)
                        if any(interval and interval[0] < end and interval[1] > start
                               for interval in (old_interval, new_interval)):
                            model.add(senior_total >= minimum).only_enforce_if(selected)
    if before[target].status == "DEGRADED":
        model.add(sum(deficit) < sum(segment.normal_gap for segment in before[target].segments))
    return deficit


def _work_portions(day, shift):
    interval = work_interval(day, shift)
    if interval is None:
        return ()
    start, end = interval
    midnight = at(day + DAY, 0)

    def duration(first, last):
        return int((last - first).total_seconds() // 3600)

    if end <= midnight:
        return ((day, duration(start, end)),)
    return ((day, duration(start, midnight)), (day + DAY, duration(midnight, end)))


def _add_hours(model, baseline, choices, rules):
    settings = rules["hours"]
    daily_limit = settings["daily_max"]
    continuous_limit = settings["continuous_max"]
    night_exception = settings["night_early_exception"]
    members = {key[0] for key in choices}
    changes_by_month = defaultdict(list)
    monthly = defaultdict(list)
    fixed_monthly = Counter()
    for key, old in baseline.items():
        member, day = key
        if member not in members:
            continue
        options = choices.get(key)
        for shift, presence in (options or {old: 1}).items():
            portions = _work_portions(day, shift)
            months = defaultdict(int)
            for work_day, hours in portions:
                months[work_day.year, work_day.month] += hours
            if options:
                for month, hours in months.items():
                    monthly[member, month].append(presence * hours)
                if shift != old:
                    touched = {(day.year, day.month), *months}
                    touched.update((work_day.year, work_day.month)
                                   for work_day, _ in _work_portions(day, old))
                    for month in touched:
                        changes_by_month[member, month].append(presence)
            else:
                for month, hours in months.items():
                    fixed_monthly[member, month] += hours

    for key, flags in changes_by_month.items():
        bound = model.add(sum(monthly[key]) + fixed_monthly[key] <= settings["monthly_max"])
        changed = model.new_bool_var("month_changed")
        model.add_max_equality(changed, flags)
        bound.only_enforce_if(changed)

    affected = set(choices) | {(member, day + DAY) for member, day in choices}
    for key in sorted(affected):
        member, day = key
        prior_key = member, day - DAY
        old, prior_old = baseline.get(key), baseline.get(prior_key)
        current_options = choices.get(key, {old: 1})
        prior_options = choices.get(prior_key, {prior_old: 1})
        for (prior, left), (current, right) in product(prior_options.items(), current_options.items()):
            if prior == prior_old and current == old:
                continue
            earlier = work_interval(day - DAY, prior)
            later = work_interval(day, current)
            portions = [(shift, hours) for start, shift in ((day - DAY, prior), (day, current))
                        for work_day, hours in _work_portions(start, shift) if work_day == day]
            daily_exception = len(portions) == 1 and portions[0][0] == "N_EARLY" and night_exception
            invalid_daily = sum(hours for _, hours in portions) > daily_limit and not daily_exception
            invalid_continuous = (
                current != old and later and _hours(day, current) > continuous_limit
                and not (current == "N_EARLY" and night_exception)
            )
            adjacent_work = earlier and later and earlier[1] >= later[0]
            if invalid_daily or invalid_continuous or adjacent_work:
                model.add(left + right <= 1)


def _priority(model, choices, baseline, target, deficit, max_changes):
    changed = []
    by_member = defaultdict(list)
    recalled = []
    extra = []
    distant = []
    for key, options in choices.items():
        old = baseline[key]
        flag = options[old].Not()
        changed.append(flag)
        by_member[key[0]].append(flag)
        if old in {"O", "R"}:
            recalled.append(flag)
        if key[1] != target:
            distant.append(flag)
        extra.extend(
            selected * (_hours(key[1], new) - _hours(key[1], old))
            for new, selected in options.items() if new != old
        )
    people = []
    for member_id, flags in by_member.items():
        person = model.new_bool_var(f"affected_{member_id}")
        model.add_max_equality(person, flags)
        people.append(person)
    # Use a lexicographic objective within the enforced change-count bound.
    base = max_changes + 1
    normal_gap = sum(deficit)
    emergency = model.new_bool_var("below_normal")
    model.add(normal_gap > 0).only_enforce_if(emergency)
    model.add(normal_gap == 0).only_enforce_if(emergency.Not())
    extra_hours = sum(extra)
    positive_extra = model.new_int_var(0, 14 * max_changes, "additional_hours")
    model.add_max_equality(positive_extra, [extra_hours, 0])
    criteria = (emergency, sum(people), sum(recalled), positive_extra, sum(distant), sum(changed))
    objective = criteria[0]
    for criterion, radix in zip(criteria[1:], (base, base, 14 * max_changes + 1, base, base)):
        objective = objective * radix + criterion
    model.minimize(objective)
    return people, changed, criteria


def _conditional(roster, target, rules):
    if not rules["actions"].get("critical_leave_cancel_request", True):
        return ()
    options = []
    for key, original in sorted(roster.leaves.items()):
        member_id, day = key
        if day != target or not original or refused(roster, key, "cancel_leave_request"):
            continue
        # Restore against an off-duty baseline to validate both restored hours and resulting coverage.
        temporary = roster.with_cancelled_leave(member_id, day, day, original)
        temporary = replace(temporary, overrides={**temporary.overrides, key: "O"})
        check = validate_transition(temporary, {key: original}, [target], rules=rules)
        if check.ok:
            options.append(Plan((Change(*key, "L", original, "cancel_leave_request"),), ()))
    return tuple(options)


def search(roster, target, *, days_before=3, days_after=3, max_members=4,
           max_changes=8, timeout=30, top=20, rules=None):
    """Return ranked plans and an explicit completeness status."""
    if min(days_before, days_after) < 0 or max_members < 1 or not 1 <= max_changes <= 32 or top < 1:
        raise ValueError("Invalid search bounds")
    deadline = monotonic() + max(0, timeout)
    rules = load_rules() if rules is None else rules
    baseline = roster.effective()
    days = {target + offset * DAY for offset in range(-days_before, days_after + 1)}
    if target not in {day for _, day in baseline}:
        return SearchResult("UNVERIFIED", unverified=("Target date is missing from the roster",))
    before = coverage(roster, sorted(days & {day for _, day in baseline}), rules=rules)
    if before[target].status == "NORMAL":
        return SearchResult("NO_CHANGE")
    if monotonic() >= deadline:
        return SearchResult("UNKNOWN")

    schedule = _schedule_model(roster, baseline, days, rules["actions"], deadline)
    if schedule is None:
        return SearchResult("UNKNOWN")
    model, choices, details = schedule
    deficit = _add_coverage(model, roster, baseline, choices, before, target, rules)
    _add_hours(model, baseline, choices, rules)
    people, changes, criteria = _priority(model, choices, baseline, target, deficit, max_changes)
    model.add(sum(people) <= max_members)
    model.add(sum(changes) <= max_changes)

    plans = []
    unverified = set()
    engine = cp_model.CpSolver()
    engine.parameters.num_search_workers = 1
    status = "UNKNOWN"
    while len(plans) <= top:
        remaining = deadline - monotonic()
        if remaining <= 0:
            status = "PARTIAL/TIMEOUT" if plans else "UNKNOWN"
            break
        engine.parameters.max_time_in_seconds = remaining
        result = engine.solve(model)
        if result == cp_model.INFEASIBLE:
            if unverified:
                status = "PARTIAL/UNVERIFIED" if plans else "UNVERIFIED"
            else:
                status = "COMPLETE" if plans else "INFEASIBLE"
            break
        if result not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            status = "PARTIAL/TIMEOUT" if plans else "UNKNOWN"
            break
        selected = tuple(sorted(change for entries in details.values()
                                for flag, change in entries if engine.boolean_value(flag)))
        mapping = {(change.member_id, change.date): change.new_shift for change in selected}
        check = validate_transition(roster, mapping, [target], rules=rules)
        if check.ok:
            plans.append(Plan(selected, tuple(engine.value(criterion) for criterion in criteria)))
        elif not check.errors:
            unverified.update(check.unverified)
        if check.ok and result == cp_model.OPTIMAL:
            # Suppress supersets of already valid assignments at the same coverage grade.
            # Any normal solution ranked before an emergency-only one.
            selected_changes = [choices[key][new].Not() for key, new in mapping.items()]
            if plans[-1].score[0]:
                selected_changes.append(criteria[0].Not())
            model.add_bool_or(selected_changes)
        else:
            model.add_bool_or(
                option.Not() for options in choices.values()
                for option in options.values() if engine.boolean_value(option)
            )
        if result == cp_model.FEASIBLE:
            status = "PARTIAL/TIMEOUT" if plans else "UNKNOWN"
            break
    if len(plans) > top and status != "PARTIAL/TIMEOUT":
        status = "PARTIAL/LIMIT"
    conditional = (
        _conditional(roster, target, rules)
        if status == "INFEASIBLE" and before[target].status == "CRITICAL" else ()
    )
    return SearchResult(status, tuple(sorted(plans[:top], key=lambda plan: (plan.score, plan.changes))),
                        conditional, tuple(sorted(unverified)),
                        tuple(day for day, report in before.items() if day != target and any(report.deficits)))
