"""Roster domain, CSV conversion, and atomic snapshot storage."""

from __future__ import annotations

import csv
import fcntl
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

ShiftKey = tuple[str, date]
SHIFTS = frozenset({"D", "N", "O", "R", "S", "S_OT", "N_EARLY"})
EXPERIENCE_LEVELS = frozenset({"SENIOR", "JUNIOR"})


class DataError(ValueError):
    """Invalid roster input or operation."""


class StaleRevisionError(DataError):
    """The shared roster changed since the manager last read it."""


@dataclass(frozen=True)
class Member:
    member_id: str
    name: str
    team: str
    experience_level: str
    active: bool = True


@dataclass
class Roster:
    members: dict[str, Member]
    shifts: dict[ShiftKey, str]
    leaves: dict[ShiftKey, str | None] = field(default_factory=dict)
    overrides: dict[ShiftKey, str] = field(default_factory=dict)
    revision: int = 0
    audit: list[dict] = field(default_factory=list)
    plans: dict[str, dict] = field(default_factory=dict)
    unavailability: list[dict] = field(default_factory=list)
    source_shifts: dict[ShiftKey, str] = field(default_factory=dict)
    import_id: str = ""
    import_csv: str = ""
    original_leaves: dict[ShiftKey, str | None] = field(default_factory=dict)

    def effective(self) -> dict[ShiftKey, str]:
        return self.shifts | self.overrides | dict.fromkeys(self.leaves, "L")

    def _leave_keys(self, member_id: str, start: date, end: date) -> list[ShiftKey]:
        member = self.members.get(member_id)
        if member is None or not member.active:
            raise DataError(f"Unknown or inactive member {member_id!r}")
        if type(start) is not date or type(end) is not date or end < start:
            raise DataError("Leave requires an inclusive range of full calendar dates")
        requested_days = (end - start).days + 1
        if requested_days > len(self.shifts):
            raise DataError("Leave extends beyond the imported schedule")
        keys = [(member_id, start + timedelta(days=offset)) for offset in range(requested_days)]
        missing = next((day for key_member, day in keys if (key_member, day) not in self.shifts), None)
        if missing is not None:
            raise DataError(f"No imported assignment for {member_id} on {missing}")
        return keys

    def with_leave(self, member_id: str, start: date, end: date) -> Roster:
        keys = self._leave_keys(member_id, start, end)
        effective = self.effective()
        leaves = self.leaves.copy()
        for key in keys:
            if key not in leaves:
                leaves[key] = effective[key] if effective[key] in SHIFTS else None
        return replace(self, leaves=leaves)

    def with_cancelled_leave(
        self, member_id: str, start: date, end: date, restored_shift: str | None = None
    ) -> Roster:
        keys = self._leave_keys(member_id, start, end)
        if restored_shift is not None and restored_shift not in SHIFTS:
            raise DataError(f"Unknown restored shift {restored_shift!r}")
        leaves = self.leaves.copy()
        overrides = self.overrides.copy()
        for key in keys:
            if key not in leaves:
                raise DataError(f"No active leave for {member_id} on {key[1]}")
            known_shift = leaves.pop(key)
            if known_shift is not None and restored_shift not in (None, known_shift):
                raise DataError(f"The confirmed original shift on {key[1]} is {known_shift}")
            recovery = known_shift or restored_shift
            if recovery is None:
                raise DataError(f"Confirm the original shift for {member_id} on {key[1]} first")
            if (overrides.get(key) or self.shifts[key]) != recovery:
                overrides[key] = recovery
        return replace(self, leaves=leaves, overrides=overrides)


def _parse_date(value: str) -> date:
    try:
        result = date.fromisoformat(value)
    except ValueError as exc:
        raise DataError(f"Invalid ISO date {value!r}") from exc
    if result.isoformat() != value:
        raise DataError(f"Use YYYY-MM-DD for date {value!r}")
    return result


def _csv_reader(content: str) -> csv.DictReader:
    reader = csv.DictReader(io.StringIO(content.removeprefix("\ufeff"), newline=""), strict=True)
    try:
        headers = reader.fieldnames
    except csv.Error as exc:
        raise DataError(f"Invalid CSV header: {exc}") from exc
    if not headers:
        raise DataError("CSV requires a header")
    reader.fieldnames = [header.strip() for header in headers]
    if "" in reader.fieldnames or len(reader.fieldnames) != len(set(reader.fieldnames)):
        raise DataError("CSV contains blank or duplicate column headers")
    return reader


def _rows(reader: csv.DictReader):
    try:
        for row in reader:
            if None in row or any(value is None for value in row.values()):
                raise DataError(f"Line {reader.line_num} does not match the header column count")
            yield {key: value.strip() for key, value in row.items()}
    except csv.Error as exc:
        raise DataError(f"Invalid CSV near line {reader.line_num}: {exc}") from exc


def read_members(csv_text: str) -> dict[str, Member]:
    reader = _csv_reader(csv_text)
    required = {"member_id", "name", "team", "experience_level"}
    if not required.issubset(reader.fieldnames):
        raise DataError(f"Member CSV requires columns {', '.join(sorted(required))}")
    members = {}
    for row in _rows(reader):
        member_id, name, team = (row[column] for column in ("member_id", "name", "team"))
        level = row["experience_level"].upper()
        active = row.get("active", "true").lower()
        if not member_id or not name or not team:
            raise DataError(f"Line {reader.line_num}: member_id, name and team must have values")
        if member_id in members:
            raise DataError(f"Line {reader.line_num}: duplicate member {member_id!r}")
        if level not in EXPERIENCE_LEVELS:
            raise DataError(f"Line {reader.line_num}: {member_id} requires SENIOR or JUNIOR experience_level")
        if active not in {"true", "false", "1", "0", ""}:
            raise DataError(f"Line {reader.line_num}: invalid active value {active!r}")
        members[member_id] = Member(member_id, name, team, level, active not in {"false", "0"})
    if not members:
        raise DataError("Member CSV has no members")
    return members


def import_roster(
    csv_text: str, members: Mapping[str, Member], leave_codes: Iterable[str] = ("L",)
) -> Roster:
    reader = _csv_reader(csv_text)
    columns = set(reader.fieldnames)
    if "member_id" not in columns:
        raise DataError("Schedule CSV requires member_id")
    if any(member.experience_level not in EXPERIENCE_LEVELS for member in members.values()):
        raise DataError("Every member requires SENIOR or JUNIOR experience_level")
    if any(key != member.member_id for key, member in members.items()):
        raise DataError("Each member master key must match its member_id")
    if isinstance(leave_codes, str):
        leave_codes = (leave_codes,)
    aliases = {code.strip().upper() for code in leave_codes} | {"L"}
    if "" in aliases or aliases & SHIFTS:
        raise DataError("Leave codes must be nonempty and distinct from shift codes")

    long_format = "date" in columns
    if long_format and not columns & {"source_shift", "shift", "planned_shift"}:
        raise DataError("Long schedule requires a source_shift, shift or planned_shift column")
    wide_columns = columns - {"member_id", "name", "team", "experience_level", "active"}
    dates = {} if long_format else {column: _parse_date(column) for column in sorted(wide_columns)}
    if not long_format and not dates:
        raise DataError("Wide schedule requires at least one YYYY-MM-DD column")

    shifts = {}
    source_shifts = {}
    leaves = {}
    wide_members = set()

    def add(member_id: str, day: date, raw: str, planned: str, status: str) -> None:
        key = member_id, day
        if key in shifts:
            raise DataError(f"Duplicate assignment for {member_id} on {day}")
        code = raw.upper()
        planned = planned.upper()
        if status not in {"", "none", "approved", "cancelled"}:
            raise DataError(f"Unknown leave status {status!r}")
        if planned and planned not in SHIFTS and planned not in aliases:
            raise DataError(f"Invalid planned shift {planned!r} for {member_id} on {day}")
        if code not in SHIFTS | aliases:
            raise DataError(f"Invalid shift {raw!r} for {member_id} on {day}")
        recovery = planned if planned in SHIFTS else code if code in SHIFTS else None
        is_leave = status == "approved" or (code in aliases and status != "cancelled")
        if recovery is None and not is_leave:
            raise DataError(f"Cancelled leave requires a known original shift for {member_id} on {day}")
        shifts[key] = recovery or "L"
        source_shifts[key] = raw
        if is_leave:
            leaves[key] = recovery

    for row in _rows(reader):
        member_id = row["member_id"]
        try:
            if member_id not in members:
                raise DataError(f"Unknown member {member_id!r}")
            if long_format:
                raw = row.get("source_shift") or row.get("shift") or row.get("planned_shift") or ""
                planned = row.get("planned_shift", "")
                status = row.get("leave_status", "").lower()
                if not raw and status == "approved":
                    raw = "L"
                add(member_id, _parse_date(row["date"]), raw, planned, status)
            else:
                if member_id in wide_members:
                    raise DataError(f"Duplicate row for member {member_id!r}")
                wide_members.add(member_id)
                for column, day in dates.items():
                    if row[column]:
                        add(member_id, day, row[column], "", "")
        except DataError as exc:
            raise DataError(f"Line {reader.line_num}: {exc}") from exc

    if not shifts:
        raise DataError("Schedule CSV has no assignments")
    semantic_import = [
        sorted((member.member_id, member.name, member.team, member.experience_level, member.active)
               for member in members.values()),
        sorted((member_id, day.isoformat(), source_shifts[(member_id, day)].upper(), shift,
                (member_id, day) in leaves)
               for (member_id, day), shift in shifts.items()),
    ]
    digest = hashlib.sha256(
        json.dumps(semantic_import, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return Roster(
        dict(members), shifts, leaves, source_shifts=source_shifts, import_id=digest,
        import_csv=csv_text, original_leaves=leaves.copy()
    )


def _csv_text(header: Iterable[str], rows: Iterable[Iterable[object]]) -> str:
    destination = io.StringIO(newline="")
    writer = csv.writer(destination, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return destination.getvalue()


def export_members(roster: Roster) -> str:
    return _csv_text(
        ("member_id", "name", "team", "experience_level", "active"),
        ((member.member_id, member.name, member.team, member.experience_level,
          str(member.active).lower()) for member in sorted(roster.members.values(), key=lambda m: m.member_id))
    )


def export_roster(roster: Roster, effective: bool = True, wide: bool = False) -> str:
    assignments = roster.effective() if effective else roster.shifts | roster.source_shifts
    if wide:
        days = sorted({day for _, day in assignments})
        return _csv_text(
            ("member_id", *(day.isoformat() for day in days)),
            ((member_id, *(assignments.get((member_id, day), "") for day in days))
             for member_id in sorted(roster.members))
        )
    keys = sorted(assignments, key=lambda key: (key[1], key[0]))
    if effective:
        return _csv_text(
            ("date", "member_id", "shift"),
            ((day.isoformat(), member_id, assignments[(member_id, day)]) for member_id, day in keys)
        )
    return _csv_text(
        ("date", "member_id", "source_shift", "planned_shift", "leave_status", "import_id"),
        ((day.isoformat(), member_id, assignments[(member_id, day)],
          roster.original_leaves.get((member_id, day), roster.shifts[(member_id, day)]),
          "approved" if (member_id, day) in roster.original_leaves else "none", roster.import_id)
         for member_id, day in keys)
    )


def _write_csv(path: Path, header: Iterable[str], rows: Iterable[Iterable[object]]) -> None:
    path.write_text(_csv_text(header, rows), encoding="utf-8", newline="")


def _snapshot_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, strict=True))


def _shift_map(path: Path, column: str) -> dict[ShiftKey, str | None]:
    return {
        (row["member_id"], _parse_date(row["date"])): row[column] or None
        for row in _snapshot_rows(path)
    }


def _sync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Store:
    """One durable snapshot per transaction. Readers follow the current manifest."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> Roster | None:
        try:
            pointer = (self.path / "CURRENT").read_text(encoding="ascii").strip()
        except FileNotFoundError:
            return None
        if not re.fullmatch(r"revision-[1-9][0-9]*-[0-9a-f]{32}", pointer):
            raise DataError("Invalid roster snapshot pointer")
        snapshot = self.path / pointer
        metadata, = _snapshot_rows(snapshot / "revision.csv")
        roster_rows = _snapshot_rows(snapshot / "master_roster.csv")
        return Roster(
            members=read_members((snapshot / "members.csv").read_text(encoding="utf-8")),
            shifts={(row["member_id"], _parse_date(row["date"])): row["planned_shift"] for row in roster_rows},
            leaves=_shift_map(snapshot / "leaves.csv", "original_shift"),
            overrides=_shift_map(snapshot / "arrangements.csv", "new_shift"),
            revision=int(metadata["revision"]),
            audit=[json.loads(row["record"]) for row in _snapshot_rows(snapshot / "audit_log.csv")],
            plans={row["plan_id"]: json.loads(row["record"])
                   for row in _snapshot_rows(snapshot / "plans.csv")},
            unavailability=[json.loads(row["record"]) for row in _snapshot_rows(snapshot / "unavailability.csv")],
            source_shifts={
                (row["member_id"], _parse_date(row["date"])): row["source_shift"] for row in roster_rows
                if row["source_shift"]
            },
            import_id=metadata["import_id"],
            import_csv=(snapshot / "original_schedule.csv").read_bytes().decode("utf-8"),
            original_leaves=_shift_map(snapshot / "original_leaves.csv", "original_shift"),
        )

    def update(
        self,
        expected_revision: int,
        transform: Callable[[Roster | None], Roster],
        *,
        actor: str,
        event: str,
        details: str = "",
    ) -> Roster:
        """Run a transform that returns a fresh roster or the unchanged current roster."""
        if not actor.strip() or not event.strip():
            raise DataError("Saving requires an actor and an audit event")
        self.path.mkdir(mode=0o700, parents=True, exist_ok=True)
        with (self.path / "write.lock").open("a", encoding="ascii") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            current = self.load()
            revision = current.revision if current else 0
            if revision != expected_revision:
                raise StaleRevisionError(
                    f"Roster changed from revision {expected_revision} to {revision}. Refresh and retry."
                )
            proposed = transform(current)
            if not isinstance(proposed, Roster):
                raise DataError("Roster update must return a Roster")
            if proposed is current:
                return current
            if current and (
                current.effective() != proposed.effective()
                or current.members != proposed.members
                or current.import_id != proposed.import_id
            ):
                plans = {
                    plan_id: {**plan, "status": "STALE"}
                    if plan.get("status") in {"PROPOSED", "AWAITING_CONFIRMATION", "READY_TO_COMMIT"}
                    else plan
                    for plan_id, plan in proposed.plans.items()
                }
                proposed = replace(proposed, plans=plans)
            audit_record = {
                "event_id": uuid4().hex,
                "actor": actor.strip(),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event_type": event,
                "revision": revision + 1,
                "details": details,
            }
            saved = replace(
                proposed, revision=revision + 1,
                audit=[*(current.audit if current else []), audit_record]
            )
            self._publish(saved)
            return saved

    def import_schedule(
        self, expected_revision: int, csv_text: str, members: Mapping[str, Member], *,
        actor: str, leave_codes: Iterable[str] = ("L",)
    ) -> Roster:
        imported = import_roster(csv_text, members, leave_codes)

        def apply(current: Roster | None) -> Roster:
            if current is None:
                return imported
            if current.import_id == imported.import_id:
                return current
            return replace(imported, plans=current.plans.copy())

        return self.update(
            expected_revision, apply, actor=actor, event="schedule_import", details=imported.import_id
        )

    def _publish(self, roster: Roster) -> None:
        staging = Path(tempfile.mkdtemp(prefix=".staging-", dir=self.path))
        snapshot = self.path / f"revision-{roster.revision}-{uuid4().hex}"
        manifest = self.path / f".current-{uuid4().hex}"
        try:
            self._write_snapshot(staging, roster)
            for file in staging.iterdir():
                with file.open("rb") as handle:
                    os.fsync(handle.fileno())
            _sync_directory(staging)
            staging.replace(snapshot)
            _sync_directory(self.path)
            with manifest.open("x", encoding="ascii") as handle:
                handle.write(snapshot.name + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            manifest.replace(self.path / "CURRENT")
            _sync_directory(self.path)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
            manifest.unlink(missing_ok=True)

    def _write_snapshot(self, path: Path, roster: Roster) -> None:
        (path / "members.csv").write_text(export_members(roster), encoding="utf-8")
        _write_csv(
            path / "master_roster.csv",
            ("member_id", "date", "source_shift", "planned_shift"),
            ((member_id, day.isoformat(), roster.source_shifts.get((member_id, day), ""), shift)
             for (member_id, day), shift in sorted(roster.shifts.items()))
        )
        for filename, column, assignments in (
            ("leaves", "original_shift", roster.leaves),
            ("original_leaves", "original_shift", roster.original_leaves),
            ("arrangements", "new_shift", roster.overrides),
        ):
            _write_csv(
                path / f"{filename}.csv", ("member_id", "date", column),
                ((member_id, day.isoformat(), shift)
                 for (member_id, day), shift in sorted(assignments.items()))
            )
        _write_csv(path / "revision.csv", ("revision", "import_id"), [(roster.revision, roster.import_id)])
        _write_csv(
            path / "plans.csv", ("plan_id", "record"),
            ((plan_id, json.dumps(plan, ensure_ascii=False)) for plan_id, plan in roster.plans.items())
        )
        for filename, records in (
            ("unavailability", roster.unavailability), ("audit_log", roster.audit)
        ):
            _write_csv(
                path / f"{filename}.csv", ("record",),
                ((json.dumps(record, ensure_ascii=False),) for record in records)
            )
        (path / "original_schedule.csv").write_bytes(roster.import_csv.encode("utf-8"))


def sample_roster() -> Roster:
    examples = Path(__file__).resolve().parent / "examples"
    members = read_members((examples / "members.csv").read_text(encoding="utf-8"))
    return import_roster((examples / "schedule.csv").read_text(encoding="utf-8"), members)
