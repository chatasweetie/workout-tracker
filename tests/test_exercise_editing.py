import csv
import re
import sqlite3
from contextlib import closing

import pytest

from app import create_app
from app import exercise_editing
from db import get_connection
from import_data import (
    COL_DESCRIPTION, COL_DOSE, COL_EQUIPMENT, COL_FLOOR, COL_FOCUS,
    COL_IMAGE, COL_NAME, COL_PER_SIDE, COL_SECONDS, REQUIRED,
    read_exercises, save_exercises,
)


@pytest.fixture
def editor(tmp_path):
    files = {kind: tmp_path / f"{kind}.csv" for kind in ("stretch", "strength")}
    for kind, path in files.items():
        fields = REQUIRED + (
            [COL_SECONDS, COL_PER_SIDE, "prefill_review"] if kind == "stretch" else []
        ) + ["custom"]
        with path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fields)
            writer.writeheader()
            for name in ("Original", "Other"):
                writer.writerow({
                    COL_FOCUS: "Back", COL_NAME: name, COL_DESCRIPTION: "Old description",
                    COL_DOSE: "Old dose", COL_IMAGE: "https://example.com/old.png",
                    COL_EQUIPMENT: "", COL_FLOOR: "FALSE", "custom": "keep, this",
                    **({COL_SECONDS: "30", COL_PER_SIDE: "TRUE", "prefill_review": "keep"}
                       if kind == "stretch" else {}),
                })
            writer.writerow({})
    config = {
        "TESTING": True, "DATABASE": tmp_path / "test.db",
        "EXERCISE_CSV_FILES": files, "BACKUP_DIR": tmp_path / "backups",
    }
    app = create_app(config)
    with closing(get_connection(config["DATABASE"])) as conn:
        for kind, path in files.items():
            exercises, _ = read_exercises(path)
            save_exercises(conn, kind, exercises)
    return app, config


def exercise_row(config, kind="stretch"):
    with closing(get_connection(config["DATABASE"])) as conn:
        return conn.execute(
            "SELECT * FROM exercises WHERE type = ? ORDER BY id LIMIT 1", (kind,),
        ).fetchone()


def edit_form(client, row, **updates):
    response = client.get(f"/exercises/{row['id']}/edit")
    assert response.status_code == 200
    revision = re.search(rb'name="revision" value="([a-f0-9]+)"', response.data)[1].decode()
    form = {
        field: str(row[field] or "")
        for field in ("type", "name", "focus", "description", "dose", "image_url", "equipment", "seconds")
    }
    for field in ("on_floor", "per_side"):
        if row[field]:
            form[field] = "1"
    form["revision"] = revision
    form.update(updates)
    return form


def add_history(config, exercise_id):
    with closing(get_connection(config["DATABASE"])) as conn:
        conn.execute(
            """INSERT INTO sessions (id, date, day_type, started_at)
               VALUES (1, '2026-11-20', 'full', '2026-11-20T10:00:00')"""
        )
        conn.execute(
            """INSERT INTO session_items
                   (id, session_id, position, block, exercise_id, status)
               VALUES (1, 1, 1, 'strength', ?, 'done')""", (exercise_id,),
        )
        conn.execute(
            """INSERT INTO strength_sets (session_item_id, set_number, reps, weight)
               VALUES (1, 1, 8, 20)"""
        )
        conn.execute(
            """INSERT INTO exercise_review_notes (exercise_id, note, created_at)
               VALUES (?, 'Check dose', '2026-11-20T10:00:00')""", (exercise_id,),
        )
        conn.commit()


def test_body_area_dropdown_lists_areas_and_selects_current_value(editor):
    app, config = editor
    with closing(get_connection(config["DATABASE"])) as conn:
        conn.execute("UPDATE exercises SET focus = 'Thighs' WHERE name = 'Other'")
        conn.commit()
    row = exercise_row(config)
    client = app.test_client()
    response = client.get(f"/exercises/{row['id']}/edit")
    select = re.search(
        rb'<select id="focus" name="focus" required>(.*?)</select>',
        response.data, re.DOTALL,
    )
    assert select is not None
    assert re.findall(rb'<option value="([^"]+)"', select[1]) == [b"Back", b"Thighs"]
    assert b'<option value="Back" selected>' in select[1]

    form = edit_form(client, row, focus="Thighs")
    assert client.post(f"/exercises/{row['id']}/edit", data=form).status_code == 302
    response = client.get(f"/exercises/{row['id']}/edit")
    assert b'<option value="Thighs" selected>' in response.data
    assert exercise_row(config)["focus"] == "Thighs"
    imported, _ = read_exercises(config["EXERCISE_CSV_FILES"]["stretch"])
    assert imported[0]["focus"] == "Thighs"


@pytest.mark.parametrize("kind", ["stretch", "strength"])
def test_edit_updates_both_stores_and_preserves_history_on_reimport(editor, kind):
    app, config = editor
    client = app.test_client()
    row = exercise_row(config, kind)
    add_history(config, row["id"])
    other_kind = "strength" if kind == "stretch" else "stretch"
    untouched_file = config["EXERCISE_CSV_FILES"][other_kind].read_bytes()
    with config["EXERCISE_CSV_FILES"][kind].open(encoding="utf-8-sig", newline="") as file:
        original_rows = list(csv.reader(file))
    form = edit_form(
        client, row, name=" Renamed   exercise ", focus="Thighs",
        description="First line\nSecond line, with a comma.",
        dose='Hold for "45" seconds.\nRepeat.', image_url="https://example.com/new.png",
        equipment="Mat", on_floor="1", seconds="45", per_side="1",
    )
    response = client.post(f"/exercises/{row['id']}/edit", data=form)
    assert response.status_code == 302
    saved = client.get(response.location)
    assert b"Exercise saved to the database and CSV." in saved.data

    updated = exercise_row(config, kind)
    assert updated["id"] == row["id"]
    assert updated["name"] == "Renamed exercise"
    assert updated["type"] == kind
    assert updated["focus"] == "Thighs"
    assert updated["dose"] == form["dose"]
    assert updated["description"] == form["description"]
    assert updated["image_url"] == form["image_url"]
    assert updated["on_floor"] == 1
    assert updated["equipment"] == "Mat"
    assert updated["seconds"] == (45 if kind == "stretch" else None)
    assert updated["per_side"] == (1 if kind == "stretch" else 0)
    path = config["EXERCISE_CSV_FILES"][kind]
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    with path.open(encoding="utf-8-sig", newline="") as file:
        changed_rows = list(csv.reader(file))
    assert changed_rows[0] == original_rows[0]
    assert changed_rows[2:] == original_rows[2:]
    assert changed_rows[1][-1] == "keep, this"
    assert config["EXERCISE_CSV_FILES"][other_kind].read_bytes() == untouched_file
    imported, _ = read_exercises(path)
    with closing(get_connection(config["DATABASE"])) as conn:
        assert save_exercises(conn, kind, imported) == (0, 2, 0)
        assert dict(conn.execute("SELECT * FROM exercises WHERE id = ?", (row["id"],)).fetchone()) == dict(updated)
        assert conn.execute("SELECT exercise_id FROM session_items").fetchone()[0] == row["id"]
        assert conn.execute("SELECT exercise_id FROM exercise_review_notes").fetchone()[0] == row["id"]
        assert conn.execute("SELECT reps, weight FROM strength_sets").fetchone()[:] == (8, 20)
    assert not list(path.parent.glob(".*-edit-*"))


@pytest.mark.parametrize("updates", [
    {"name": "  "}, {"focus": ""}, {"focus": "Back; Thighs"},
    {"type": "invalid"},
    {"name": " oThEr "}, {"image_url": "javascript:alert(1)"},
    {"image_url": "https://"}, {"seconds": "0"}, {"seconds": "-1"},
    {"seconds": "1.5"}, {"seconds": "9223372036854775808"},
    {"on_floor": "yes"},
])
def test_invalid_edits_leave_database_and_csv_unchanged(editor, updates):
    app, config = editor
    client = app.test_client()
    row = exercise_row(config)
    path = config["EXERCISE_CSV_FILES"]["stretch"]
    original = path.read_bytes()
    form = edit_form(client, row, **updates)
    response = client.post(f"/exercises/{row['id']}/edit", data=form)
    assert response.status_code == 400
    assert b'role="alert"' in response.data
    assert dict(exercise_row(config)) == dict(row)
    assert path.read_bytes() == original


def test_timer_and_optional_fields_can_be_cleared(editor):
    app, config = editor
    client = app.test_client()
    row = exercise_row(config)
    form = edit_form(client, row, seconds="", image_url="", equipment="None needed")
    form.pop("per_side")
    response = client.post(f"/exercises/{row['id']}/edit", data=form)
    assert response.status_code == 302
    updated = exercise_row(config)
    assert updated["seconds"] is None
    assert updated["per_side"] == 0
    assert updated["image_url"] is None
    assert updated["equipment"] is None
    imported, _ = read_exercises(config["EXERCISE_CSV_FILES"]["stretch"])
    assert imported[0]["seconds"] is None
    assert imported[0]["per_side"] == 0


@pytest.mark.parametrize("changed", ["csv", "destination-csv", "database", "other-editor"])
def test_stale_forms_are_rejected(editor, changed):
    app, config = editor
    client = app.test_client()
    row = exercise_row(config)
    path = config["EXERCISE_CSV_FILES"]["stretch"]
    form = edit_form(client, row, name="Stale edit")
    if changed == "csv":
        path.write_bytes(path.read_bytes() + b"\r\n")
    elif changed == "destination-csv":
        other = config["EXERCISE_CSV_FILES"]["strength"]
        other.write_bytes(other.read_bytes() + b"\r\n")
    elif changed == "database":
        with closing(get_connection(config["DATABASE"])) as conn:
            conn.execute("UPDATE exercises SET dose = 'New dose' WHERE id = ?", (row["id"],))
            conn.commit()
    else:
        newer = edit_form(client, row, dose="Saved by another editor")
        assert client.post(f"/exercises/{row['id']}/edit", data=newer).status_code == 302
    current = dict(exercise_row(config))
    current_csv = path.read_bytes()
    response = client.post(f"/exercises/{row['id']}/edit", data=form)
    assert response.status_code == 409
    assert b"Reload the editor" in response.data
    assert dict(exercise_row(config)) == current
    assert path.read_bytes() == current_csv


@pytest.mark.parametrize("problem", ["missing", "ambiguous", "invalid-header"])
def test_csv_matching_problems_do_not_save(editor, problem):
    app, config = editor
    client = app.test_client()
    row = exercise_row(config)
    path = config["EXERCISE_CSV_FILES"]["stretch"]
    text = path.read_text(encoding="utf-8-sig")
    if problem == "missing":
        text = text.replace("Original", "Removed")
    elif problem == "ambiguous":
        text = text.replace("Other", "Original")
    else:
        text = text.replace(COL_NAME, "Missing name column")
    path.write_text(text, encoding="utf-8-sig")
    original = path.read_bytes()
    form = edit_form(client, row, dose="New dose")
    assert client.post(f"/exercises/{row['id']}/edit", data=form).status_code == 409
    assert dict(exercise_row(config)) == dict(row)
    assert path.read_bytes() == original


def test_csv_write_failure_rolls_back_database(editor, monkeypatch, caplog):
    app, config = editor
    client = app.test_client()
    row = exercise_row(config)
    path = config["EXERCISE_CSV_FILES"]["stretch"]
    original = path.read_bytes()
    form = edit_form(client, row, dose="New dose")

    def fail_replace(source, destination):
        raise PermissionError("CSV is not writable")

    monkeypatch.setattr(exercise_editing.os, "replace", fail_replace)
    response = client.post(f"/exercises/{row['id']}/edit", data=form)
    assert response.status_code == 500
    assert b"No edits were saved" in response.data
    assert "Exercise edit failed" in caplog.text
    assert dict(exercise_row(config)) == dict(row)
    assert path.read_bytes() == original
    assert not list(path.parent.glob(".*-edit-*"))


@pytest.mark.parametrize("change_type", [False, True])
def test_database_commit_failure_restores_csv(editor, change_type):
    app, config = editor
    row = exercise_row(config)
    path = config["EXERCISE_CSV_FILES"]["stretch"]
    originals = {kind: file.read_bytes() for kind, file in config["EXERCISE_CSV_FILES"].items()}
    form = edit_form(
        app.test_client(), row, name="Renamed",
        type="strength" if change_type else "stretch",
    )

    class FailedCommit(sqlite3.Connection):
        def commit(self):
            raise sqlite3.OperationalError("Commit failed")

    with closing(sqlite3.connect(config["DATABASE"], factory=FailedCommit)) as conn:
        conn.row_factory = sqlite3.Row
        with pytest.raises(sqlite3.OperationalError, match="Commit failed"):
            exercise_editing.save_exercise(conn, row["id"], config["EXERCISE_CSV_FILES"], form, ["Back"])
    for kind, file in config["EXERCISE_CSV_FILES"].items():
        assert file.read_bytes() == originals[kind]
    assert dict(exercise_row(config)) == dict(row)
    assert not list(path.parent.glob(".*-edit-*"))


def test_failed_csv_recovery_preserves_original_for_manual_restore(editor, monkeypatch):
    app, config = editor
    row = exercise_row(config)
    path = config["EXERCISE_CSV_FILES"]["stretch"]
    original = path.read_bytes()
    form = edit_form(app.test_client(), row, name="Renamed")
    replace = exercise_editing.os.replace
    calls = 0

    def fail_recovery(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise PermissionError("Recovery failed")
        replace(source, destination)

    class FailedCommit(sqlite3.Connection):
        def commit(self):
            raise sqlite3.OperationalError("Commit failed")

    monkeypatch.setattr(exercise_editing.os, "replace", fail_recovery)
    with closing(sqlite3.connect(config["DATABASE"], factory=FailedCommit)) as conn:
        conn.row_factory = sqlite3.Row
        with pytest.raises(exercise_editing.CSVRecoveryError, match="Stop editing"):
            exercise_editing.save_exercise(conn, row["id"], config["EXERCISE_CSV_FILES"], form, ["Back"])
    recovery, = path.parent.glob(".*-edit-*")
    assert recovery.read_bytes() == original
    assert dict(exercise_row(config)) == dict(row)


def test_missing_csv_shows_error_without_saving(editor):
    app, config = editor
    row = exercise_row(config)
    client = app.test_client()
    form = edit_form(client, row, name="Renamed")
    config["EXERCISE_CSV_FILES"]["stretch"].unlink()
    response = client.post(f"/exercises/{row['id']}/edit", data=form)
    assert response.status_code == 500
    assert dict(exercise_row(config)) == dict(row)
    response = client.get(f"/exercises/{row['id']}/edit")
    assert response.status_code == 500
    assert b'disabled>Save exercise' in response.data


def test_unknown_and_inactive_exercises_cannot_be_edited(editor):
    app, config = editor
    client = app.test_client()
    assert client.get("/exercises/99999/edit").status_code == 404
    row = exercise_row(config)
    with closing(get_connection(config["DATABASE"])) as conn:
        conn.execute("UPDATE exercises SET active = 0 WHERE id = ?", (row["id"],))
        conn.commit()
    assert client.get(f"/exercises/{row['id']}/edit").status_code == 404
    assert client.post(f"/exercises/{row['id']}/edit", data={}).status_code == 404


@pytest.mark.parametrize("source_type", ["stretch", "strength"])
def test_type_change_moves_csv_row_and_preserves_identity_on_reimport(editor, source_type):
    app, config = editor
    client = app.test_client()
    row = exercise_row(config, source_type)
    target_type = "strength" if source_type == "stretch" else "stretch"
    add_history(config, row["id"])
    originals = {}
    for kind, path in config["EXERCISE_CSV_FILES"].items():
        with path.open(encoding="utf-8-sig", newline="") as file:
            originals[kind] = list(csv.DictReader(file))
    form = edit_form(
        client, row, type=target_type, name="Moved exercise",
        dose="Updated during move", seconds="45", per_side="1",
    )
    response = client.post(f"/exercises/{row['id']}/edit", data=form)
    assert response.status_code == 302
    assert b"Exercise saved" in client.get(response.location).data

    for kind, path in config["EXERCISE_CSV_FILES"].items():
        with path.open(encoding="utf-8-sig", newline="") as file:
            rows = list(csv.DictReader(file))
        existing_rows = [
            {key: value or "" for key, value in item.items() if key in originals[kind][0]}
            for item in rows if item[COL_NAME] != "Moved exercise"
        ]
        expected = originals[kind][1:] if kind == source_type else originals[kind]
        assert existing_rows == expected
        if kind == source_type:
            assert all(item[COL_NAME] not in ("Original", "Moved exercise") for item in rows)
        else:
            moved, = [item for item in rows if item[COL_NAME] == "Moved exercise"]
            assert moved["custom"] == "keep, this"
            assert moved[COL_DOSE] == "Updated during move"
            if target_type == "strength":
                assert moved["prefill_review"] == "keep"
                assert COL_SECONDS not in moved
            else:
                assert moved[COL_SECONDS] == "45"
                assert moved[COL_PER_SIDE] == "TRUE"
    with closing(get_connection(config["DATABASE"])) as conn:
        updated = conn.execute("SELECT * FROM exercises WHERE id = ?", (row["id"],)).fetchone()
        assert updated["type"] == target_type
        assert updated["name"] == "Moved exercise"
        assert updated["seconds"] == (45 if target_type == "stretch" else None)
        assert updated["per_side"] == (1 if target_type == "stretch" else 0)
        for kind, path in config["EXERCISE_CSV_FILES"].items():
            exercises, _ = read_exercises(path)
            new, _, deactivated = save_exercises(conn, kind, exercises)
            assert (new, deactivated) == (0, 0)
        assert conn.execute("SELECT COUNT(*) FROM exercises").fetchone()[0] == 4
        reimported = conn.execute("SELECT * FROM exercises WHERE id = ?", (row["id"],)).fetchone()
        assert dict(reimported) == dict(updated)
        assert conn.execute("SELECT exercise_id FROM session_items").fetchone()[0] == row["id"]
        assert conn.execute("SELECT exercise_id FROM exercise_review_notes").fetchone()[0] == row["id"]
        assert conn.execute("SELECT reps, weight FROM strength_sets").fetchone()[:] == (8, 20)
    assert b"8 reps" in client.get("/session/1/summary").data
    assert not list(config["DATABASE"].parent.glob(".*-edit-*"))


@pytest.mark.parametrize("duplicate", ["database", "csv-only"])
def test_type_change_rejects_duplicate_destination_names(editor, duplicate):
    app, config = editor
    client = app.test_client()
    row = exercise_row(config)
    name = "Original"
    if duplicate == "csv-only":
        name = "CSV-only name"
        path = config["EXERCISE_CSV_FILES"]["strength"]
        path.write_bytes(path.read_bytes().replace(b"Original", name.encode()))
    originals = {kind: path.read_bytes() for kind, path in config["EXERCISE_CSV_FILES"].items()}
    form = edit_form(client, row, type="strength", name=name)
    assert client.post(f"/exercises/{row['id']}/edit", data=form).status_code == 400
    assert dict(exercise_row(config)) == dict(row)
    assert all(path.read_bytes() == originals[kind] for kind, path in config["EXERCISE_CSV_FILES"].items())


def test_failure_replacing_second_csv_restores_first_and_database(editor, monkeypatch):
    app, config = editor
    client = app.test_client()
    row = exercise_row(config)
    form = edit_form(client, row, type="strength", name="Moved exercise")
    originals = {kind: path.read_bytes() for kind, path in config["EXERCISE_CSV_FILES"].items()}
    replace = exercise_editing.os.replace
    calls = 0

    def fail_second_replace(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise PermissionError("Second CSV is not writable")
        replace(source, destination)

    monkeypatch.setattr(exercise_editing.os, "replace", fail_second_replace)
    response = client.post(f"/exercises/{row['id']}/edit", data=form)
    assert response.status_code == 500
    assert calls == 3
    assert dict(exercise_row(config)) == dict(row)
    assert all(path.read_bytes() == originals[kind] for kind, path in config["EXERCISE_CSV_FILES"].items())
    assert not list(config["DATABASE"].parent.glob(".*-edit-*"))


def test_type_change_preserves_unlabelled_destination_data(editor):
    app, config = editor
    client = app.test_client()
    row = exercise_row(config)
    destination = config["EXERCISE_CSV_FILES"]["strength"]
    with destination.open("a", encoding="utf-8", newline="") as file:
        csv.writer(file).writerow(["Back", "Extra row"] + [""] * 6 + ["Unlabelled value"])
    originals = {kind: path.read_bytes() for kind, path in config["EXERCISE_CSV_FILES"].items()}
    form = edit_form(client, row, type="strength", name="Moved exercise")
    response = client.post(f"/exercises/{row['id']}/edit", data=form)
    assert response.status_code == 302
    with destination.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.reader(file))
    header = rows[0]
    extra, = [item for item in rows[1:] if len(item) > 1 and item[1] == "Extra row"]
    assert extra[len(header):] == ["Unlabelled value"]
    assert dict(zip(header, extra))["prefill_review"] == ""
    moved, = [item for item in rows[1:] if len(item) > 1 and item[1] == "Moved exercise"]
    assert dict(zip(header, moved))["prefill_review"] == "keep"
    assert rows[1][:len(REQUIRED)] == list(csv.reader(
        originals["strength"].decode("utf-8-sig").splitlines()
    ))[1][:len(REQUIRED)]
    imported, _ = read_exercises(destination)
    assert any(item["name"] == "Moved exercise" for item in imported)


def test_type_change_preserves_unlabelled_source_data(editor):
    app, config = editor
    client = app.test_client()
    row = exercise_row(config, "strength")
    source = config["EXERCISE_CSV_FILES"]["strength"]
    with source.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.reader(file))
    overflow = ["", "", "sets-based; leave timer blank or set manually"]
    rows[1].extend(overflow)
    with source.open("w", encoding="utf-8-sig", newline="") as file:
        csv.writer(file).writerows(rows)
    form = edit_form(client, row, type="stretch", name="Moved exercise", seconds="45")
    assert client.post(f"/exercises/{row['id']}/edit", data=form).status_code == 302
    destination = config["EXERCISE_CSV_FILES"]["stretch"]
    with destination.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.reader(file))
    moved, = [item for item in rows[1:] if len(item) > 1 and item[1] == "Moved exercise"]
    assert moved[len(rows[0]):] == overflow
    imported, _ = read_exercises(destination)
    moved, = [item for item in imported if item["name"] == "Moved exercise"]
    assert moved["seconds"] == 45


def test_failed_recovery_of_one_csv_does_not_prevent_other_csv_recovery(editor, monkeypatch):
    app, config = editor
    row = exercise_row(config)
    form = edit_form(app.test_client(), row, type="strength", name="Moved exercise")
    originals = {kind: path.read_bytes() for kind, path in config["EXERCISE_CSV_FILES"].items()}
    replace = exercise_editing.os.replace
    calls = 0

    def fail_one_recovery(source, destination):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise PermissionError("Destination CSV recovery failed")
        replace(source, destination)

    class FailedCommit(sqlite3.Connection):
        def commit(self):
            raise sqlite3.OperationalError("Commit failed")

    monkeypatch.setattr(exercise_editing.os, "replace", fail_one_recovery)
    with closing(sqlite3.connect(config["DATABASE"], factory=FailedCommit)) as conn:
        conn.row_factory = sqlite3.Row
        with pytest.raises(exercise_editing.CSVRecoveryError, match="Stop editing"):
            exercise_editing.save_exercise(conn, row["id"], config["EXERCISE_CSV_FILES"], form, ["Back"])
    assert calls == 4
    assert config["EXERCISE_CSV_FILES"]["stretch"].read_bytes() == originals["stretch"]
    recovery, = config["DATABASE"].parent.glob(".*-edit-*")
    assert recovery.read_bytes() == originals["strength"]
    assert dict(exercise_row(config)) == dict(row)


@pytest.mark.parametrize("target_type", ["stretch", "strength"])
def test_workout_saves_after_type_change_preserve_old_sets_or_allow_strength_edits(editor, target_type):
    app, config = editor
    client = app.test_client()
    source_type = "strength" if target_type == "stretch" else "stretch"
    row = exercise_row(config, source_type)
    add_history(config, row["id"])
    form = edit_form(client, row, type=target_type, name="Moved exercise")
    assert client.post(f"/exercises/{row['id']}/edit", data=form).status_code == 302
    stale = client.post("/api/items/1", json={
        "type": source_type, "status": "pending", "sets": [],
    })
    assert stale.status_code == 409
    assert "Reload" in stale.get_json()["error"]

    response = client.post("/api/items/1", json={
        "type": target_type, "status": "pending", "sets": [],
    })
    assert response.status_code == 200
    with closing(get_connection(config["DATABASE"])) as conn:
        sets = conn.execute("SELECT reps, weight FROM strength_sets").fetchall()
        assert [tuple(item) for item in sets] == ([(8, 20)] if target_type == "stretch" else [])
