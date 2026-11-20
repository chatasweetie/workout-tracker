"""Backup and restore tests use temporary databases, never the real database."""
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta

import pytest

import backup
from app import create_app
from db import get_connection, init_db


def test_backup_restores_all_tables_from_live_wal_database(tmp_path):
    source_path = tmp_path / "source.db"
    with closing(get_connection(source_path)) as source:
        source.execute("PRAGMA journal_mode = WAL")
        init_db(source)
        source.execute(
            """INSERT INTO exercises (id, type, focus, name)
               VALUES (1, 'strength', 'Back', 'Test exercise')"""
        )
        source.execute(
            """INSERT INTO sessions (id, date, day_type, started_at)
               VALUES (1, '2026-11-20', 'full', '2026-11-20T10:00:00')"""
        )
        source.execute(
            """INSERT INTO session_items
                   (id, session_id, position, block, exercise_id, status, completed_at)
               VALUES (1, 1, 1, 'strength', 1, 'done', '2026-11-20T10:01:00')"""
        )
        source.execute(
            """INSERT INTO strength_sets (session_item_id, set_number, reps, weight)
               VALUES (1, 1, 10, 20)"""
        )
        source.execute(
            """INSERT INTO exercise_review_notes
                   (exercise_id, session_item_id, note, created_at)
               VALUES (1, 1, 'Check demo', '2026-11-20T10:01:00')"""
        )
        source.execute(
            """INSERT INTO activity_logs
                   (activity_type, date, duration_minutes, distance_miles, created_at)
               VALUES ('walk', '2026-11-20', 30.5, 1.25, '2026-11-20T11:00:00')"""
        )
        source.commit()
        expected = list(source.iterdump())
        source.execute("UPDATE strength_sets SET weight = 99")

        path = backup.backup_database(source_path, tmp_path / "backups")

        with closing(sqlite3.connect(path)) as snapshot:
            with closing(get_connection(tmp_path / "restored.db")) as restored:
                snapshot.backup(restored)
                assert list(restored.iterdump()) == expected
                assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                assert restored.execute("PRAGMA foreign_key_check").fetchall() == []
        assert source.execute("SELECT weight FROM strength_sets").fetchone()[0] == 99
        source.rollback()


def test_repeated_backups_preserve_previous_snapshot(tmp_path):
    source_path = tmp_path / "source.db"
    with closing(sqlite3.connect(source_path)) as source:
        source.execute("CREATE TABLE example (value TEXT)")
        source.execute("INSERT INTO example VALUES ('first')")
        source.commit()
        first = backup.backup_database(source_path, tmp_path / "backups")
        source.execute("UPDATE example SET value = 'second'")
        source.commit()
        second = backup.backup_database(source_path, tmp_path / "backups")

    assert first != second
    for path, expected in ((first, "first"), (second, "second")):
        with closing(sqlite3.connect(path)) as snapshot:
            assert snapshot.execute("SELECT value FROM example").fetchone() == (expected,)


def test_missing_source_is_not_created(tmp_path):
    source = tmp_path / "missing.db"
    destination = tmp_path / "backups"
    with pytest.raises(sqlite3.OperationalError):
        backup.backup_database(source, destination)
    assert not source.exists()
    assert not destination.exists()


def test_invalid_database_leaves_no_backup(tmp_path):
    source = tmp_path / "invalid.db"
    source.write_text("not a SQLite database")
    destination = tmp_path / "backups"
    with pytest.raises(sqlite3.DatabaseError):
        backup.backup_database(source, destination)
    assert list(destination.iterdir()) == []


def test_command_uses_environment_destination(tmp_path, monkeypatch, capsys):
    source = tmp_path / "source.db"
    with closing(sqlite3.connect(source)) as conn:
        conn.execute("CREATE TABLE example (value TEXT)")
    destination = tmp_path / "custom-backups"
    monkeypatch.setenv("WORKOUT_BACKUP_DIR", str(destination))
    create_backup = backup.backup_database
    monkeypatch.setattr(
        backup, "backup_database",
        lambda backup_dir: create_backup(source, backup_dir),
    )

    assert backup.main() == 0
    assert len(list(destination.glob("workout-*.db"))) == 1
    assert str(destination) in capsys.readouterr().out


@pytest.mark.parametrize("destination", ["", "   "])
def test_command_rejects_empty_destination(destination, monkeypatch, capsys):
    monkeypatch.setenv("WORKOUT_BACKUP_DIR", destination)
    assert backup.main() == 1
    assert "must not be empty" in capsys.readouterr().err


def test_command_reports_failure(tmp_path, monkeypatch, capsys):
    destination = tmp_path / "not-a-directory"
    destination.write_text("existing file")
    monkeypatch.setenv("WORKOUT_BACKUP_DIR", str(destination))
    source = tmp_path / "source.db"
    with closing(sqlite3.connect(source)) as conn:
        conn.execute("CREATE TABLE example (value TEXT)")
    create_backup = backup.backup_database
    monkeypatch.setattr(
        backup, "backup_database",
        lambda backup_dir: create_backup(source, backup_dir),
    )

    assert backup.main() == 1
    output = capsys.readouterr()
    assert "Backup failed:" in output.err
    assert not output.out


@pytest.fixture
def app_config(tmp_path):
    return {
        "TESTING": True,
        "DATABASE": tmp_path / "source.db",
        "BACKUP_DIR": tmp_path / "backups",
    }


def test_home_backs_up_once_per_day_even_after_restart(app_config, monkeypatch):
    app = create_app(app_config)
    assert app.test_client().get("/").status_code == 200
    paths = list(app_config["BACKUP_DIR"].glob("*.db"))
    assert len(paths) == 1
    contents = paths[0].read_bytes()

    assert app.test_client().get("/").status_code == 200
    restarted_app = create_app(app_config)
    assert restarted_app.test_client().get("/").status_code == 200
    assert list(app_config["BACKUP_DIR"].glob("*.db")) == paths
    assert paths[0].read_bytes() == contents

    tomorrow = datetime.now() + timedelta(days=1)

    class NextDay(datetime):
        @classmethod
        def now(cls):
            return tomorrow

    monkeypatch.setattr(backup, "datetime", NextDay)
    assert restarted_app.test_client().get("/").status_code == 200
    assert len(list(app_config["BACKUP_DIR"].glob("*.db"))) == 2
    assert paths[0].read_bytes() == contents


def test_home_backup_includes_expired_session_cleanup(app_config):
    app = create_app(app_config)
    with closing(get_connection(app_config["DATABASE"])) as conn:
        conn.execute(
            """INSERT INTO exercises (id, type, focus, name)
               VALUES (1, 'stretch', 'Back', 'Test exercise')"""
        )
        conn.execute(
            """INSERT INTO sessions (id, date, day_type, started_at)
               VALUES (1, '2000-01-01', 'flex', '2000-01-01T10:00:00')"""
        )
        conn.execute(
            """INSERT INTO session_items
                   (session_id, position, block, exercise_id)
               VALUES (1, 1, 'stretch', 1)"""
        )
        conn.commit()

    assert app.test_client().get("/").status_code == 200
    path, = app_config["BACKUP_DIR"].glob("*.db")
    with closing(sqlite3.connect(path)) as snapshot:
        assert snapshot.execute("SELECT status FROM session_items").fetchone() == (
            "skipped",
        )
        assert snapshot.execute("SELECT finished_at FROM sessions").fetchone()[0]


def test_home_reports_backup_failure_and_retries(app_config, caplog):
    destination = app_config["BACKUP_DIR"]
    destination.write_text("not a directory")
    app = create_app(app_config)

    response = app.test_client().get("/")
    assert response.status_code == 200
    assert b"Automatic backup failed" in response.data
    assert b'role="alert"' in response.data
    assert "Automatic database backup failed" in caplog.text

    destination.unlink()
    response = app.test_client().get("/")
    assert response.status_code == 200
    assert b"Automatic backup failed" not in response.data
    assert len(list(destination.glob("*.db"))) == 1


def test_home_uses_environment_destination(tmp_path, monkeypatch):
    destination = tmp_path / "environment-backups"
    monkeypatch.setenv("WORKOUT_BACKUP_DIR", str(destination))
    app = create_app({"TESTING": True, "DATABASE": tmp_path / "source.db"})
    assert app.test_client().get("/").status_code == 200
    assert len(list(destination.glob("*.db"))) == 1


def test_manual_snapshot_satisfies_daily_backup(app_config):
    app = create_app(app_config)
    path = backup.backup_database(
        app_config["DATABASE"], app_config["BACKUP_DIR"],
    )
    assert app.test_client().get("/").status_code == 200
    assert list(app_config["BACKUP_DIR"].glob("*.db")) == [path]
