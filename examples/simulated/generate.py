"""Create reproducible fictional source schedules from the shared example."""

import csv
from pathlib import Path

OUTPUT = Path(__file__).resolve().parent
TARGET = "2026-12-03"
MONTH_END = "2026-12-31"

SCENARIOS = {
    "normal_long.csv": set(),
    "day_senior_gap_long.csv": {(TARGET, member) for member in ("C01", "C02", "C03")},
    "night_gap_wide.csv": {(TARGET, member) for member in ("B01", "B02", "B03")},
    "month_end_incomplete_long.csv": {(MONTH_END, member) for member in ("B01", "B02", "B03")},
}


def generate():
    with (OUTPUT.parent / "schedule.csv").open(encoding="utf-8", newline="") as handle:
        baseline = list(csv.DictReader(handle))
    for filename, absences in SCENARIOS.items():
        with (OUTPUT / filename).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, lineterminator="\n")
            if filename.endswith("_wide.csv"):
                dates = sorted({row["date"] for row in baseline})
                schedules = {}
                for row in baseline:
                    day, member = row["date"], row["member_id"]
                    schedules.setdefault(member, {})[day] = (
                        "AL" if (day, member) in absences else row["planned_shift"]
                    )
                writer.writerow(["member_id", *dates])
                for member, schedule in sorted(schedules.items()):
                    writer.writerow([member, *(schedule[day] for day in dates)])
            else:
                writer.writerow(["date", "member_id", "source_shift", "planned_shift", "leave_status"])
                for row in baseline:
                    day, member, shift = row["date"], row["member_id"], row["planned_shift"]
                    absent = (day, member) in absences
                    writer.writerow([day, member, "L" if absent else shift, shift,
                                     "approved" if absent else "none"])


if __name__ == "__main__":
    generate()
