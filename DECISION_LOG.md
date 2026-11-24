# Decisions

- Python's standard CSV module handles business records. Streamlit uses tables only for presentation.
- CP-SAT models changes and minimum coverage. The independent rule engine validates actual intervals, including month and roster boundaries.
- Equivalent S→D and S→S_OT results are represented by S→D when enabled and accepted. S→S_OT remains available when conversion is disabled. A refusal covers both equivalent requests.
- Full-day Leave uses the roster start date, and hours are split by local calendar day and month. Off Standby and direct reassignment start disabled pending Manager confirmation. See OPEN_QUESTIONS.md.
- A display limit signals partial search. A plan that is a superset of a previously found feasible plan at the same coverage grade is omitted to avoid unrelated changes.
- Critical leave fallback evaluates single confirmed restorations and lists them as requests. The restored shift must be known and independently verifiable. Any further changes require a fresh search after the Manager records the cancellation.
