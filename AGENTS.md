# Project instructions

Use PRD v1.1 as the requirements baseline and use fictional records for development. Leave unresolved policy questions configurable or use the documented conservative defaults. A full-shift Senior on every affected D/N shift is required. Never relax a hard rule to increase search results.

Keep time and coverage rules in `rules.py`, persistence in `roster.py`, candidate search in `solver.py`, and Manager operations in `service.py`. Streamlit calls those interfaces. Keep CSV reads and writes in the data layer.

For regressions, record reproduction and expected behavior in BUG_TRACKER.md, add a test, then run the complete suite using `python -m pytest -q`.
