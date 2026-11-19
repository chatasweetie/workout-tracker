# Workout Tracker

A personal, local-first workout tracker built with Flask, SQLite, and vanilla JavaScript.

The app selects varied workouts from a curated exercise library, guides you through each exercise, records performance, and lets you capture exercise corrections for later review.

It runs on a laptop in a browser. The browser or laptop display can be mirrored to a TV.

## Features

- Import stretching and strength exercises from two CSV files.
- Browse exercises by type and body area.
- Generate workouts using a weekday schedule.
- Rotate exercise selection using completion history.
- Display one exercise at a time with instructions, dose, and demonstration image.
- Run stretching timers with preparation and side-switch buffers.
- Record completed and skipped exercises.
- Log actual strength sets, reps, and weight in pounds.
- Save exercise-review notes for later corrections.
- Automatically finish sessions when every exercise is completed or skipped.
- View workout summaries and history.
- Resume unfinished sessions.

No accounts, cloud hosting, AI services, or frontend build tools are required.

## Requirements

- Python 3.12 is the current development environment.
- A browser.
- Internet access for externally hosted exercise images.

The application and database run locally. Exercise images may be unavailable without internet.

## Setup

The commands below target macOS Terminal.

### 1. Open the project directory

```bash
cd /path/to/health-tracker
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
python -m pip install -r requirements.txt
```

The project uses Flask and pytest, plus Python's standard library.

### 4. Add the exercise CSV files

Place the source files at:

```text
data/stretch.csv
data/strength.csv
```

### 5. Import the exercise library

```bash
python import_data.py
```

The importer creates the database and prints exercise counts, skipped rows, and warnings.

The current library target is:

| Type | Exercises |
| --- | ---: |
| Stretching | 114 |
| Strength | 119 |
| Total | 233 |

Use the import report to verify the actual counts in your files.

### 6. Start the application

```bash
python -m flask --app 'app:create_app()' run --debug --port 5001
```

Open:

```text
http://127.0.0.1:5001
```

Port 5001 is used in the project's local commands to avoid the port-5000 conflict encountered during setup.

Keep the server local. The debug command is for development, not public deployment.

Stop the server with `Ctrl+C`.

## Starting the App Later

From the repository root:

```bash
source .venv/bin/activate
python -m flask --app 'app:create_app()' run --debug --port 5001
```

There is no need to reinstall dependencies or reimport exercises every time.

If the browser still displays older JavaScript or styling after a change, try a hard refresh with `Command+Shift+R`.

## Workout Schedule

| Day | Session | Structure |
| --- | --- | --- |
| Monday, Wednesday, Friday | Full day | 10 stretches → 10 strength → 10 different stretches |
| Tuesday, Thursday | Flexibility | 20 stretches, including 3 Balance exercises |
| Saturday, Sunday | Rest | Either session can be started manually |

Both workout types are available from the homepage.

Starting a workout creates a new session and saves its exercise sequence. Refreshing an existing session does not generate a new selection.

## Exercise Selection

Selection is based on rules and recorded history, not AI.

The selector:

1. Allocates slots across eligible body areas.
2. Gives extra slots to priority areas before distributing them elsewhere.
3. Within each area, prefers exercises with fewer completions.
4. Breaks completion-count ties using the oldest completion time.
5. Randomizes remaining ties.
6. Avoids duplicate exercises within a session.
7. Groups standing and floor exercises.
8. Tries to avoid consecutive exercises from the same area.

Priority areas are:

- Hips & Glutes
- Thighs
- Back

Balance exercises are selected only for flexibility sessions.

### Rotation is per area

Small exercise pools may repeat while larger areas still have unused exercises.

The app does not guarantee that all exercises in the entire library are completed before any exercise repeats.

Skipped and pending exercises do not increase completion counts.

### Floor and standing order

Full-day blocks are arranged as:

- Opening stretches: standing, then floor.
- Strength: floor, then standing.
- Closing stretches: standing, then floor.

Area separation is best-effort within those constraints.

## Using the Workout Player

Each exercise displays:

- Exercise name and body area.
- Position in the workout and block name.
- Prescribed dose.
- Instructions.
- Demonstration image, when available.
- Equipment information, when supplied.
- Stretch timer or strength-set inputs.
- Exercise notes.

### Keyboard Controls

| Key | Action |
| --- | --- |
| Right Arrow | Start, pause, or resume the stretch timer |
| Space | Save the current exercise as completed and advance |
| S | Save the current exercise as skipped and advance |
| Left Arrow | Save current edits and move back one exercise |

Global shortcuts are ignored while focus is on an input, textarea, button, or link.

If a shortcut appears unresponsive after clicking a control, click the exercise heading or another non-interactive area first.

Visible buttons are available for the main actions.

### Saving

Save, Complete, Skip, and Back save the current exercise's entered data.

- Save preserves its existing completion status.
- Complete marks it done.
- Skip marks it skipped.
- Back preserves its current status while navigating backward.
- A failed save keeps the player on the current exercise.

Strength fields are optional. An exercise can be completed without entering actual reps or weight.

## Stretch Timers

Timers appear only for stretches with a positive `seconds` value.

### Single hold

```text
Start → 2-second preparation buffer → timed hold → beep and stop
```

### Per-side hold

```text
Start
→ 2-second preparation buffer
→ first hold
→ beep
→ 2-second switch-sides buffer
→ second hold starts automatically
→ beep and stop
```

Right Arrow or the timer button pauses and resumes the countdown.

Resuming continues the remaining countdown without adding another buffer.

Reset returns to the first hold and restores the initial preparation buffer.

Timer completion does not automatically complete the exercise. Use Complete or Space when ready.

### Timer limitations

- Timer progress is not saved to the database.
- Refreshing or returning to an exercise resets its timer.
- Keep the laptop awake while using the timer.
- Sound depends on browser audio permissions and output settings.
- The timer model supports one hold or two equal per-side holds.
- More complex prescriptions must be followed using the dose text.

## Strength Logging

Strength exercises support multiple set rows.

Each row records:

- Set number.
- Actual reps.
- Actual weight in pounds.

Saving replaces the existing set records for that exercise occurrence rather than appending duplicate rows.

Weight may be zero. Reps, when entered, must be positive whole numbers.

## Exercise Notes and Reviews

The workout player has one notes section, used for exercise-level corrections and personal adjustments.

Examples:

- This belongs in strength rather than stretching.
- Review the prescribed dose.
- The image shows the wrong movement.
- Replace this exercise with something more suitable.

These are not session-performance notes.

### Review workflow

1. Enter a note during a workout.
2. Use Save, Complete, Skip, or Back.
3. Find the saved note on the Exercise reviews page.
4. Make the correction in the source CSV.
5. Reimport the CSV files.
6. Mark the note resolved.

Open notes appear when that exercise is displayed in a later workout.

The review page includes Open and Resolved views.

### Saving behavior

Exercise notes and workout outcomes are saved through separate requests.

If a note saves but the workout outcome fails:

- The note remains saved.
- The player stays on the exercise.
- The cleared note field avoids reposting it during an ordinary retry.

### Exercise identity limitation

The importer identifies exercises by type and name.

Renaming an exercise or moving it between the stretch and strength CSVs creates a new exercise record and deactivates the old one.

Existing reviews and workout history remain attached to the old record. Reviews for inactive exercises remain available.

## Session Completion and Resume

A session finishes automatically when every exercise is either completed or skipped.

The completion screen shows:

- Completed and skipped counts.
- A varied celebration when at least one exercise was completed.
- A Return to home link.
- A View summary link.

No Finish button is required.

Finished sessions are read-only in the current interface.

### Resume behavior

Opening an unfinished session resumes at its first pending exercise.

The homepage lists unfinished sessions from yesterday only.

Other unfinished sessions, including today's, can be opened through History.

### Expired sessions

Opening the homepage closes unfinished sessions started more than 24 hours ago.

For those sessions:

- Pending exercises become skipped.
- Completed and already-skipped exercises remain unchanged.
- Notes and strength sets are preserved.
- The session receives a finish timestamp.

Expiration is based on the original start time, not the most recent activity.

Cleanup runs when the homepage is requested. It does not run as a background job while the application is stopped.

For expired sessions, the finish timestamp represents when cleanup closed the record.

## Summary and History

The summary displays:

- Session date and type.
- Start and finish times.
- Completed, skipped, and pending counts.
- Exercise outcomes.
- Recorded strength sets.

Summary dates use a readable format such as:

```text
Wednesday, Nov 18, 2026
```

Times use 12-hour format:

```text
9:05 am
```

History lists sessions with summary links and Resume links for unfinished sessions.

## Exercise CSV Format

Both source files use these columns:

```text
Muscle/Body focus
Activity Name
Short description
Dose (number or repetitions or how long to hold)
Image or Video demo URL
Equipment needed
Done on the floor (True/False)
```

The stretching CSV also supports:

```text
seconds
per_side
```

A temporary `prefill_review` column is ignored.

### Import behavior

- Exercise type comes from the source filename.
- Rows missing an area or exercise name are skipped.
- Whitespace is normalized.
- Combined areas keep their first component.
- Blank or unrecognized floor flags produce warnings and default to false.
- Invalid timer values produce warnings.
- Blank equipment or values starting with “None” mean no equipment.
- Reimporting updates matching type/name records.
- Exercises removed from the CSV become inactive rather than being deleted.

Run the importer after editing the source files:

```bash
python import_data.py
```

Review its report before starting another workout.

## Data Storage

The database is stored at:

```text
data/workout.db
```

The application uses these tables:

| Table | Purpose |
| --- | --- |
| `exercises` | Imported exercise catalog |
| `sessions` | Workout session records |
| `session_items` | Planned sequence and saved exercise outcomes |
| `strength_sets` | Actual strength performance |
| `exercise_review_notes` | Exercise corrections and review status |

Completion counts and last-completed values are derived from saved exercise outcomes.

The `instance/` directory is not the database location in this project.

### Historical exercise details

Sessions store exercise references, not complete catalog snapshots.

Updating an exercise's description or dose can change the details displayed for an older session. Actual logged sets, reps, weight, and outcomes remain stored separately.

## Project Structure

```text
health-tracker/
├── app/
│   ├── __init__.py
│   ├── tracking.py
│   ├── reviews.py
│   ├── templates/
│   │   ├── index.html
│   │   ├── exercises.html
│   │   ├── workout.html
│   │   ├── summary.html
│   │   ├── history.html
│   │   └── reviews.html
│   └── static/
│       ├── css/
│       │   └── styles.css
│       └── js/
│           ├── workout.js
│           └── stretch-timer.js
├── data/
│   ├── stretch.csv
│   ├── strength.csv
│   └── workout.db
├── tests/
├── config.py
├── db.py
├── import_data.py
├── selection.py
├── pytest.ini
├── requirements.txt
└── README.md
```

Local environment directories, caches, and optional media directories are omitted.

## Testing

Run tests from the repository root:

```bash
python -m pytest
```

Selection testing is implemented. Import, tracking, review, expiration, and backup coverage should be verified or expanded as the project develops.

### Manual acceptance checklist

- [ ] Import the complete exercise library.
- [ ] Reimport without creating duplicate exercises.
- [ ] Generate both workout types.
- [ ] Confirm no duplicate exercises within a session.
- [ ] Save completion and skips, then refresh.
- [ ] Save multiple strength sets, then refresh.
- [ ] Verify timer pause, reset, and automatic second-side behavior.
- [ ] Save an exercise note and find it on the review page.
- [ ] Resolve a review note.
- [ ] Finish a session and inspect its summary.
- [ ] Verify expired-session cleanup using test data.
- [ ] Test readability and controls on the TV.
- [ ] Create and restore a database backup.

## Backups

A dedicated backup command and documented restore procedure remain to be implemented.

The database contains workout history, performance records, and exercise-review notes. Preserve it before destructive resets or database changes.

Source CSVs can rebuild the exercise catalog, but they cannot restore workout history or review notes.

Keep local databases and backup files out of Git.

## Known Limitations

- Personal, single-user application.
- No authentication or public deployment.
- No mobile-specific interface.
- Remote images can fail or disappear.
- No live Google Sheets synchronization.
- No in-app exercise editor.
- No calendar or progress charts.
- No CSV history export.
- No persistent timer progress.
- No stable CSV exercise IDs across renames or category changes.
- No dedicated backup/restore tool yet.

## Planned Improvements

- Database backup and restore verification.
- Additional automated tests.
- Calendar and progress summaries.
- Previous strength performance displayed during workouts.
- Local image downloads.
- Stable exercise identifiers.
- In-app exercise editing.
- CSV export.