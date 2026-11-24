"""Streamlit entry point for the manager's local roster workspace."""

from __future__ import annotations

import csv
from io import StringIO
import os
from pathlib import Path

import streamlit as st

from roster import Store, export_roster, import_roster, read_members, sample_roster
from rules import coverage, load_rules, monthly_hours, standby_rotation_issues, work_interval
from service import cancel_leave, commit_plan, plan_status, record_response, save_plan
from solver import search


PAGES = (
    "Master Roster",
    "Leave Management",
    "Manpower Coverage",
    "Arrangement Advisor",
    "Confirmation & History",
)
STORE_PATH = Path(__file__).resolve().parent / "data"


def records_csv(records):
    if not records:
        return ""
    columns = list(dict.fromkeys(key for record in records for key in record))
    output = StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=columns)
    writer.writeheader()
    writer.writerows(records)
    return output.getvalue()


def published(store, revision, transform, actor, event, details):
    store.update(revision, transform, actor=actor, event=event, details=details)
    st.rerun()


def dates_in(shifts):
    return sorted({day for _, day in shifts})


def roster_view(roster):
    shifts = roster.effective()
    dates = dates_in(shifts)
    if not dates:
        st.info("The roster has no dates.")
        return
    mode = st.radio("Roster version", ("Effective", "Original"), horizontal=True)
    if mode == "Original":
        shifts = roster.source_shifts or roster.shifts
    months = sorted({day.strftime("%Y-%m") for day in dates})
    month = st.selectbox("Month", months)
    team = st.selectbox("Team", ("All", *sorted({m.team for m in roster.members.values()})))
    experience = st.selectbox("Experience", ("All", "SENIOR", "JUNIOR"))
    members = [
        member for member in roster.members.values()
        if (team == "All" or member.team == team)
        and (experience == "All" or member.experience_level == experience)
    ]
    selected = st.multiselect(
        "Employees", members, format_func=lambda member: f"{member.name} ({member.member_id})"
    )
    display_dates = [day for day in dates if day.strftime("%Y-%m") == month]
    rows = []
    for member in selected or members:
        row = {
            "Employee": member.name,
            "ID": member.member_id,
            "Team": member.team,
            "Experience": member.experience_level,
        }
        row.update({day.isoformat(): shifts.get((member.member_id, day), "") for day in display_dates})
        rows.append(row)
    st.dataframe(rows, hide_index=True)
    st.download_button(
        "Download roster CSV",
        export_roster(roster, effective=mode == "Effective"),
        f"{mode.lower()}_roster.csv",
        "text/csv",
    )


def master_roster(store, roster, actor):
    revision = roster.revision if roster is not None else 0
    with st.expander("Import a schedule", expanded=roster is None):
        members_file = st.file_uploader("Employee data CSV", type="csv")
        schedule_file = st.file_uploader("Schedule CSV", type="csv")
        codes = st.text_input("Leave codes, comma-separated", value="L")
        st.caption("Use a date and shift per row, or one YYYY-MM-DD column per roster date.")
        if schedule_file:
            try:
                if members_file:
                    members = read_members(members_file.getvalue().decode("utf-8-sig"))
                elif roster:
                    members = roster.members
                else:
                    raise ValueError("Upload employee data with the first schedule.")
                leave_codes = tuple(code.strip() for code in codes.split(",") if code.strip())
                schedule = schedule_file.getvalue().decode("utf-8")
                imported = import_roster(schedule, members, leave_codes=leave_codes)
                st.caption(
                    f"{len(imported.members)} employees · "
                    f"{len(dates_in(imported.shifts))} dates · {len(imported.leaves)} leave entries"
                )
                rotation_issues = standby_rotation_issues(imported)
                if rotation_issues:
                    with st.expander(f"Baseline standby deviations ({len(rotation_issues)})"):
                        st.write(rotation_issues)
                snapshot = export_roster(imported, effective=False)
                st.dataframe(list(csv.DictReader(StringIO(snapshot)))[:15], hide_index=True)
                if roster:
                    st.warning("Import starts a new baseline. The previous revision remains in history.")
                if st.button("Import schedule", type="primary"):
                    store.import_schedule(revision, schedule, members, actor=actor, leave_codes=leave_codes)
                    st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        if roster is None and st.button("Load 19-employee example"):
            published(store, revision, lambda _: sample_roster(), actor, "IMPORT", "Synthetic example")
    if roster is not None:
        roster_view(roster)


def coverage_rows(roster, report):
    def names(member_ids):
        return ", ".join(f"{roster.members[mid].name} ({mid})" for mid in member_ids)

    rows = []
    for day, daily in sorted(report.items()):
        for segment in daily.segments:
            rows.append({
                "Date": day.isoformat(), "Status": daily.status, "Interval": segment.label,
                "People": segment.headcount, "Normal target": segment.normal,
                "Minimum": segment.minimum, "Normal gap": segment.normal_gap,
                "Minimum gap": segment.minimum_gap, "Employees": names(segment.members),
            })
    return rows


def senior_rows(roster, report):
    rows = []
    for day, daily in sorted(report.items()):
        shifts = (
            ("Day", daily.day_seniors, daily.day_senior_gap),
            ("Night", daily.night_seniors, daily.night_senior_gap),
        )
        for name, members, gap in shifts:
            rows.append({
                "Date": day.isoformat(), "Shift": name, "Full-shift seniors": len(members),
                "Senior gap": gap,
                "Employees": ", ".join(f"{roster.members[mid].name} ({mid})" for mid in members),
            })
    return rows


def show_coverage(roster, report):
    st.dataframe(coverage_rows(roster, report), hide_index=True)
    st.markdown("**Full-shift Senior coverage**")
    st.dataframe(senior_rows(roster, report), hide_index=True)


def leave_management(store, roster, actor):
    st.caption("Leave applies to the roster date on which a shift begins, including night shifts.")
    dates = dates_in(roster.shifts)
    members = sorted(mid for mid, member in roster.members.items() if member.active)
    if not members:
        st.info("There are no active employees.")
        return
    employee = st.selectbox(
        "Employee", members, format_func=lambda mid: f"{roster.members[mid].name} ({mid})"
    )
    leaves = []
    for (mid, day), original in sorted(roster.leaves.items(), key=lambda item: (item[0][1], item[0][0])):
        leaves.append({
            "Employee": roster.members[mid].name, "ID": mid, "Date": day.isoformat(),
            "Restorable shift": original or "Unknown",
        })
    if leaves:
        st.dataframe(leaves, hide_index=True)
    else:
        st.info("No active leave entries.")
    operation = st.radio("Action", ("Add or simulate leave", "Cancel leave"), horizontal=True)
    start = st.date_input("Start date", min_value=dates[0], max_value=dates[-1], value=dates[0])
    end = st.date_input("End date", min_value=start, max_value=dates[-1], value=start)
    details = f"{employee} {start.isoformat()} through {end.isoformat()}"
    if operation == "Add or simulate leave":
        if st.button("Simulate leave"):
            simulated = roster.with_leave(employee, start, end)
            before, after = st.columns(2)
            affected = [day for day in dates if start <= day <= end]
            with before:
                st.markdown("**Current coverage**")
                show_coverage(roster, coverage(roster, affected))
            with after:
                st.markdown("**Coverage with proposed leave**")
                show_coverage(simulated, coverage(simulated, affected))
        if st.button("Add leave", type="primary"):
            published(
                store, roster.revision, lambda current: current.with_leave(employee, start, end),
                actor, "ADD_LEAVE", details,
            )
    else:
        confirmed_shift = st.selectbox(
            "Verified original shift if the import omitted it",
            (None, "D", "N", "S", "O", "R", "S_OT", "N_EARLY"),
            format_func=lambda code: code or "Use the recorded shift",
        )
        if st.button("Record confirmed leave cancellation", type="primary"):
            cancel_leave(store, roster.revision, employee, start, end, confirmed_shift, actor)
            st.rerun()


def coverage_dashboard(roster):
    report = coverage(roster)
    if not report:
        st.info("No coverage dates are available.")
        return
    groups = {"CRITICAL": "🔴", "DEGRADED": "🟠", "NORMAL": "🟢"}
    status_filter = st.multiselect("Coverage status", list(groups), default=list(groups))
    visible = {day: item for day, item in report.items() if item.status in status_filter}
    if not visible:
        st.info("No dates match this filter.")
        return
    rows = [
        {
            "Date": day.isoformat(),
            "Coverage": f"{groups[item.status]} {item.status}",
            "Shortages": ", ".join(item.shortage_types),
            "Day Senior gap": item.day_senior_gap,
            "Night Senior gap": item.night_senior_gap,
        }
        for day, item in sorted(visible.items())
    ]
    st.dataframe(rows, hide_index=True)
    selected = st.selectbox(
        "Inspect date", sorted(visible),
        format_func=lambda day: f"{day.isoformat()} · {visible[day].status}",
    )
    show_coverage(roster, {selected: visible[selected]})


def planned_hours(day, shift):
    interval = work_interval(day, shift)
    if interval is None:
        return 0
    start, end = interval
    return (end - start).total_seconds() / 3600


def describe_plan(roster, changes, target, *, context_dates=(), conditional=False):
    original = roster.effective()
    proposed = original.copy()
    change_days = set()
    employees = set()
    rows = []
    for change in changes:
        member = roster.members[change.member_id]
        shift_date = change.date
        employees.add(change.member_id)
        change_days.add(shift_date)
        proposed[(change.member_id, shift_date)] = change.new_shift
        rows.append({
            "Employee": member.name, "ID": member.member_id, "Team": member.team,
            "Date": shift_date.isoformat(), "Original": change.old_shift, "Proposed": change.new_shift,
            "Action": change.action,
            "Planned hours change": (
                planned_hours(shift_date, change.new_shift) - planned_hours(shift_date, change.old_shift)
            ),
        })
    st.dataframe(rows, hide_index=True)
    if not rows:
        return
    st.caption("Employees to contact: " + ", ".join(roster.members[mid].name for mid in sorted(employees)))
    months = []
    for member_id in sorted(employees):
        old = monthly_hours(original, member_id)
        new = monthly_hours(proposed, member_id)
        for year, month in sorted(old.keys() | new.keys()):
            if any((day.year, day.month) == (year, month) for day in change_days) or old.get(
                (year, month), 0
            ) != new.get((year, month), 0):
                months.append({
                    "Employee": roster.members[member_id].name, "Month": f"{year}-{month:02d}",
                    "Before hours": old.get((year, month), 0), "After hours": new.get((year, month), 0),
                })
    st.markdown("**Monthly hours**")
    st.dataframe(months, hide_index=True)
    if not conditional:
        rest_days = sum(change.old_shift in {"O", "R"} for change in changes)
        extra = sum(row["Planned hours change"] for row in rows)
        st.caption(
            f"{len(employees)} employees affected · {rest_days} rest days changed · "
            f"{extra:+g} total planned hours"
        )
    dates = change_days | {target} | set(context_dates)
    before, after = st.columns(2)
    with before:
        st.markdown("**Before**")
        show_coverage(roster, coverage(roster, dates))
    with after:
        st.markdown("**After**")
        show_coverage(roster, coverage(roster, dates, shifts=proposed))


def arrangement_advisor(store, roster, actor):
    dates = dates_in(roster.shifts)
    target = st.selectbox("Target date", dates)
    defaults = load_rules()["search"]
    with st.expander("Search limits"):
        before = st.number_input("Days before target", 0, 31, defaults["days_before"])
        after = st.number_input("Days after target", 0, 31, defaults["days_after"])
        member_limit = st.number_input("Maximum employees changed", 1, 19, defaults["max_changed_members"])
        assignment_limit = st.number_input("Maximum assignments changed", 1, 32, defaults["max_changed_assignments"])
        timeout = st.number_input("Time limit (seconds)", 1, 300, defaults["time_limit_seconds"])
        top = st.number_input("Maximum plans to display", 1, 100, 20)
    signature = (roster.revision, target, before, after, member_limit, assignment_limit, timeout, top)
    if st.button("Find arrangements", type="primary"):
        with st.spinner("Checking allowed changes and coverage…"):
            result = search(
                roster, target, days_before=before, days_after=after, max_members=member_limit,
                max_changes=assignment_limit, timeout=timeout, top=top,
            )
        st.session_state["arrangements"] = signature, result
    stored = st.session_state.get("arrangements")
    if stored is None or stored[0] != signature:
        return
    result = stored[1]
    st.write(f"Search status **{result.status}**")
    if result.status == "NO_CHANGE":
        st.info("The target meets normal headcount and full-shift Senior coverage.")
    elif result.status == "INFEASIBLE":
        st.warning("No eligible plan was found within the selected search limits.")
    elif result.status in {"PARTIAL/TIMEOUT", "UNKNOWN"}:
        st.warning("The search reached its time limit before it could verify all options.")
    elif result.status == "PARTIAL/LIMIT":
        st.info(f"Showing the first {top} ranked options. Increase the display limit to see more.")
    if result.remaining_dates:
        st.caption(
            "Existing minimum coverage gaps elsewhere in the search window: "
            + ", ".join(day.isoformat() for day in result.remaining_dates)
        )
    if result.unverified:
        st.warning("Some candidates could not be verified against the available roster.")
        st.write(result.unverified)
    page_size = 10
    offset = 0
    if len(result.plans) > page_size:
        pages = (len(result.plans) + page_size - 1) // page_size
        page = st.selectbox("Plan page", range(1, pages + 1), key=f"page_{signature}")
        offset = (page - 1) * page_size
    for index, plan in enumerate(result.plans[offset:offset + page_size], offset + 1):
        level = "minimum coverage" if plan.score[0] else "normal coverage"
        with st.expander(f"Rank {index} · {level}", expanded=index == 1):
            describe_plan(roster, plan.changes, target, context_dates=result.remaining_dates)
            if st.button("Send to confirmation", key=f"save_plan_{index}"):
                save_plan(store, roster.revision, target, plan, actor)
                st.session_state["notice"] = "Plan saved. Record employee responses in Confirmation & History."
                st.rerun()
    if result.conditional:
        st.warning("Ask the employee before cancelling leave. Record the cancellation in Leave Management and search again.")
        for index, plan in enumerate(result.conditional, 1):
            with st.expander(f"Conditional leave request {index}"):
                describe_plan(
                    roster, plan.changes, target, context_dates=result.remaining_dates, conditional=True
                )


def history(store, roster, actor):
    plans = list(roster.plans.values())
    if plans:
        for plan in reversed(plans):
            plan_id = plan["plan_id"]
            status = plan_status(roster, plan)
            with st.expander(f"{plan['target']} · {status} · {plan_id}"):
                st.dataframe(plan["changes"], hide_index=True)
                responses = plan["responses"]
                participants = sorted({change["member_id"] for change in plan["changes"]})
                for member_id in participants:
                    response = responses.get(member_id)
                    state = "Pending" if response is None else ("Accepted" if response else "Rejected")
                    employee = roster.members.get(member_id)
                    st.write(f"{employee.name if employee else member_id} · {state}")
                    if status in {"PROPOSED", "AWAITING_CONFIRMATION", "READY_TO_COMMIT"}:
                        accept, reject = st.columns(2)
                        if accept.button("Accept", key=f"{plan_id}_{member_id}_accept", disabled=response is True):
                            record_response(store, roster.revision, plan_id, member_id, True, actor)
                            st.rerun()
                        if reject.button("Reject", key=f"{plan_id}_{member_id}_reject"):
                            record_response(store, roster.revision, plan_id, member_id, False, actor)
                            st.rerun()
                if status == "READY_TO_COMMIT" and st.button(
                    "Commit complete plan", type="primary", key=f"commit_{plan_id}"
                ):
                    commit_plan(store, roster.revision, plan_id, actor)
                    st.session_state["notice"] = "Plan committed. The effective roster has been updated."
                    st.rerun()
                if status == "REJECTED":
                    st.info("Run a new search in Arrangement Advisor. The refusal will be used in the next search.")
                elif status == "STALE":
                    st.info("The roster changed after this plan was proposed. Search again using the current roster.")
        st.download_button(
            "Download plans CSV",
            records_csv([
                {key: value for key, value in plan.items() if key not in {"changes", "responses"}}
                for plan in plans
            ]),
            "plans.csv", "text/csv",
        )
        st.download_button(
            "Download changes CSV",
            records_csv([
                {
                    "plan_id": plan["plan_id"], "plan_status": plan["status"],
                    **change, "accepted": plan["responses"].get(change["member_id"]),
                }
                for plan in plans for change in plan["changes"]
            ]),
            "changes.csv", "text/csv",
        )
    else:
        st.info("No plans have been sent to confirmation.")
    if roster.audit:
        st.markdown("**Audit history**")
        st.dataframe(list(reversed(roster.audit)), hide_index=True)
    st.download_button(
        "Download effective roster CSV", export_roster(roster), "effective_roster.csv", "text/csv"
    )


def main():
    st.set_page_config(page_title="Shift Roster Planner", layout="wide")
    store = Store(Path(os.environ.get("ROSTER_DATA_DIR", STORE_PATH)))
    page = st.sidebar.radio("Page", PAGES)
    actor = st.sidebar.selectbox("Acting manager", ("Manager 1", "Manager 2"))
    st.title(page)
    notice = st.session_state.pop("notice", None)
    if notice:
        st.success(notice)
    try:
        roster = store.load()
        if roster is not None:
            st.sidebar.caption(f"Roster revision {roster.revision}")
        if page == "Master Roster":
            master_roster(store, roster, actor)
        elif roster is None:
            st.info("Import a schedule or load the example from Master Roster to get started.")
        elif page == "Leave Management":
            leave_management(store, roster, actor)
        elif page == "Manpower Coverage":
            coverage_dashboard(roster)
        elif page == "Arrangement Advisor":
            arrangement_advisor(store, roster, actor)
        else:
            history(store, roster, actor)
    except (ValueError, RuntimeError, OSError) as exc:
        st.error(str(exc))


if __name__ == "__main__":
    main()
