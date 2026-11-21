# Workout Tracker

A personal, local-first workout tracker built with Flask, SQLite, and vanilla JavaScript.

The app selects varied workouts from a curated exercise library, guides you through each exercise, records performance, and lets you capture exercise corrections for later review.

It runs on a laptop in a browser. The browser or laptop display can be mirrored to a TV.

## Features

- Import stretching and strength exercises from two CSV files.
- Browse exercises by type and body area.
- Edit exercise details in the app and save to both SQLite and the source CSV.
- Generate workouts using a weekday schedule.
- Rotate exercise selection using completion history.
- Display one exercise at a time with instructions, dose, and demonstration image.
- Run stretching timers with preparation and side-switch buffers.
- Record completed and skipped exercises.
- Log actual strength sets, reps, and weight in pounds.
- Log walks, runs, and bike rides with a date, duration, and distance.
- Save exercise-review notes for later corrections.
- Automatically finish sessions when every exercise is completed or skipped.
- View workout summaries and history.
- Explore a calendar, weekly totals and trends, body-area coverage, and strength progress.
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

### macOS desktop icon

After completing Setup, install the desktop launcher once:

```bash
.venv/bin/python macos_launcher.py --install
```

Double-click **Workout Tracker** on your Desktop. It starts the local server,
waits until it is ready, and opens your default browser without a Terminal window.
Clicking it again opens the running tracker rather than starting another server.

The launcher remains in the Dock. Choose **Quit** from its Dock menu to stop a
server it started. Closing the browser alone does not stop the server.
If the project's development server is already running in Terminal on port 5001,
the launcher reuses it and leaves it running when you quit; stop that server
with `Ctrl+C` in Terminal.

Launcher servers run without the debugger or automatic code reloading. Quit and
reopen the desktop app after Python changes. Your existing database, CSV files,
and automatic backups are used unchanged.

Startup errors appear in an alert; server output is saved in
`.desktop-launcher/server.log` in the project, which is ignored by Git.
Another app using port 5001 is reported rather than stopped.

The icon points to this project and its `.venv`. If you move the project,
move the old icon to Trash and rerun the install command from its new location.
No dependencies or exercise data are installed by the launcher.

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

## Walk / Run / Bike Logging

On the homepage, choose **Log a walk, run, or bike ride**.

Each entry records:

- Activity: Walk, Run, or Bike.
- Date, defaulting to today; past dates can also be entered.
- Duration in minutes, greater than zero.
- Distance in miles, including zero.

All fields are required, and duration and distance accept decimals. Saved
activities appear on the same page and alongside workout sessions in History,
newest date first. Multiple activities can be recorded on the same day.

These entries are separate from guided workout sessions and do not affect
exercise rotation or completion counts. They are stored in the same SQLite
database and included in its backups. No CSV import or export is needed.
This version supports adding and viewing activities, not editing or deleting them.

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
4. Click Edit exercise and save the correction.
5. Mark the note resolved.

Edits made in the app update the database and CSV together; no reimport is needed.
Inactive exercises still require correcting the source CSV and reimporting.

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

Renaming an exercise directly in a CSV or moving it between the stretch and
strength CSVs creates a new exercise record and deactivates the old one.
Renaming or changing type through the app preserves the existing record and its history.

Existing reviews and workout history remain attached to the old record. Reviews for inactive exercises remain available.

## Editing Exercises

Open Exercise library, find an exercise, and click **Edit exercise**. Active
exercises also have an Edit exercise link on their review notes.

You can change:

- Name, description, dose, and image/demo URL.
- Exercise type: Stretching or Strength.
- Body area (chosen from an existing-area dropdown), equipment, and whether it is done on the floor.
- Stretch timer seconds and per-side behavior.

Changing type moves the CSV row to the other file without creating a new database
record. A conflicting name in the destination type must be changed before saving.
The form switches when you choose a type: Stretching shows timer settings,
and Strength hides and disables them. Saving as strength clears timer seconds and per-side
settings; reclassification retains previously logged strength sets.

Blank seconds disables the timer. Changing the dose text does not automatically
change timer seconds; edit both when needed.
Blank equipment or a value starting with "None" means no equipment, consistent
with CSV import. Demo URLs must use HTTP or HTTPS.

**Save exercise** updates the existing database row and the matching row in
`data/stretch.csv` or `data/strength.csv`. It preserves the database ID, workout
history, logged sets, and review notes, even when the name or type changes. A later
reimport matches the updated type and name without creating another exercise.
Older sessions display the updated exercise details rather than a historical
snapshot.

Existing sessions keep their saved sequence and block names. Reload any open
workout after a type correction so its timer and logging controls match the new
type. The player rejects saves from a stale type. Old strength sets remain visible
in summaries even after an exercise becomes a stretch.

The editor preserves other CSV rows and extra columns such as `prefill_review`.
When moving an exercise, nonempty extra fields are copied to the destination;
missing extra columns are added there. Stretch timer columns are not added to the
strength CSV.
Existing cells beyond a CSV's header are preserved as unlabelled cells rather than
blocking a move or being assigned to newly added metadata columns.
It rejects duplicate names within an exercise type and refuses to save if the
exercise or either CSV changed since the page was opened. Reload the latest details and
reapply your edits in that case. Avoid editing the CSV externally while saving.

Save errors appear on the edit page. If writing either CSV fails, database changes
are rolled back and any replaced CSVs are restored. If committing the database
fails after CSV replacement, the original CSVs are restored. If recovery also fails, the page and server
log identify a retained original file to restore manually.

SQLite and a CSV cannot share a single atomic transaction. If the process or
laptop stops during a save, stop the app and check both stores before reimporting.
Hidden `.stretch.csv-edit-*.original` or `.strength.csv-edit-*.original` files in
`data/` contain pre-edit CSV recovery copies if saving was interrupted. Compare
them with the database before restoring, since an interruption may also occur
after a successful commit. Database backups do not include the source CSVs;
preserve both before manual recovery.

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

History combines workout sessions and Walk / Run / Bike entries, newest date first.
Within a date, entries are ordered by when the session was started or the activity
was recorded. Workout sessions retain summary links and Resume links for unfinished
sessions. Activity entries show their type, duration in minutes, and distance in miles.

### History visualizations

All five views appear above the detailed History list, without external chart
services or JavaScript chart dependencies:

- **Monthly calendar:** previous/current/next month navigation and labelled badges
  for full, flexibility, walk, run, and bike records. Open and skip-only sessions
  are identified. Click a day to filter the detailed list; Show all records clears
  that filter.
- **This-week cards:** Monday through today. Active days contain at least one
  completed exercise or a cardio log. Completed workouts are finished sessions
  with at least one completed exercise; skip-only sessions are excluded. Cardio
  minutes and miles come only from walk/run/bike logs.
- **Weekly trends:** eight weeks of completed workout counts, cardio minutes, and
  cardio miles, each with its own bar scale. The current week excludes future dates.
- **Body-area coverage:** completed exercise occurrences over the last 30 days,
  including today. Pending and skipped exercises are excluded, and active library
  areas without completions show zero. Dates are the recorded session dates.
- **Strength progress:** choose an exercise with saved sets from completed exercise
  occurrences. Two charts show the heaviest logged weight and total logged reps per
  workout, across its last 12 workouts, oldest to newest. Missing weight/reps are
  labelled Not logged rather than replaced with zero. Zero weight is retained.
  Inactive or reclassified exercises with historical sets remain selectable.

Day and month navigation do not change the current-week or 30-day summary windows.
Strength chart dates link to workout summaries. Numeric chart labels are rounded
to two decimal places; the detailed records remain available below.
Exercise names and body areas reflect the current catalog, not historical snapshots.
Session start-to-finish time is not treated as exercise duration.

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

Run the importer after editing the source files directly (not after app edits):

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
| `activity_logs` | Walk, run, and bike dates, minutes, and miles |

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
│   ├── history_metrics.py
│   ├── activities.py
│   ├── reviews.py
│   ├── exercise_editing.py
│   ├── templates/
│   │   ├── index.html
│   │   ├── activities.html
│   │   ├── exercises.html
│   │   ├── edit_exercise.html
│   │   ├── workout.html
│   │   ├── summary.html
│   │   ├── history.html
│   │   ├── history_dashboard.html
│   │   └── reviews.html
│   └── static/
│       ├── css/
│       │   └── styles.css
│       └── js/
│           ├── edit-exercise.js
│           ├── workout.js
│           └── stretch-timer.js
├── data/
│   ├── stretch.csv
│   ├── strength.csv
│   └── workout.db
├── tests/
├── backup.py
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

Selection, activity logging, backup/restore, and exercise editing/synchronization tests are
implemented. Broader import, tracking, review, and expiration coverage should
be verified or expanded as the project develops.

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
- [ ] Edit and rename an exercise in the app, then verify the CSV and history.
- [ ] Log a walk, run, and bike ride and verify dates, minutes, and miles after refreshing.
- [ ] Finish a session and inspect its summary.
- [ ] Verify expired-session cleanup using test data.
- [ ] Test readability and controls on the TV.
- [ ] Create and restore a database backup.

## Backups

Backups happen automatically on your first homepage visit each day, after
expired sessions are closed. No backup command or macOS schedule is needed.
The app checks for today's timestamped backup on disk, so restarting the server
or refreshing the page does not create duplicates. A manual backup from today
also satisfies this check.

If an automatic backup fails, the homepage displays a warning and the server
logs the error. The next homepage visit retries. The app remains usable.
No backups run while the app is closed, and changes made later in the day are
captured on the next day's visit, or by a manual backup.

### Manual backups

From the repository root with the virtual environment activated:

```bash
python backup.py
```

The command uses SQLite's backup API to capture committed data, including data
in the write-ahead log, even while the app is running. It creates a unique,
timestamped `workout-*.db` file in `backups/` and runs SQLite's integrity check
before reporting success. Earlier backups are never overwritten or automatically
deleted. A failed backup reports an error and exits with a nonzero status.

To use another folder, including an already-synced cloud folder:

```bash
WORKOUT_BACKUP_DIR="$HOME/Documents/workout-backups" python backup.py
```

The destination folder is created if needed. The default `backups/` folder is
relative to the project, regardless of the current working directory.
For automatic backups, set `WORKOUT_BACKUP_DIR` when starting Flask instead:

```bash
WORKOUT_BACKUP_DIR="$HOME/Documents/workout-backups" \
  python -m flask --app 'app:create_app()' run --debug --port 5001
```

Keep a copy outside the laptop for protection against disk loss.

### Restore a backup

1. Stop the Flask server with `Ctrl+C` and close any other database connections.
2. Run `python backup.py` to preserve the current database before replacing it.
3. If `data/workout.db-wal` or `data/workout.db-shm` still exist after shutdown,
   checkpoint them using macOS's SQLite command:

   ```bash
   sqlite3 data/workout.db "PRAGMA wal_checkpoint(TRUNCATE);"
   ```

   Proceed only if the result is `0|0|0` and both journal files are gone after
   the command exits. Otherwise another connection may still be open. Do not
   manually delete the journal files.
4. Replace the database with the chosen backup (substitute its actual filename):

   ```bash
   cp backups/workout-YYYYMMDD-HHMMSS-XXXXXXXX.db data/workout.db
   ```

5. Restart the app and check History, Exercise reviews, and the Walk / Run / Bike log. Reimporting the CSVs
   is not necessary to restore a backup.

Restoring replaces all current data with the snapshot, including the exercise
catalog. Changes made after that snapshot are not included.

The database contains workout history, performance records, activity logs, and exercise-review notes. Preserve it before destructive resets or database changes.

Source CSVs can rebuild the exercise catalog, but they cannot restore workout history, activity logs, or review notes.

Keep local databases and backup files out of Git.

## Known Limitations

- Personal, single-user application.
- No authentication or public deployment.
- No mobile-specific interface.
- Remote images can fail or disappear.
- No live Google Sheets synchronization.
- No in-app exercise creation or deletion.
- No CSV history export.
- No persistent timer progress.
- No stable CSV exercise IDs across renames or category changes.
- Automatic backups require a homepage visit; restore requires stopping the app and replacing the database.

## Planned Improvements

- Background scheduled backups that run without opening the app.
- Additional automated tests.
- Previous strength performance displayed during workouts.
- Local image downloads.
- Stable exercise identifiers.
- In-app exercise creation.
- CSV export.