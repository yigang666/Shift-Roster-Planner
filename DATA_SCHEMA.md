# Data schema

Provide two UTF-8 CSV files. Use `examples/members.csv` and `examples/schedule.csv` to try the application with 19 fictional employees. The example covers November 29, 2026 through January 2, 2027 so changes to December shifts can be checked against December work hours and adjacent days. `python examples/generate.py` regenerates both CSV files.

## Member master

One row per `member_id`. Supply `member_id,name,team,experience_level` and optionally `active` (defaults to true). The two experience levels are `SENIOR` and `JUNIOR`. Team and experience are independent.

## Schedule import and export

Secondary date information in ISO `YYYY-MM-DD` refers to the date the roster assignment starts. Supply one of these formats.

- Long CSV with `date,member_id,shift`, or `date,member_id,source_shift,planned_shift,leave_status` for schedules that retain the planned shift during leave. A recorded leave with an unknown original assignment uses an empty `planned_shift`. The default leave marker is `L`. Additional source markers can be supplied at import.
- Wide CSV with one `member_id` column followed by date columns. A blank assignment is missing data. The explicit `O` and `R` codes represent off and reset days.

Working assignments are `D`, `N`, `S`, `S_OT`, and `N_EARLY`. Repeated member/date entries, unknown members or codes, and malformed inputs raise an import error before saving. Reimporting the current schedule with the same normalized assignments and member data leaves its current revision and subsequent edits intact.

A snapshot maintains three layers per `(member_id, date)`. The original import stores the source code and planned assignment. Committed arrangements supply assignment overrides. Active leave then marks the effective assignment as `L`. Cancelling a leave requires a known or explicitly confirmed original assignment. Effective exports represent the data as viewed after applying these layers.

## Shared snapshots

Each revision stores `members.csv`, `master_roster.csv`, the original upload, current and original leave records, arrangement overlays, plan and refusal records, and an audit log. Plans and audit details with nested structure are serialized into CSV record fields. `CURRENT` points to the active revision. All manager changes go through the store under an exclusive file lock. The store checks the expected revision, writes and flushes a complete snapshot, then switches the pointer atomically. Earlier snapshots and original uploads remain in the data directory for history and recovery. Use one shared local data directory for the manager sessions.
