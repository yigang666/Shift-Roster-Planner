"""Independent roster coverage and work-hour validation."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from pathlib import Path
import calendar
import copy
import json
from zoneinfo import ZoneInfo


DAY = timedelta(days=1)
ZONE = ZoneInfo("Asia/Singapore")
WORK_TIMES = {"D": (8, 20), "N": (20, 32), "S": (8, 18), "S_OT": (8, 20), "N_EARLY": (18, 32)}
CODES = frozenset(WORK_TIMES) | {"O", "R", "L"}


@lru_cache(maxsize=1)
def _defaults():
    return json.loads(Path(__file__).with_name("config").joinpath("rules.json").read_text())


def load_rules(path=None):
    """Load the default or a complete operator-supplied configuration."""
    if path is None:
        return copy.deepcopy(_defaults())
    return json.loads(Path(path).read_text())


@lru_cache(maxsize=2048)
def at(day, hour):
    return datetime.combine(day, time(), ZONE) + timedelta(hours=hour)


@lru_cache(maxsize=8192)
def work_interval(day, code):
    """Return a working assignment's interval by roster start date."""
    if code not in WORK_TIMES:
        return None
    start, end = WORK_TIMES[code]
    return at(day, start), at(day, end)


@dataclass(frozen=True)
class Segment:
    label: str
    start: datetime
    end: datetime
    members: tuple[str, ...]
    normal: int
    minimum: int

    @property
    def headcount(self):
        return len(self.members)

    @property
    def normal_gap(self):
        return max(0, self.normal - self.headcount)

    @property
    def minimum_gap(self):
        return max(0, self.minimum - self.headcount)


@dataclass(frozen=True)
class DayCoverage:
    date: date
    status: str
    segments: tuple[Segment, ...]
    day_seniors: tuple[str, ...]
    night_seniors: tuple[str, ...]
    day_senior_gap: int
    night_senior_gap: int

    @property
    def deficits(self):
        return tuple(segment.minimum_gap for segment in self.segments) + (
            self.day_senior_gap, self.night_senior_gap,
        )

    @property
    def shortage_types(self):
        result = []
        if any(segment.minimum_gap for segment in self.segments):
            result.append("HEADCOUNT_SHORTAGE")
        if self.day_senior_gap or self.night_senior_gap:
            result.append("SENIOR_SHORTAGE")
        return tuple(result)


def coverage(roster, dates=None, *, shifts=None, rules=None):
    """Compute each staffed interval and each full-shift Senior requirement."""
    if shifts is None:
        shifts = roster.effective()
    rules = _defaults() if rules is None else rules
    counts = rules["coverage"]
    senior = rules["senior_coverage"]
    dates = {day for _, day in shifts} if dates is None else set(dates)
    schedules = defaultdict(list)
    for (member_id, day), code in shifts.items():
        member = roster.members.get(member_id)
        if day not in dates or member is None or not member.active:
            continue
        interval = work_interval(day, code)
        if interval:
            schedules[day].append((member_id, *interval, member.experience_level == "SENIOR"))

    result = {}
    for day in sorted(dates):
        intervals = schedules[day]
        segments = []
        periods = (
            ("08:00–18:00", 8, 18, counts["day_08_18_normal"], counts["day_08_18_min"]),
            ("18:00–20:00", 18, 20, counts["day_18_20_min"], counts["day_18_20_min"]),
            ("20:00–08:00", 20, 32, counts["night_min"], counts["night_min"]),
        )
        for label, start_hour, end_hour, normal, minimum in periods:
            start, end = at(day, start_hour), at(day, end_hour)
            # Split at actual interval events, so future shift definitions can
            # change personnel or headcount inside a reporting period.
            events = {start, end}
            events.update(point for _, first, last, _ in intervals
                          for point in (first, last) if start < point < end)
            ordered = sorted(events)
            for left, right in zip(ordered, ordered[1:]):
                members = tuple(sorted({m for m, first, last, _ in intervals
                                        if first <= left and last >= right}))
                segments.append(Segment(label, left, right, members, normal, minimum))

        def covering_seniors(start, end):
            return tuple(sorted({m for m, first, last, is_senior in intervals
                                 if is_senior and first <= at(day, start) and last >= at(day, end)}))

        day_seniors = covering_seniors(8, 20)
        night_seniors = covering_seniors(20, 32)
        # H14 is mandatory even if the configuration asks for a lower target.
        day_gap = max(0, max(1, senior["day_min"]) - len(day_seniors))
        night_gap = max(0, max(1, senior["night_min"]) - len(night_seniors))
        status = "NORMAL"
        if day_gap or night_gap or any(segment.minimum_gap for segment in segments):
            status = "CRITICAL"
        elif any(segment.normal_gap for segment in segments):
            status = "DEGRADED"
        result[day] = DayCoverage(day, status, tuple(segments), day_seniors, night_seniors,
                                  day_gap, night_gap)
    return result


def _hours(start, end):
    return (end - start).total_seconds() / 3600


def _day_portions(start, end):
    while start < end:
        day = start.date()
        boundary = min(end, at(day + DAY, 0))
        yield day, _hours(start, boundary)
        start = boundary


def monthly_hours(shifts, member_id):
    """Count work in calendar months, splitting shifts at local midnight."""
    totals = Counter()
    for (employee, day), code in shifts.items():
        if employee == member_id and (interval := work_interval(day, code)):
            for work_day, hours in _day_portions(*interval):
                totals[work_day.year, work_day.month] += hours
    return dict(totals)


@dataclass(frozen=True)
class Validation:
    errors: tuple[str, ...]
    unverified: tuple[str, ...]

    @property
    def ok(self):
        return not self.errors and not self.unverified


def _months_to_check(shift_days, before, after, member):
    months = set()
    for day in shift_days:
        months.add((day.year, day.month))
        for code in (before.get((member, day)), after.get((member, day))):
            interval = work_interval(day, code)
            if interval:
                months.update((part.year, part.month) for part, _ in _day_portions(*interval))
    return months


def _has_month_data(shifts, member, year, month):
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    # The preceding assignment can contribute hours on the first day.
    return all((member, first - DAY + offset * DAY) in shifts
               for offset in range((last - first).days + 2))


def _member_errors(member, schedule, changed_days, months, hour_rules):
    errors = []
    intervals = sorted((interval[0], interval[1], code, day)
                       for day, code in schedule.items()
                       if (interval := work_interval(day, code)))
    groups = []
    for interval in intervals:
        if groups and interval[0] <= groups[-1][1]:
            previous, end = groups[-1]
            previous.append(interval)
            groups[-1] = (previous, max(end, interval[1]))
        else:
            groups.append(([interval], interval[1]))

    daily = defaultdict(list)
    affected_days = changed_days | {day + DAY for day in changed_days}
    for group, group_end in groups:
        if any(item[3] in changed_days for item in group):
            first = group[0]
            if any(prior[1] > nxt[0] for prior, nxt in zip(group, group[1:])):
                errors.append(f"H03 {member} {first[3]} has overlapping work")
            if any(prior[2] in ("N", "N_EARLY") and nxt[2] in ("D", "S", "S_OT")
                   and prior[1] == nxt[0] for prior, nxt in zip(group, group[1:])):
                errors.append(f"H01 {member} {first[3]} immediately follows night work")
            exception = len(group) == 1 and first[2] == "N_EARLY" and hour_rules["night_early_exception"]
            if not exception and _hours(first[0], group_end) > hour_rules["continuous_max"]:
                errors.append(f"H07 {member} {first[3]} exceeds continuous hours")
        for start, end, code, _ in group:
            for day, hours in _day_portions(start, end):
                daily[day].append((hours, code))

    month_totals = Counter()
    for day, portions in daily.items():
        total = sum(hours for hours, _ in portions)
        month_totals[day.year, day.month] += total
        exception = (len(portions) == 1 and portions[0][1] == "N_EARLY"
                     and hour_rules["night_early_exception"])
        if day in affected_days and total > hour_rules["daily_max"] and not exception:
            errors.append(f"H09 {member} {day} exceeds daily hours ({total:g})")
    for year, month in sorted(months):
        total = month_totals[year, month]
        if total > hour_rules["monthly_max"]:
            errors.append(f"H10 {member} {year}-{month:02} exceeds monthly hours ({total:g})")
    return errors


def validate_transition(roster, changes, target_dates, *, rules=None, verify_data=True):
    """Check the complete effective candidate against the baseline and targets."""
    rules = _defaults() if rules is None else rules
    before = roster.effective()
    after = dict(before)
    errors = []
    unverified = []
    changed_members = defaultdict(set)
    affected_shifts = defaultdict(set)
    for (member_id, day), code in changes.items():
        key = member_id, day
        if member_id not in roster.members or not roster.members[member_id].active or key not in before:
            errors.append(f"{member_id} {day} is missing an active baseline assignment")
        elif code not in CODES or code == "L":
            errors.append(f"{member_id} {day} has invalid arrangement code {code}")
        elif before[key] == "L":
            errors.append(f"H02 {member_id} {day} is on leave")
        elif before[key] != code:
            after[key] = code
            changed_members[member_id].add(day)
            for assignment in (before[key], code):
                interval = work_interval(day, assignment)
                if interval:
                    if interval[0] < at(day, 20):
                        affected_shifts[day].add("Day")
                    if interval[1] > at(day, 20):
                        affected_shifts[day].add("Night")

    target_dates = set(target_dates)
    affected = target_dates | {day for dates in changed_members.values() for day in dates}
    baseline = coverage(roster, affected, shifts=before, rules=rules)
    candidate = coverage(roster, affected, shifts=after, rules=rules)
    for day, result in candidate.items():
        before_deficits = baseline[day].deficits
        if len(result.deficits) != len(before_deficits):
            # Fixed shift definitions share all three coverage boundaries.
            errors.append(f"H06 {day} cannot compare coverage by interval")
        elif any(new > old for old, new in zip(before_deficits, result.deficits)):
            errors.append(f"H06/H14 {day} introduces or worsens minimum coverage")
        if day in target_dates and any(result.deficits):
            errors.append(f"H06/H14 {day} retains a target shortage")
        elif day not in target_dates:
            for shift, gap in (("Day", result.day_senior_gap), ("Night", result.night_senior_gap)):
                if shift in affected_shifts[day] and gap:
                    errors.append(f"H14 {day} changed {shift} still lacks full-shift Senior coverage")

    member_schedules = defaultdict(dict)
    for (member_id, day), code in after.items():
        if member_id in changed_members:
            member_schedules[member_id][day] = code
    for member_id, days in sorted(changed_members.items()):
        months = _months_to_check(days, before, after, member_id)
        errors.extend(_member_errors(member_id, member_schedules[member_id], days, months, rules["hours"]))
        if verify_data:
            for day in sorted(days):
                if (member_id, day - DAY) not in after or (member_id, day + DAY) not in after:
                    unverified.append(f"{member_id} {day} lacks preceding or following assignment")
            for year, month in sorted(months):
                if not _has_month_data(after, member_id, year, month):
                    unverified.append(f"{member_id} {year}-{month:02} lacks complete month data")
    return Validation(tuple(errors), tuple(unverified))


def standby_rotation_issues(roster, cycle_start=None, *, rules=None):
    """Report deviations on the imported baseline without rewriting shifts.

    Per-employee cycle checks require an explicit cycle anchor and complete
    blocks. A fixed anchor avoids conflating a partial import with a violation.
    """
    rules = _defaults() if rules is None else rules
    policy = rules["base_standby"]
    active = {member_id for member_id, member in roster.members.items() if member.active}
    by_date = defaultdict(dict)
    for (member_id, day), code in roster.shifts.items():
        if member_id in active:
            by_date[day][member_id] = code
    issues = []
    for day, assignments in sorted(by_date.items()):
        if assignments.keys() == active:
            count = sum(code == "S" for code in assignments.values())
            if not policy["min"] <= count <= policy["max"]:
                issues.append(f"H12 {day} has {count} baseline standby assignments")
    if cycle_start is not None and by_date:
        step = timedelta(days=policy["cycle_days"])
        block = cycle_start + ((min(by_date) - cycle_start) // step) * step
        while block + step - DAY <= max(by_date):
            days = [block + offset * DAY for offset in range(policy["cycle_days"])]
            for member_id in sorted(active):
                if all(day in by_date and member_id in by_date[day] for day in days):
                    count = sum(by_date[day][member_id] == "S" for day in days)
                    if count != 1:
                        issues.append(f"H12 {member_id} cycle at {block} has {count} standby assignments")
            block += step
    return tuple(issues)
