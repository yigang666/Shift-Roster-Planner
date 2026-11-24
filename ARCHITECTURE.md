# Architecture

Streamlit renders a shared Manager workflow. `roster.py` imports member and schedule CSVs and retains the original import, Leave and arrangement overrides. The store uses a revision check under a process lock and publishes a complete CSV snapshot through an atomic manifest switch.

`rules.py` calculates Singapore work intervals, independent coverage and work-hour validation. `solver.py` uses CP-SAT to model allowable assignment changes, linked pairs and mandatory coverage. It validates each candidate independently and returns plans ordered by the documented impact criteria. Search stops at its time or display bound and reports its status.

`service.py` checks consent and availability, validates the latest roster, then publishes all assignments in a single transaction. Manager actions append audit records. A change to the effective schedule invalidates outstanding plans based on the earlier schedule.
