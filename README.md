# Shift Roster Planner

Internal Streamlit tool for two Shift Managers to import rosters, assess staffing, and record agreed arrangements. Use Python 3.12 on Linux or macOS.

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

Load the fictional roster from **Master Roster**, or upload a members CSV and a schedule CSV in one of the formats in [DATA_SCHEMA.md](DATA_SCHEMA.md). For a sample shortage, add Leave for C03 on 3 December 2026. In **Arrangement Advisor**, choose that date and search. Save a plan, record each employee's consent in **Confirmation & History**, submit the complete plan, and export the effective roster. The sample includes pre-existing Leave.

Use one shared app instance and data directory for both Managers. Set `ROSTER_DATA_DIR` to choose a private directory. Keep its snapshot directories along with the `CURRENT` manifest when backing it up. If a plan becomes stale, refresh and search again. The app requires complete relevant months and neighboring records before allowing work changes.

Run automated tests with:

```sh
python -m pytest -q
```

[BUSINESS_RULES.md](BUSINESS_RULES.md) describes the coverage and work-hour checks. Keep real employee records outside this repository. Confirm the open company policies and complete Manager acceptance before production use.
