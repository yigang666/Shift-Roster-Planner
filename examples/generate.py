"""Regenerate the deterministic, fictional example CSV files."""

import csv
from datetime import date, timedelta
from pathlib import Path

EXAMPLES = Path(__file__).resolve().parent
TEAM_SIZES = [("A", 5, 4), ("B", 5, 4), ("C", 5, 3), ("D", 4, 3)]
START = date(2026, 11, 29)
FINISH = date(2027, 1, 2)
EXISTING_LEAVE = {("C01", date(2026, 12, 3)), ("C02", date(2026, 12, 3))}


def generate() -> None:
    with (EXAMPLES / "members.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["member_id", "name", "team", "experience_level", "active"])
        for team, members, seniors in TEAM_SIZES:
            for index in range(1, members + 1):
                member_id = f"{team}{index:02}"
                level = "SENIOR" if index <= seniors else "JUNIOR"
                writer.writerow([member_id, f"Example {member_id}", team, level, "true"])

    with (EXAMPLES / "schedule.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["date", "member_id", "source_shift", "planned_shift", "leave_status"])
        for offset in range((FINISH - START).days + 1):
            day = START + timedelta(days=offset)
            shift_day = offset + 2
            for team_index, (team, members, _) in enumerate(TEAM_SIZES):
                phase = (shift_day - team_index) % 4
                shift = "DNOR"[phase]
                standby_round = ((shift_day - team_index) // 4) % 3
                for index in range(1, members + 1):
                    member_id = f"{team}{index:02}"
                    assignment = "S" if shift == "R" and (index - 1) % 3 == standby_round else shift
                    on_leave = (member_id, day) in EXISTING_LEAVE
                    writer.writerow([day.isoformat(), member_id, "L" if on_leave else assignment,
                                     assignment, "approved" if on_leave else "none"])


if __name__ == "__main__":
    generate()
