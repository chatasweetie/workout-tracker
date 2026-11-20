import re
from contextlib import closing
from datetime import date

import pytest

from app import create_app
from db import get_connection


@pytest.fixture
def activity_app(tmp_path):
    return create_app({
        "TESTING": True,
        "DATABASE": tmp_path / "test.db",
        "BACKUP_DIR": tmp_path / "backups",
    })


def activity_form(**updates):
    values = {
        "activity_type": "walk", "date": "2026-11-20",
        "duration_minutes": "30.5", "distance_miles": "1.25",
    }
    values.update(updates)
    return values


def test_home_links_to_activity_form_with_today_as_default(activity_app):
    client = activity_app.test_client()
    home = client.get("/")
    assert b'href="/activities"' in home.data
    assert re.search(rb'name="day_type"\s+value="full"', home.data)
    assert re.search(rb'name="day_type"\s+value="flex"', home.data)
    response = client.get("/activities")
    assert response.status_code == 200
    assert f'value="{date.today().isoformat()}"'.encode() in response.data
    assert b"Duration (minutes)" in response.data
    assert b"Distance (miles)" in response.data
    assert b"No activities logged yet." in response.data


@pytest.mark.parametrize("activity_type", ["walk", "run", "bike"])
def test_activity_persists_after_restart_without_refresh_duplicates(activity_app, activity_type):
    client = activity_app.test_client()
    response = client.post("/activities", data=activity_form(activity_type=activity_type))
    assert response.status_code == 302
    response = client.get(response.location)
    assert b"Activity saved." in response.data
    assert b"30.5 minutes" in response.data
    assert b"1.25 miles" in response.data
    restarted = create_app(dict(activity_app.config))
    assert restarted.test_client().get("/activities").status_code == 200
    assert client.get("/activities").status_code == 200
    with closing(get_connection(activity_app.config["DATABASE"])) as conn:
        rows = conn.execute("SELECT * FROM activity_logs").fetchall()
        assert len(rows) == 1
        assert rows[0]["activity_type"] == activity_type
        assert rows[0]["date"] == "2026-11-20"
        assert rows[0]["duration_minutes"] == 30.5
        assert rows[0]["distance_miles"] == 1.25
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


def test_zero_distance_is_allowed(activity_app):
    response = activity_app.test_client().post(
        "/activities", data=activity_form(activity_type="bike", distance_miles="0"),
    )
    assert response.status_code == 302
    with closing(get_connection(activity_app.config["DATABASE"])) as conn:
        assert conn.execute("SELECT distance_miles FROM activity_logs").fetchone()[0] == 0


@pytest.mark.parametrize("updates", [
    {"activity_type": "swim"},
    {"date": ""}, {"date": "2026-02-30"}, {"date": "20261120"},
    {"duration_minutes": ""}, {"duration_minutes": "0"}, {"duration_minutes": "-1"},
    {"duration_minutes": "nan"}, {"duration_minutes": "inf"}, {"duration_minutes": "invalid"},
    {"distance_miles": ""}, {"distance_miles": "-1"},
    {"distance_miles": "nan"}, {"distance_miles": "inf"},
])
def test_invalid_activity_is_not_saved_and_retains_entries(activity_app, updates):
    response = activity_app.test_client().post("/activities", data=activity_form(**updates))
    assert response.status_code == 400
    assert b'role="alert"' in response.data
    assert b"Activity saved." not in response.data
    assert b'value="30.5"' in response.data or "duration_minutes" in updates
    assert b'value="1.25"' in response.data or "distance_miles" in updates
    with closing(get_connection(activity_app.config["DATABASE"])) as conn:
        assert conn.execute("SELECT COUNT(*) FROM activity_logs").fetchone()[0] == 0


def test_activities_sort_by_date_then_latest_entry(activity_app):
    client = activity_app.test_client()
    for kind, day in (("run", "2026-11-20"), ("bike", "2026-11-19"), ("walk", "2026-11-20")):
        assert client.post(
            "/activities", data=activity_form(activity_type=kind, date=day),
        ).status_code == 302
    response = client.get("/activities")
    entries = re.findall(
        rb'<h3>\s*(\w+)\s*\xc2\xb7 <time datetime="([^"]+)"',
        response.data,
    )
    assert entries == [(b"Walk", b"2026-11-20"), (b"Run", b"2026-11-20"), (b"Bike", b"2026-11-19")]


def test_save_failure_is_logged_and_shown_without_losing_entries(activity_app, caplog):
    with closing(get_connection(activity_app.config["DATABASE"])) as conn:
        conn.execute(
            """CREATE TRIGGER reject_activity BEFORE INSERT ON activity_logs
               BEGIN SELECT RAISE(ABORT, 'Activity storage unavailable'); END"""
        )
        conn.commit()
    response = activity_app.test_client().post("/activities", data=activity_form())
    assert response.status_code == 500
    assert b"Could not save this activity" in response.data
    assert b"Activity saved." not in response.data
    assert b'value="30.5"' in response.data
    assert b'value="1.25"' in response.data
    assert "Activity log save failed" in caplog.text
    with closing(get_connection(activity_app.config["DATABASE"])) as conn:
        assert conn.execute("SELECT COUNT(*) FROM activity_logs").fetchone()[0] == 0


def test_history_combines_activities_and_workouts_in_date_order(activity_app):
    with closing(get_connection(activity_app.config["DATABASE"])) as conn:
        conn.execute(
            """INSERT INTO exercises (id, type, focus, name)
               VALUES (1, 'stretch', 'Back', 'Test exercise')"""
        )
        conn.executemany(
            """INSERT INTO sessions (id, date, day_type, started_at, finished_at)
               VALUES (?, ?, ?, ?, ?)""",
            [
                (1, "2026-11-20", "full", "2026-11-20T09:00:00", "2026-11-20T10:00:00"),
                (2, "2026-11-18", "flex", "2026-11-18T09:00:00", None),
            ],
        )
        conn.executemany(
            """INSERT INTO session_items (session_id, position, block, exercise_id, status)
               VALUES (?, ?, 'stretch', 1, ?)""",
            [(1, 1, "done"), (1, 2, "skipped"), (2, 1, "pending")],
        )
        conn.commit()
    client = activity_app.test_client()
    for kind, day in (("walk", "2026-11-19"), ("run", "2026-11-20"), ("bike", "2026-11-21")):
        assert client.post(
            "/activities", data=activity_form(activity_type=kind, date=day),
        ).status_code == 302
    with closing(get_connection(activity_app.config["DATABASE"])) as conn:
        conn.execute(
            "UPDATE activity_logs SET created_at = '2026-11-20T11:00:00' WHERE activity_type = 'run'",
        )
        conn.commit()

    response = client.get("/history")
    assert response.status_code == 200
    headings = re.findall(rb"<h2>([^<]+)</h2>", response.data)
    assert headings == [
        f"{day} \u00b7 {label}".encode()
        for day, label in [
            ("2026-11-21", "Bike"), ("2026-11-20", "Run"), ("2026-11-20", "full"),
            ("2026-11-19", "Walk"), ("2026-11-18", "flex"),
        ]
    ]
    cards = re.findall(rb'<article class="card">(.*?)</article>', response.data, re.DOTALL)
    workout = cards[2]
    assert b"Finished" in workout
    assert b"1 completed" in workout
    assert b"1 skipped" in workout
    assert b"0 pending" in workout
    assert b'href="/session/1/summary"' in workout
    assert b'href="/session/1"' not in workout
    unfinished = cards[4]
    assert b"Unfinished" in unfinished
    assert b"1 pending" in unfinished
    assert b'href="/session/2/summary"' in unfinished
    assert b'href="/session/2"' in unfinished
    assert b"30.5 minutes" in cards[0]
    assert b"1.25 miles" in cards[0]


def test_history_shows_activities_without_workout_sessions(activity_app):
    client = activity_app.test_client()
    for kind in ("walk", "run", "bike"):
        assert client.post(
            "/activities", data=activity_form(activity_type=kind),
        ).status_code == 302
    response = client.get("/history")
    assert response.status_code == 200
    assert len(re.findall(rb"<h2>", response.data)) == 3
    for kind in ("Walk", "Run", "Bike"):
        assert kind.encode() in response.data
    assert b"No workouts or activities" not in response.data
    assert b"View summary" not in response.data
    assert b"Resume" not in response.data
    assert b'href="/history"' in client.get("/activities").data


def test_history_empty_state(activity_app):
    response = activity_app.test_client().get("/history")
    assert response.status_code == 200
    assert b"No workouts or activities recorded yet." in response.data
