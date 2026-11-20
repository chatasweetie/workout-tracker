"""Exercise editing with coordinated database and source CSV updates."""
import csv
import hashlib
import io
import json
import logging
import os
import sqlite3
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from flask import abort, redirect, render_template, request, url_for

from import_data import (
    COL_DESCRIPTION, COL_DOSE, COL_EQUIPMENT, COL_FLOOR, COL_FOCUS,
    COL_IMAGE, COL_NAME, COL_PER_SIDE, COL_SECONDS, REQUIRED,
    keep_lines, one_line, parse_equipment,
)


CSV_FIELDS = {
    "name": COL_NAME,
    "focus": COL_FOCUS,
    "description": COL_DESCRIPTION,
    "dose": COL_DOSE,
    "image_url": COL_IMAGE,
    "equipment": COL_EQUIPMENT,
    "on_floor": COL_FLOOR,
    "seconds": COL_SECONDS,
    "per_side": COL_PER_SIDE,
}


class EditConflict(ValueError):
    """The source or exercise changed, or cannot be matched safely."""


class CSVRecoveryError(OSError):
    """The original CSV needs manual recovery after a failed database commit."""


def edit_revision(exercise, contents):
    record = {
        "exercise": dict(exercise),
        "csvs": {
            kind: hashlib.sha256(content).hexdigest()
            for kind, content in contents.items()
        },
    }
    return hashlib.sha256(json.dumps(record, sort_keys=True).encode("utf-8")).hexdigest()


def validate_values(form, exercise, focuses):
    values = {
        "type": form.get("type", exercise["type"]),
        "name": one_line(form.get("name")),
        "focus": one_line(form.get("focus")),
        "description": keep_lines(form.get("description")),
        "dose": keep_lines(form.get("dose")),
        "image_url": one_line(form.get("image_url")) or None,
        "equipment": parse_equipment(form.get("equipment")),
    }
    if values["type"] not in ("stretch", "strength"):
        raise ValueError("Choose Stretching or Strength.")
    if not values["name"] or not values["focus"]:
        raise ValueError("Enter both an exercise name and a body area.")
    if ";" in values["focus"]:
        raise ValueError("Choose one body area, without a semicolon.")
    if any("\0" in value for value in values.values() if isinstance(value, str)):
        raise ValueError("Exercise details must not contain null characters.")
    values["focus"] = next(
        (focus for focus in focuses if focus.casefold() == values["focus"].casefold()),
        values["focus"],
    )
    if values["image_url"]:
        try:
            url = urlsplit(values["image_url"])
            valid_url = url.scheme in ("http", "https") and bool(url.hostname)
        except ValueError:
            valid_url = False
        if not valid_url:
            raise ValueError("Enter an http:// or https:// demo URL, or leave it blank.")
    for field in ("on_floor", "per_side"):
        if form.get(field) not in (None, "1"):
            raise ValueError("Invalid floor or per-side checkbox value.")
        values[field] = int(form.get(field) == "1")
    values["seconds"] = None
    if values["type"] == "stretch":
        seconds = form.get("seconds", "").strip()
        if seconds:
            try:
                number = int(seconds)
            except ValueError:
                number = 0
            if not seconds.isascii() or not seconds.isdigit() or not 0 < number < 2**63:
                raise ValueError("Enter a positive whole number of seconds, or leave it blank.")
            values["seconds"] = number
    else:
        values["per_side"] = 0
    return values


def parse_csv(content, exercise_type):
    encoding = "utf-8-sig" if content.startswith(b"\xef\xbb\xbf") else "utf-8"
    text = content.decode(encoding)
    rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    required = REQUIRED + (
        [COL_SECONDS, COL_PER_SIDE] if exercise_type == "stretch" else []
    )
    if not rows or len(set(rows[0])) != len(rows[0]) or not set(required) <= set(rows[0]):
        raise EditConflict("The source CSV has missing or duplicate columns. Fix it before editing.")
    newline = "\r\n" if text.partition("\n")[0].endswith("\r") else "\n"
    return rows, encoding, newline


def find_csv_row(rows, name):
    header = rows[0]
    name_index = header.index(COL_NAME)
    matches = [
        row for row in rows[1:]
        if len(row) > name_index
        and one_line(row[name_index]).casefold() == name.casefold()
    ]
    if len(matches) != 1:
        raise EditConflict(
            "The exercise must match exactly one source CSV row. "
            "Check the CSV and reimport it before editing."
        )
    return matches[0]


def check_csv_name(rows, name, target=None):
    name_index = rows[0].index(COL_NAME)
    for row in rows[1:]:
        if row is not target and len(row) > name_index:
            if one_line(row[name_index]).casefold() == name.casefold():
                raise ValueError("Another exercise in this CSV already has that name.")


def write_csv_values(header, target, values):
    target.extend([""] * max(0, len(header) - len(target)))
    for field, column in CSV_FIELDS.items():
        if column not in header:
            continue
        value = values[field]
        if field in ("on_floor", "per_side"):
            value = "TRUE" if value else "FALSE"
        target[header.index(column)] = "" if value is None else str(value)


def encode_csv(rows, encoding, newline):
    output = io.StringIO(newline="")
    csv.writer(output, lineterminator=newline).writerows(rows)
    return output.getvalue().encode(encoding)


def updated_csvs(originals, exercise, values):
    source_type = exercise["type"]
    target_type = values["type"]
    rows, encoding, newline = parse_csv(originals[source_type], source_type)
    target = find_csv_row(rows, exercise["name"])
    if source_type == target_type:
        check_csv_name(rows, values["name"], target)
        write_csv_values(rows[0], target, values)
        return {source_type: encode_csv(rows, encoding, newline)}

    destination, dest_encoding, dest_newline = parse_csv(
        originals[target_type], target_type,
    )
    check_csv_name(destination, values["name"])
    source_values = dict(zip(rows[0], target))
    for column, value in source_values.items():
        if column not in destination[0] and value and column not in (COL_SECONDS, COL_PER_SIDE):
            position = len(destination[0])
            destination[0].append(column)
            # Keep overflow cells outside the expanded header.
            for existing in destination[1:]:
                if len(existing) > position:
                    existing.insert(position, "")
    moved = [source_values.get(column, "") for column in destination[0]]
    write_csv_values(destination[0], moved, values)
    moved.extend(target[len(rows[0]):])
    position = len(destination)
    while position > 1 and not any(value.strip() for value in destination[position - 1]):
        position -= 1
    destination.insert(position, moved)
    rows.remove(target)
    return {
        source_type: encode_csv(rows, encoding, newline),
        target_type: encode_csv(destination, dest_encoding, dest_newline),
    }


def stage_csv(path, content, suffix):
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}-edit-", suffix=suffix, delete=False,
    ) as file:
        staged = Path(file.name)
        try:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        except OSError:
            staged.unlink(missing_ok=True)
            raise
    return staged


def save_exercise(conn, exercise_id, csv_files, form, focuses):
    """Serialize editors and restore replaced CSVs if any part of saving fails."""
    paths = {kind: Path(path) for kind, path in csv_files.items()}
    if paths["stretch"].resolve() == paths["strength"].resolve():
        raise ValueError("Stretching and strength must use separate CSV files.")
    replacements = {}
    recoveries = {}
    replaced = []
    preserve_recovery = set()
    try:
        conn.execute("BEGIN IMMEDIATE")
        exercise = conn.execute(
            "SELECT * FROM exercises WHERE id = ? AND active = 1", (exercise_id,),
        ).fetchone()
        if exercise is None:
            raise EditConflict("This exercise is no longer active. Reload the library.")
        originals = {kind: path.read_bytes() for kind, path in paths.items()}
        if form.get("revision") != edit_revision(exercise, originals):
            raise EditConflict(
                "The exercise or CSV changed after you opened this page. "
                "Reload the editor and review the latest details before saving."
            )
        values = validate_values(form, exercise, focuses)
        duplicates = conn.execute(
            "SELECT name FROM exercises WHERE type = ? AND id != ?",
            (values["type"], exercise_id),
        ).fetchall()
        if any(one_line(row["name"]).casefold() == values["name"].casefold() for row in duplicates):
            raise ValueError("Another exercise of this type already has that name.")
        updates = updated_csvs(originals, exercise, values)
        for kind, content in updates.items():
            replacements[kind] = stage_csv(paths[kind], content, ".pending")
            recoveries[kind] = stage_csv(paths[kind], originals[kind], ".original")
        conn.execute(
            """UPDATE exercises SET
                   type = :type, name = :name, focus = :focus, description = :description,
                   dose = :dose, image_url = :image_url, equipment = :equipment,
                   on_floor = :on_floor, seconds = :seconds, per_side = :per_side
               WHERE id = :id""",
            {**values, "id": exercise_id},
        )
        if any(path.read_bytes() != originals[kind] for kind, path in paths.items()):
            raise EditConflict("The CSV changed during saving. Reload the editor before retrying.")
        for kind, replacement in replacements.items():
            os.replace(replacement, paths[kind])
            replaced.append(kind)
        conn.commit()
    except (OSError, sqlite3.Error, ValueError, csv.Error) as failure:
        try:
            conn.rollback()
        finally:
            recovery_errors = []
            for kind in reversed(replaced):
                try:
                    os.replace(recoveries[kind], paths[kind])
                except OSError:
                    preserve_recovery.add(kind)
                    recovery_errors.append(f"Restore {paths[kind]} from {recoveries[kind]}.")
            if recovery_errors:
                raise CSVRecoveryError(
                    "Saving failed and some CSVs could not be restored. Stop editing. "
                    + " ".join(recovery_errors)
                ) from failure
        raise
    finally:
        temporary = list(replacements.values()) + [
            path for kind, path in recoveries.items() if kind not in preserve_recovery
        ]
        for staged in temporary:
            try:
                staged.unlink(missing_ok=True)
            except OSError:
                logging.getLogger(__name__).exception(
                    "Could not remove exercise-edit temporary file %s", staged,
                )


def register_exercise_edit_routes(app, get_db):
    @app.route("/exercises/<int:exercise_id>/edit", methods=["GET", "POST"])
    def edit_exercise(exercise_id):
        conn = get_db()
        exercise = conn.execute(
            "SELECT * FROM exercises WHERE id = ? AND active = 1", (exercise_id,),
        ).fetchone()
        if exercise is None:
            abort(404, description="Active exercise not found.")
        focuses = [
            row["focus"] for row in conn.execute(
                "SELECT DISTINCT focus FROM exercises ORDER BY focus",
            )
        ]
        csv_files = app.config["EXERCISE_CSV_FILES"]
        values = dict(exercise)
        revision = ""
        error = None
        status = 200
        try:
            if request.method == "POST":
                values.update(request.form)
                for field in ("on_floor", "per_side"):
                    values[field] = request.form.get(field) == "1"
                revision = request.form.get("revision", "")
                save_exercise(conn, exercise_id, csv_files, request.form, focuses)
                return redirect(url_for("edit_exercise", exercise_id=exercise_id, saved="1"))
            contents = {kind: Path(path).read_bytes() for kind, path in csv_files.items()}
            revision = edit_revision(exercise, contents)
        except EditConflict as failure:
            error, status = str(failure), 409
        except ValueError as failure:
            error, status = str(failure), 400
        except CSVRecoveryError as failure:
            app.logger.exception("Exercise CSV recovery failed")
            error, status = str(failure), 500
        except (OSError, sqlite3.Error, csv.Error) as failure:
            app.logger.exception("Exercise edit failed")
            error = f"Could not save both the database and CSV. No edits were saved. {failure}"
            status = 500
        return render_template(
            "edit_exercise.html", exercise=exercise, values=values,
            focuses=focuses, revision=revision, error=error,
            saved=request.method == "GET" and request.args.get("saved") == "1",
        ), status
