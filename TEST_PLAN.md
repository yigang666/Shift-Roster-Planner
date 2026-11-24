# MVP test plan

Run `python -m pytest -q` from the project root with the requirements installed. Test data uses synthetic employees and temporary snapshot directories.

| PRD scenarios | Automated evidence |
|---|---|
| TC01–03 | Normal coverage and no-change search, idempotent reimport of mapped leave, both evening recovery routes with degraded status |
| TC04–09 | Night adjacency, isolated early-start exception, continuous hours, reachable values at and above the monthly cap, cross-month allocation |
| TC10–12 | Reciprocal swap coverage, future gap protection, ranked and deduplicated multi-person repairs |
| TC13–17 | Conditional versus unknown leave recovery, rejection and recalculation, concurrent Manager commits, simulated manifest write failure |
| TC18–22 | Explicit exhausted time budget, incomplete month blocking, emergency status, Reset Standby, early-night adjacency |
| TC23–28 | Senior shortfalls on both shifts, valid Senior coverage, partial Standby coverage, extension, conversion, and early-night coverage |
| TC29–35 | Unique Senior swap regression, no stitching of partial coverage, leave-driven Senior shortage, import validation, cross-date combination, conditional Senior request, four-team sample |

TC06 uses a representable ordinary continuous shift sequence exceeding 12 hours. TC07 uses 266 hours, the next reachable value above 264 with the confirmed whole-even-hour shifts. TC10 exercises an undercovered target with a complete swap, then checks that applying only one side of an otherwise valid swap cannot reduce night headcount below minimum. A complete same-date reciprocal exchange preserves aggregate headcount, though it can change Senior coverage and work-hour compliance.

Integration tests include both CSV layouts, historic snapshot visibility after an interrupted commit, unanimous consent, irreversible stale status after a roster edit, and preventing leave cancellation from restoring a shift that violates working-hour constraints. A small exhaustive action oracle checks solver completeness in a one-assignment window. The Streamlit smoke tests traverse the Manager workflow and load the 19-employee example.

Manager acceptance with an approved anonymized Schedule and confirmation of the outstanding business rules remain separate release checks.
