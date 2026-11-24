from datetime import date, timedelta

import pytest

from roster import Member, Roster


@pytest.fixture
def target():
    return date(2026, 6, 15)


@pytest.fixture
def make_roster():
    def build(target, assignments, *, senior=("A", "D"), extra=None, complete=True):
        extras = extra or {}
        identifiers = set(assignments) | {member for member, day in extras}
        members = {
            member: Member(member, member, "North" if member < "D" else "South",
                           "SENIOR" if member in senior else "JUNIOR")
            for member in sorted(identifiers)
        }
        shifts = {}
        if complete:
            day = date(2026, 5, 31)
            while day <= date(2026, 7, 1):
                shifts.update({(member, day): "O" for member in members})
                day += timedelta(days=1)
        shifts.update({(member, target): code for member, code in assignments.items()})
        shifts.update(extras)
        return Roster(members, shifts)

    return build


@pytest.fixture
def healthy(make_roster, target):
    return make_roster(target, dict(A="D", B="D", C="D", D="N", E="N", F="N", G="S"))
