"""Exercise the Streamlit manager workflow against a temporary, shared store."""

from datetime import date, timedelta
from pathlib import Path

from streamlit.testing.v1 import AppTest

from roster import Member, Roster, Store


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"


def open_page(app, name):
    app.sidebar.radio[0].set_value(name).run()
    assert not app.exception
    assert not app.error


def click(app, label):
    next(button for button in app.button if button.label == label).click().run(timeout=30)
    assert not app.exception
    assert not app.error


def test_manager_workflow(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSTER_DATA_DIR", str(tmp_path))
    manager_store = Store(tmp_path)
    target = date(2026, 12, 8)
    members = {
        f"E{index}": Member(f"E{index}", f"Employee {index}", "A", "SENIOR" if index in (0, 3, 7) else "JUNIOR")
        for index in range(8)
    }
    shifts = {
        (member_id, date(2026, 11, 30) + timedelta(days=offset)): "O"
        for member_id in members for offset in range(33)
    }
    shifts.update({(member_id, target): code for member_id, code in zip(members, "DDDNNNSO")})
    manager_store.update(0, lambda _: Roster(members, shifts), actor="Manager 1", event="IMPORT")

    app = AppTest.from_file(str(APP_PATH)).run(timeout=15)
    assert not app.exception
    assert not app.error
    open_page(app, "Leave Management")
    app.date_input[0].set_value(target).run()
    app.date_input[1].set_value(target).run()
    click(app, "Simulate leave")
    assert not manager_store.load().leaves
    click(app, "Add leave")
    assert manager_store.load().effective()["E0", target] == "L"

    open_page(app, "Manpower Coverage")
    coverage_date = next(widget for widget in app.selectbox if widget.label == "Inspect date")
    assert f"{target.isoformat()} · CRITICAL" in coverage_date.options

    open_page(app, "Arrangement Advisor")
    next(widget for widget in app.selectbox if widget.label == "Target date").set_value(target)
    for widget in app.number_input:
        if widget.label in {"Days before target", "Days after target"}:
            widget.set_value(0)
        if widget.label == "Maximum plans to display":
            widget.set_value(1)
    click(app, "Find arrangements")
    click(app, "Send to confirmation")

    open_page(app, "Confirmation & History")
    assert all(button.label != "Commit complete plan" for button in app.button)
    while any(button.label == "Accept" and not button.disabled for button in app.button):
        next(
            button for button in app.button if button.label == "Accept" and not button.disabled
        ).click().run()
        assert not app.exception
        assert not app.error
    click(app, "Commit complete plan")
    assert manager_store.load().effective()["E7", target] == "D"
    assert any(plan["status"] == "COMMITTED" for plan in manager_store.load().plans.values())
    assert any(button.proto.label == "Download effective roster CSV"
               for button in app.get("download_button"))


def test_load_sample_roster(tmp_path, monkeypatch):
    monkeypatch.setenv("ROSTER_DATA_DIR", str(tmp_path))
    app = AppTest.from_file(str(APP_PATH)).run(timeout=15)
    click(app, "Load 19-employee example")
    roster = Store(tmp_path).load()
    assert len(roster.members) == 19
    assert set(member.team for member in roster.members.values()) == {"A", "B", "C", "D"}
    assert roster.leaves
    assert len(app.dataframe[0].value) == 19
    assert any(button.proto.label == "Download roster CSV" for button in app.get("download_button"))
