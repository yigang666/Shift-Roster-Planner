# MVP test report

The local automated suite passed all 50 collected tests. The command was `python -m pytest -q` from the repository root with Python 3.12 and the project requirements installed.

- Rule-engine tests exercise emergency coverage, full-shift Senior coverage, leave, and cross-day and cross-month hours.
- Solver tests exercise ranked repairs, deduplication, cross-date combinations, refusal handling, conditional requests, unverified inputs, timeout reporting, and equivalent Standby extension settings. A reduced search matches exhaustive enumeration.
- Storage and workflow tests exercise import/export, two concurrent Manager commits, and failure just before publication of a snapshot. The manifest remained on the old revision after the injected failure, and both swap changes appeared together on successful retry.
- Streamlit AppTest exercises the synthetic employee example and a Manager workflow through leave entry, shortage detection, arrangement search, consent, commit, and the export control.

All 35 PRD scenario IDs are mapped in [TEST_PLAN.md](TEST_PLAN.md), including three fixtures adapted to the behavior reachable under the defined shifts. Manager UAT, approved real-world data replay, and confirmation of open policy questions are pending.

The simulated CSV regression suite adds four raw-data scenarios covering normal staffing, combined daytime headcount and Senior gaps, a nighttime gap imported from a wide schedule, and incomplete month-end work-hour data. The two repairable cases run through consent, commit, export, and reimport.
