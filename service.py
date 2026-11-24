"""Shared Manager workflow with atomic roster and audit updates."""

from dataclasses import asdict, replace
from datetime import UTC, date, datetime
from hashlib import sha256
from json import dumps
from uuid import uuid4

from rules import coverage, load_rules, validate_transition
from solver import ACTIONS, Change, legal_swap, refused, swap_action


def _fingerprint(roster):
    rows = [(member, day.isoformat(), shift)
            for (member, day), shift in sorted(roster.effective().items())]
    members = [asdict(member) for _, member in sorted(roster.members.items())]
    return sha256(dumps([roster.import_id, rows, members], sort_keys=True).encode()).hexdigest()


def _paired_swaps(roster, swaps, settings):
    if not swaps:
        return True
    first, *others = swaps
    first_key = first.member_id, first.date
    for index, second in enumerate(others):
        second_key = second.member_id, second.date
        if (
            first.old_shift == second.new_shift and first.new_shift == second.old_shift
            and first.action == second.action == swap_action(first_key, second_key)
            and legal_swap(roster, first_key, second_key, first.old_shift, second.old_shift, settings)
            and _paired_swaps(roster, others[:index] + others[index + 1:], settings)
        ):
            return True
    return False


def _check_plan(roster, target, changes):
    if not changes or len(changes) > 32:
        raise ValueError("A plan must contain between 1 and 32 assignments")
    baseline = roster.effective()
    rules = load_rules()
    settings = rules["actions"]
    mapping = {}
    swaps = []
    for change in changes:
        key = change.member_id, change.date
        if key in mapping or baseline.get(key) != change.old_shift or change.old_shift == change.new_shift:
            raise ValueError("Plan contains a duplicate, obsolete, or unchanged assignment")
        if change.member_id not in roster.members or refused(roster, key, change.action):
            raise ValueError("An employee is unavailable for this arrangement")
        if change.action in {"same_day_swap", "cross_date_swap"}:
            swaps.append(change)
        elif (change.new_shift, change.action) not in ACTIONS.get(change.old_shift, ()) or not settings.get(
            change.action, change.action not in {"off_standby", "direct_reassignment"}
        ):
            raise ValueError("The plan contains an action that is not enabled")
        mapping[key] = change.new_shift
    if not _paired_swaps(roster, swaps, settings):
        raise ValueError("Every swap must contain both valid assignments")
    result = validate_transition(roster, mapping, [target], rules=rules)
    if not result.ok:
        raise ValueError("; ".join((*result.errors, *result.unverified)))
    before = coverage(roster, [target])[target]
    if before.status != "CRITICAL":
        after = coverage(roster, [target], shifts={**baseline, **mapping})[target]
        gap_before = sum(segment.normal_gap for segment in before.segments)
        gap_after = sum(segment.normal_gap for segment in after.segments)
        if gap_after >= gap_before:
            raise ValueError("The plan does not improve target coverage")
    return mapping


def save_plan(store, revision, target, plan, actor):
    plan_id = uuid4().hex

    def update(roster):
        _check_plan(roster, target, plan.changes)
        record = {
            "plan_id": plan_id,
            "base_revision": roster.revision,
            "baseline": _fingerprint(roster),
            "target": target.isoformat(),
            "status": "AWAITING_CONFIRMATION",
            "changes": [{**asdict(change), "date": change.date.isoformat()} for change in plan.changes],
            "responses": {},
            "score": list(plan.score),
            "created_by": actor,
            "created_at": datetime.now(UTC).isoformat(),
        }
        return replace(roster, plans={**roster.plans, plan_id: record})

    return store.update(revision, update, actor=actor, event="plan_proposed", details=plan_id)


def _plan(roster, plan_id, statuses):
    existing = roster.plans.get(plan_id)
    if not existing or existing["status"] not in statuses:
        raise ValueError("Plan is unavailable or its status has changed")
    if existing["baseline"] != _fingerprint(roster):
        raise ValueError("Plan is stale. Refresh the roster and search again.")
    return existing


def record_response(store, revision, plan_id, member_id, accepted, actor):
    def update(roster):
        plan = _plan(roster, plan_id, {"AWAITING_CONFIRMATION", "READY_TO_COMMIT"})
        assignments = [change for change in plan["changes"] if change["member_id"] == member_id]
        if not assignments:
            raise ValueError("Employee is not part of this plan")
        if type(accepted) is not bool:
            raise ValueError("Consent must be recorded as accepted or rejected")
        responses = {**plan["responses"], member_id: accepted}
        unavailable = list(roster.unavailability)
        status = "AWAITING_CONFIRMATION"
        if not accepted:
            status = "REJECTED"
            unavailable.extend(
                {"member_id": member_id, "date": change["date"], "action": change["action"],
                 "reason": "Employee declined", "status": "active"}
                for change in assignments
            )
        elif all(responses.get(change["member_id"]) is True for change in plan["changes"]):
            status = "READY_TO_COMMIT"
        updated = {**plan, "responses": responses, "status": status}
        return replace(roster, plans={**roster.plans, plan_id: updated}, unavailability=unavailable)

    return store.update(revision, update, actor=actor, event="employee_response",
                        details=f"{plan_id} {member_id} {'accepted' if accepted else 'rejected'}")


def commit_plan(store, revision, plan_id, actor):
    def update(roster):
        plan = _plan(roster, plan_id, {"READY_TO_COMMIT"})
        changes = tuple(Change(item["member_id"], date.fromisoformat(item["date"]),
                               item["old_shift"], item["new_shift"], item["action"])
                        for item in plan["changes"])
        if not all(plan["responses"].get(change.member_id) is True for change in changes):
            raise ValueError("H08 requires every employee to consent")
        mapping = _check_plan(roster, date.fromisoformat(plan["target"]), changes)
        plans = dict(roster.plans)
        for other_id, other in roster.plans.items():
            if other["status"] in {"AWAITING_CONFIRMATION", "READY_TO_COMMIT"}:
                status = "COMMITTED" if other_id == plan_id else "STALE"
                plans[other_id] = {**other, "status": status}
        return replace(roster, overrides={**roster.overrides, **mapping}, plans=plans)

    return store.update(revision, update, actor=actor, event="plan_committed", details=plan_id)


def plan_status(roster, plan):
    status = plan["status"]
    if status in {"AWAITING_CONFIRMATION", "READY_TO_COMMIT"} and plan["baseline"] != _fingerprint(roster):
        return "STALE"
    return status


def cancel_leave(store, revision, member_id, start, end, restored_shift, actor):
    """Record a Manager-confirmed cancellation only if restored working hours are verifiable."""
    def update(roster):
        cancelled = roster.with_cancelled_leave(member_id, start, end, restored_shift)
        effective = cancelled.effective()
        keys = roster.leaves.keys() - cancelled.leaves.keys()
        restored = {key: effective[key] for key in keys if effective[key] not in {"O", "R"}}
        if restored:
            baseline = replace(cancelled, overrides={**cancelled.overrides, **dict.fromkeys(restored, "O")})
            result = validate_transition(baseline, restored, [])
            # Leave cancellation restores coverage. Remaining gaps are handled in a separate plan.
            errors = [error for error in result.errors if not error.startswith(("H06", "H14"))]
            if errors or result.unverified:
                raise ValueError("; ".join((*errors, *result.unverified)))
        return cancelled

    return store.update(revision, update, actor=actor, event="leave_cancelled",
                        details=f"{member_id} {start.isoformat()} to {end.isoformat()}")
