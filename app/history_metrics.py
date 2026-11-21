"""History dashboard metrics derived from saved workouts and activity logs."""
import calendar
from collections import Counter, defaultdict
from datetime import date, timedelta


def chart_bars(points):
    maximum = max((point["value"] for point in points if point["value"] is not None), default=0)
    return [
        {
            **point,
            "width": None if point["value"] is None else (
                100 * point["value"] / maximum if maximum else 0
            ),
            "display": "Not logged" if point["value"] is None else
                f'{point["value"]:,.2f}'.rstrip("0").rstrip("."),
        }
        for point in points
    ]


def adjacent_month(month, offset):
    year, index = divmod(month.year * 12 + month.month - 1 + offset, 12)
    return date(year, index + 1, 1) if 1 <= year <= 9999 else None


def build_dashboard(conn, sessions, activities, today, month, exercise_id=None):
    week_start = today - timedelta(days=today.weekday())
    active_dates = {
        session["date"] for session in sessions if (session["done_count"] or 0) > 0
    } | {activity["date"] for activity in activities}
    completed = [
        session for session in sessions
        if session["finished_at"] and (session["done_count"] or 0) > 0
    ]
    weeks = []
    for offset in range(7, -1, -1):
        start = week_start - timedelta(weeks=offset)
        end = min(start + timedelta(days=6), today)
        start_text, end_text = start.isoformat(), end.isoformat()
        cardio = [
            activity for activity in activities
            if start_text <= activity["date"] <= end_text
        ]
        weeks.append({
            "label": start.strftime("%b %d"),
            "start": start_text,
            "active_days": sum(start_text <= day <= end_text for day in active_dates),
            "workouts": sum(start_text <= session["date"] <= end_text for session in completed),
            "minutes": sum(activity["duration_minutes"] for activity in cardio),
            "miles": sum(activity["distance_miles"] for activity in cardio),
        })
    weekly_charts = [
        {
            "title": title, "unit": unit,
            "bars": chart_bars([
                {"label": week["label"], "value": week[field], "description": f'Week of {week["start"]}'}
                for week in weeks
            ]),
        }
        for field, title, unit in (
            ("workouts", "Completed workouts", "workouts"),
            ("minutes", "Cardio duration", "minutes"),
            ("miles", "Cardio distance", "miles"),
        )
    ]

    badges = defaultdict(Counter)
    for session in sessions:
        label = "Full" if session["day_type"] == "full" else "Flex"
        if not session["finished_at"]:
            label += " (open)"
        elif not (session["done_count"] or 0):
            label += " (skipped)"
        badges[session["date"]][(session["day_type"], label)] += 1
    for activity in activities:
        badges[activity["date"]][(activity["activity_type"], activity["activity_type"].capitalize())] += 1
    calendar_weeks = []
    for week in calendar.Calendar(firstweekday=0).monthdayscalendar(month.year, month.month):
        days = []
        for number in week:
            if not number:
                days.append(None)
                continue
            day = month.replace(day=number)
            day_badges = [
                {"kind": kind, "label": label, "count": count}
                for (kind, label), count in badges[day.isoformat()].items()
            ]
            days.append({
                "number": number, "date": day.isoformat(), "today": day == today,
                "badges": day_badges,
                "description": day.strftime("%B %d, %Y") + ": " + (
                    ", ".join(f'{badge["label"]} ({badge["count"]})' for badge in day_badges)
                    or "No records"
                ),
            })
        calendar_weeks.append(days)

    coverage_start = today - timedelta(days=29)
    coverage = conn.execute(
        """
        SELECT e.focus, COUNT(*) AS completed
        FROM session_items AS si
        JOIN sessions AS s ON s.id = si.session_id
        JOIN exercises AS e ON e.id = si.exercise_id
        WHERE si.status = 'done' AND s.date BETWEEN ? AND ?
        GROUP BY e.focus ORDER BY completed DESC, e.focus
        """,
        (coverage_start.isoformat(), today.isoformat()),
    ).fetchall()
    area_counts = {row["focus"]: row["completed"] for row in coverage}
    for row in conn.execute("SELECT DISTINCT focus FROM exercises WHERE active = 1"):
        area_counts.setdefault(row["focus"], 0)
    body_bars = chart_bars([
        {"label": focus, "value": count, "description": focus}
        for focus, count in sorted(area_counts.items(), key=lambda item: (-item[1], item[0]))
    ])

    choices = conn.execute(
        """
        SELECT DISTINCT e.id, e.name, e.active
        FROM exercises AS e
        JOIN session_items AS si ON si.exercise_id = e.id
        JOIN strength_sets AS ss ON ss.session_item_id = si.id
        WHERE si.status = 'done' AND (ss.weight IS NOT NULL OR ss.reps IS NOT NULL)
        ORDER BY e.name, e.id
        """
    ).fetchall()
    if exercise_id is None and choices:
        exercise_id = choices[0]["id"]
    if exercise_id is not None and not any(row["id"] == exercise_id for row in choices):
        raise ValueError("Choose an exercise with logged sets from a completed exercise.")
    points = []
    if exercise_id is not None:
        points = conn.execute(
            """
            SELECT s.id, s.date, MAX(ss.weight) AS weight, SUM(ss.reps) AS reps
            FROM sessions AS s
            JOIN session_items AS si ON si.session_id = s.id
            JOIN strength_sets AS ss ON ss.session_item_id = si.id
            WHERE si.exercise_id = ? AND si.status = 'done'
            GROUP BY s.id
            ORDER BY s.date DESC, s.started_at DESC, s.id DESC
            LIMIT 12
            """,
            (exercise_id,),
        ).fetchall()[::-1]
    strength_charts = [
        {
            "title": title, "unit": unit,
            "bars": chart_bars([
                {
                    "label": point["date"], "value": point[field], "session_id": point["id"],
                    "description": f'{point["date"]}, session {point["id"]}',
                }
                for point in points
            ]),
        }
        for field, title, unit in (
            ("weight", "Heaviest logged weight", "lb"),
            ("reps", "Total logged reps", "reps"),
        )
    ]
    return {
        "week": weeks[-1], "week_start": week_start.isoformat(), "today": today.isoformat(),
        "weekly_charts": weekly_charts, "calendar_weeks": calendar_weeks,
        "month": month.isoformat()[:7], "month_label": month.strftime("%B %Y"),
        "previous_month": adjacent_month(month, -1), "next_month": adjacent_month(month, 1),
        "body_bars": body_bars, "body_completed": sum(area_counts.values()),
        "coverage_start": coverage_start.isoformat(),
        "strength_choices": choices, "exercise_id": exercise_id,
        "strength_charts": strength_charts,
    }
