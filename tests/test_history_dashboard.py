from contextlib import closing
from datetime import datetime

import pytest
from flask import template_rendered

from app import create_app, tracking
from db import get_connection


@pytest.fixture
def dashboard_app(tmp_path, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls):
            return cls(2026, 11, 20, 12)

    monkeypatch.setattr(tracking, "datetime", Clock)
    app = create_app({
        "TESTING": True, "DATABASE": tmp_path / "test.db",
        "BACKUP_DIR": tmp_path / "backups",
    })
    with closing(get_connection(app.config["DATABASE"])) as conn:
        conn.executemany(
            "INSERT INTO exercises (id, type, focus, name) VALUES (?, ?, ?, ?)",
            [(1, "strength", "Back", "Back lift"), (2, "stretch", "Thighs", "Thigh stretch"),
             (3, "strength", "Chest", "Chest press")],
        )
        conn.commit()
    return app


def add_session(conn, day, items, finished=True):
    cursor = conn.execute(
        "INSERT INTO sessions (date, day_type, started_at, finished_at) VALUES (?, 'full', ?, ?)",
        (day, day + "T09:00:00", day + "T10:00:00" if finished else None),
    )
    session_id = cursor.lastrowid
    item_ids = []
    for position, (exercise_id, status) in enumerate(items, 1):
        cursor = conn.execute(
            """INSERT INTO session_items (session_id, position, block, exercise_id, status)
               VALUES (?, ?, 'strength', ?, ?)""",
            (session_id, position, exercise_id, status),
        )
        item_ids.append(cursor.lastrowid)
    return session_id, item_ids


def add_activity(conn, day, kind="walk", minutes=30, miles=2):
    conn.execute(
        """INSERT INTO activity_logs
               (activity_type, date, duration_minutes, distance_miles, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (kind, day, minutes, miles, day + "T12:00:00"),
    )


def render_history(app, url="/history"):
    contexts = []

    def capture(sender, template, context, **extra):
        contexts.append(context)

    with template_rendered.connected_to(capture, app):
        response = app.test_client().get(url)
    assert response.status_code == 200
    return response, contexts[-1]


def test_weekly_summary_excludes_skips_pending_and_future_and_deduplicates_days(dashboard_app):
    with closing(get_connection(dashboard_app.config["DATABASE"])) as conn:
        add_session(conn, "2026-11-15", [(1, "done")])
        add_session(conn, "2026-11-16", [(1, "done")])
        add_session(conn, "2026-11-17", [(1, "done")], finished=False)
        add_session(conn, "2026-11-18", [(1, "skipped")])
        add_session(conn, "2026-11-19", [(1, "pending")], finished=False)
        add_activity(conn, "2026-11-20", minutes=20, miles=1)
        add_activity(conn, "2026-11-20", kind="bike", minutes=10, miles=2)
        add_activity(conn, "2026-11-21", minutes=100, miles=10)
        conn.commit()
    response, context = render_history(dashboard_app)
    dashboard = context["dashboard"]
    assert dashboard["week"]["active_days"] == 3
    assert dashboard["week"]["workouts"] == 1
    assert dashboard["week"]["minutes"] == 30
    assert dashboard["week"]["miles"] == 3
    assert dashboard["week_start"] == "2026-11-16"
    assert len(dashboard["weekly_charts"]) == 3
    assert all(len(chart["bars"]) == 8 for chart in dashboard["weekly_charts"])
    assert dashboard["weekly_charts"][0]["bars"][-2]["value"] == 1
    assert dashboard["weekly_charts"][0]["bars"][-1]["value"] == 1
    for heading in (b"This week", b"Activity calendar", b"Weekly trends",
                    b"Body-area coverage", b"Strength progress"):
        assert heading in response.data


def test_week_boundary_crosses_year_correctly(dashboard_app, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls):
            return cls(2027, 1, 1, 12)

    monkeypatch.setattr(tracking, "datetime", Clock)
    with closing(get_connection(dashboard_app.config["DATABASE"])) as conn:
        add_activity(conn, "2026-12-27", minutes=100)
        add_activity(conn, "2026-12-28", minutes=10)
        add_activity(conn, "2027-01-01", minutes=20)
        add_activity(conn, "2027-01-02", minutes=100)
        conn.commit()
    _, context = render_history(dashboard_app)
    dashboard = context["dashboard"]
    assert dashboard["week_start"] == "2026-12-28"
    assert dashboard["week"]["minutes"] == 30
    assert dashboard["week"]["active_days"] == 2
    assert dashboard["previous_month"].isoformat() == "2026-12-01"


def test_calendar_leap_month_and_badges_do_not_hide_multiple_activities(dashboard_app):
    with closing(get_connection(dashboard_app.config["DATABASE"])) as conn:
        add_activity(conn, "2024-02-29")
        add_activity(conn, "2024-02-29")
        add_activity(conn, "2024-02-29", kind="run")
        add_session(conn, "2024-02-29", [(1, "pending")], finished=False)
        conn.commit()
    _, context = render_history(dashboard_app, "/history?month=2024-02")
    days = [day for week in context["dashboard"]["calendar_weeks"] for day in week if day]
    assert [day["number"] for day in days] == list(range(1, 30))
    badges = {badge["label"]: badge["count"] for badge in days[-1]["badges"]}
    assert badges == {"Full (open)": 1, "Walk": 2, "Run": 1}
    assert days[-1]["date"] == "2024-02-29"


def test_body_coverage_includes_exact_30_day_boundary_and_zero_areas(dashboard_app):
    with closing(get_connection(dashboard_app.config["DATABASE"])) as conn:
        add_session(conn, "2026-10-21", [(1, "done")])
        add_session(conn, "2026-10-22", [(1, "done")])
        add_session(conn, "2026-11-20", [(2, "done"), (1, "skipped"), (1, "pending")])
        add_session(conn, "2026-11-21", [(1, "done")])
        conn.commit()
    _, context = render_history(dashboard_app)
    dashboard = context["dashboard"]
    assert dashboard["coverage_start"] == "2026-10-22"
    assert {bar["label"]: bar["value"] for bar in dashboard["body_bars"]} == {
        "Back": 1, "Thighs": 1, "Chest": 0,
    }


def test_strength_uses_max_weight_and_total_reps_without_filling_missing_values(dashboard_app):
    with closing(get_connection(dashboard_app.config["DATABASE"])) as conn:
        _, first = add_session(conn, "2026-11-18", [(1, "done"), (1, "pending"), (2, "done")])
        _, second = add_session(conn, "2026-11-19", [(1, "done")])
        _, third = add_session(conn, "2026-11-20", [(1, "done")])
        conn.executemany(
            "INSERT INTO strength_sets (session_item_id, set_number, reps, weight) VALUES (?, ?, ?, ?)",
            [(first[0], 1, 8, 10), (first[0], 2, 10, 20),
             (first[1], 1, 100, 100), (first[2], 1, 50, 50),
             (second[0], 1, None, 0), (third[0], 1, 5, None)],
        )
        conn.execute("UPDATE exercises SET type = 'stretch', active = 0 WHERE id = 1")
        conn.commit()
    response, context = render_history(dashboard_app, "/history?exercise_id=1")
    charts = context["dashboard"]["strength_charts"]
    assert [bar["value"] for bar in charts[0]["bars"]] == [20, 0, None]
    assert [bar["value"] for bar in charts[1]["bars"]] == [18, None, 5]
    assert charts[0]["bars"][1]["width"] == 0
    assert charts[0]["bars"][2]["width"] is None
    assert b"Not logged" in response.data
    assert b"Back lift (inactive)" in response.data


def test_strength_limits_to_latest_12_workouts_in_chronological_order(dashboard_app):
    with closing(get_connection(dashboard_app.config["DATABASE"])) as conn:
        for number in range(1, 14):
            _, items = add_session(conn, f"2026-11-{number:02d}", [(1, "done")])
            conn.execute(
                "INSERT INTO strength_sets (session_item_id, set_number, reps, weight) VALUES (?, 1, 8, ?)",
                (items[0], number),
            )
        conn.commit()
    _, context = render_history(dashboard_app)
    bars = context["dashboard"]["strength_charts"][0]["bars"]
    assert len(bars) == 12
    assert [bar["value"] for bar in bars] == list(range(2, 14))
    assert [bar["session_id"] for bar in bars] == list(range(2, 14))


def test_calendar_day_filters_details_but_not_overview_metrics(dashboard_app):
    with closing(get_connection(dashboard_app.config["DATABASE"])) as conn:
        add_activity(conn, "2026-11-19", minutes=10)
        add_activity(conn, "2026-11-20", minutes=20)
        conn.commit()
    response, context = render_history(dashboard_app, "/history?month=2026-11&day=2026-11-19")
    assert len(context["entries"]) == 1
    assert context["entries"][0]["date"] == "2026-11-19"
    assert context["dashboard"]["week"]["minutes"] == 30
    assert b"Show all records" in response.data
    assert b"day=2026-11-19" in response.data
    response, context = render_history(dashboard_app, "/history?day=2026-11-18")
    assert not context["entries"]
    assert b"No records on this day." in response.data


@pytest.mark.parametrize("query", [
    "month=invalid", "month=2026-13", "month=2026-1",
    "day=", "day=2026-02-30", "day=20261120",
    "exercise_id=", "exercise_id=abc", "exercise_id=0", "exercise_id=999",
])
def test_invalid_dashboard_filters_are_rejected(dashboard_app, query):
    response = dashboard_app.test_client().get("/history?" + query)
    assert response.status_code == 400
    assert b"Invalid history filter" in response.data


def test_empty_dashboard_has_truthful_empty_states_and_no_invalid_bar_widths(dashboard_app):
    response, context = render_history(dashboard_app)
    assert context["dashboard"]["week"]["active_days"] == 0
    assert context["dashboard"]["week"]["workouts"] == 0
    assert b"No completed exercises in the last 30 days." in response.data
    assert b"Complete an exercise and log reps or weight" in response.data
    assert b"No workouts or activities recorded yet." in response.data
    assert b"nan%" not in response.data
    assert b"inf%" not in response.data


@pytest.mark.parametrize("month, missing_link", [
    ("0001-01", b"Previous month"), ("9999-12", b"Next month"),
])
def test_calendar_at_supported_year_boundaries(dashboard_app, month, missing_link):
    response, context = render_history(dashboard_app, "/history?month=" + month)
    assert context["dashboard"]["month"] == month
    assert missing_link not in response.data
