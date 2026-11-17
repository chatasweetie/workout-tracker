"""Load data/stretch.csv and data/strength.csv into the exercises table.

Run it from the project folder:  python import_data.py
It is safe to run again whenever the CSV files change.
"""
import csv
import sys
from collections import Counter
from pathlib import Path

from db import DB_PATH, get_connection, init_db

DATA_DIR = Path(__file__).parent / "data"
FILES = {
    "stretch": DATA_DIR / "stretch.csv",
    "strength": DATA_DIR / "strength.csv",
}

# Column headers exactly as they appear in the CSV files.
COL_FOCUS = "Muscle/Body focus"
COL_NAME = "Activity Name"
COL_DESCRIPTION = "Short description"
COL_DOSE = "Dose (number or repetitions or how long to hold)"
COL_IMAGE = "Image or Video demo URL"
COL_EQUIPMENT = "Equipment needed"
COL_FLOOR = "Done on the floor (True/False)"
COL_SECONDS = "seconds"  # only in stretch.csv
COL_PER_SIDE = "per_side"  # only in stretch.csv
REQUIRED = [COL_FOCUS, COL_NAME, COL_DESCRIPTION, COL_DOSE, COL_IMAGE, COL_EQUIPMENT, COL_FLOOR]


def one_line(text):
    """Trim and squash any run of spaces or line breaks into a single space."""
    return " ".join((text or "").split())


def keep_lines(text):
    """Trim each line, keep the line breaks, and allow at most one blank line in a row."""
    lines = [line.strip() for line in (text or "").replace("\r\n", "\n").split("\n")]
    out = []
    for line in lines:
        if line == "" and (not out or out[-1] == ""):
            continue
        out.append(line)
    return "\n".join(out).strip()


def parse_bool(text):
    """Return True, False, or None when the cell is blank or unrecognised."""
    value = one_line(text).casefold()
    if value in ("true", "yes", "1"):
        return True
    if value in ("false", "no", "0"):
        return False
    return None


def parse_focus(text):
    """Keep only the first area ("Hips & Glutes; Thighs" -> "Hips & Glutes")."""
    return one_line(text.split(";")[0])


def canonical_spellings(exercises):
    """Map each area to its most common spelling across both files.

    "back", "Back" and "BACK" are one area; whichever spelling is used most wins.
    """
    counts = {}
    for e in exercises:
        counts.setdefault(e["focus"].casefold(), Counter())[e["focus"]] += 1
    return {key: spellings.most_common(1)[0][0] for key, spellings in counts.items()}


def parse_equipment(text):
    """Blank or anything starting with "None" means no equipment."""
    value = one_line(text)
    if not value or value.casefold().startswith("none"):
        return None
    return value


def read_exercises(path):
    """Read one CSV file. Returns (exercises, stats)."""
    stats = {"blank": 0, "incomplete": [], "duplicates": [], "warnings": []}
    exercises = []
    seen = set()

    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
        if missing:
            raise SystemExit(f"{path.name} is missing columns: {missing}")

        for line_number, row in enumerate(reader, start=2):  # line 1 is the header
            focus_raw = one_line(row.get(COL_FOCUS))
            name = one_line(row.get(COL_NAME))

            if not focus_raw and not name:
                stats["blank"] += 1
                continue
            if not focus_raw or not name:
                stats["incomplete"].append(f"line {line_number}: needs both an area and a name")
                continue
            if name.casefold() in seen:
                stats["duplicates"].append(f"line {line_number}: duplicate name '{name}'")
                continue
            seen.add(name.casefold())

            warn = stats["warnings"].append
            dose = keep_lines(row.get(COL_DOSE))
            if not dose:
                warn(f"{name}: no dose")

            on_floor = parse_bool(row.get(COL_FLOOR))
            if on_floor is None:
                warn(f"{name}: floor flag is blank or not TRUE/FALSE, using FALSE")
                on_floor = False

            seconds = None
            seconds_text = one_line(row.get(COL_SECONDS))
            if seconds_text:
                if seconds_text.isdigit() and int(seconds_text) > 0:
                    seconds = int(seconds_text)
                else:
                    warn(f"{name}: seconds '{seconds_text}' is not a whole number, ignoring")

            per_side = False
            per_side_text = one_line(row.get(COL_PER_SIDE))
            if per_side_text:
                per_side = parse_bool(per_side_text)
                if per_side is None:
                    warn(f"{name}: per_side '{per_side_text}' is not TRUE/FALSE, using FALSE")
                    per_side = False

            exercises.append({
                "focus": parse_focus(focus_raw),
                "name": name,
                "description": keep_lines(row.get(COL_DESCRIPTION)),
                "dose": dose,
                "image_url": one_line(row.get(COL_IMAGE)) or None,
                "equipment": parse_equipment(row.get(COL_EQUIPMENT)),
                "on_floor": int(on_floor),
                "seconds": seconds,
                "per_side": int(per_side),
            })
    return exercises, stats


UPSERT = """
INSERT INTO exercises
  (type, focus, name, description, dose, image_url, equipment, on_floor, seconds, per_side, active)
VALUES
  (:type, :focus, :name, :description, :dose, :image_url, :equipment, :on_floor, :seconds, :per_side, 1)
ON CONFLICT (type, name) DO UPDATE SET
  focus = excluded.focus,
  description = excluded.description,
  dose = excluded.dose,
  image_url = excluded.image_url,
  equipment = excluded.equipment,
  on_floor = excluded.on_floor,
  seconds = excluded.seconds,
  per_side = excluded.per_side,
  active = 1
"""


def save_exercises(conn, ex_type, exercises):
    """Insert or update by (type, name). Exercises no longer in the file become inactive."""
    existing = {
        row["name"]: row["active"]
        for row in conn.execute("SELECT name, active FROM exercises WHERE type = ?", (ex_type,))
    }
    new = sum(1 for e in exercises if e["name"] not in existing)

    with conn:  # one transaction: all of it happens, or none of it
        for e in exercises:
            conn.execute(UPSERT, {**e, "type": ex_type})
        names_in_file = {e["name"] for e in exercises}
        gone = [n for n, active in existing.items() if active and n not in names_in_file]
        for name in gone:
            conn.execute(
                "UPDATE exercises SET active = 0 WHERE type = ? AND name = ?", (ex_type, name)
            )
    return new, len(exercises) - new, len(gone)


def print_report(ex_type, path, exercises, stats, saved):
    new, existing, deactivated = saved
    print(f"\n{path.name}: {len(exercises)} exercises")
    print(f"  new {new} | already there {existing} | deactivated {deactivated}")
    print(f"  skipped: {stats['blank']} blank rows, {len(stats['incomplete'])} incomplete, "
          f"{len(stats['duplicates'])} duplicates")
    areas = Counter(e["focus"] for e in exercises)
    print("  by area: " + ", ".join(f"{a} {n}" for a, n in areas.most_common()))
    for message in stats["incomplete"] + stats["duplicates"]:
        print(f"  ! {message}")
    if stats["warnings"]:
        print(f"  warnings ({len(stats['warnings'])}):")
        for message in stats["warnings"]:
            print(f"    - {message}")


def main():
    for path in FILES.values():
        if not path.exists():
            print(f"Cannot find {path}")
            return 1

    # Read both files first, so area spellings can be matched across them.
    loaded = {ex_type: read_exercises(path) for ex_type, path in FILES.items()}
    everything = [e for exercises, _ in loaded.values() for e in exercises]
    spelling = canonical_spellings(everything)
    for e in everything:
        e["focus"] = spelling[e["focus"].casefold()]

    conn = get_connection()
    init_db(conn)
    for ex_type, path in FILES.items():
        exercises, stats = loaded[ex_type]
        saved = save_exercises(conn, ex_type, exercises)
        print_report(ex_type, path, exercises, stats, saved)

    total = conn.execute("SELECT COUNT(*) FROM exercises WHERE active = 1").fetchone()[0]
    print(f"\nActive exercises in {DB_PATH.name}: {total}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())