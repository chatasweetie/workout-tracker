from datetime import datetime

from flask import abort, redirect, render_template, request, url_for


def register_review_routes(app, get_db):
    @app.get("/reviews")
    def exercise_reviews():
        status = request.args.get("status", "open")

        if status not in ("open", "resolved"):
            abort(400, description="Invalid review filter.")

        condition = (
            "r.resolved_at IS NULL"
            if status == "open"
            else "r.resolved_at IS NOT NULL"
        )

        reviews = get_db().execute(
            f"""
            SELECT
                r.*,
                e.name,
                e.type,
                e.focus,
                e.active
            FROM exercise_review_notes AS r
            JOIN exercises AS e ON e.id = r.exercise_id
            WHERE {condition}
            ORDER BY r.created_at DESC, r.id DESC
            """
        ).fetchall()

        return render_template(
            "reviews.html",
            reviews=reviews,
            status=status,
        )

    @app.post("/api/items/<int:item_id>/reviews")
    def create_exercise_review(item_id):
        conn = get_db()

        item = conn.execute(
            """
            SELECT id, exercise_id
            FROM session_items
            WHERE id = ?
            """,
            (item_id,),
        ).fetchone()

        if item is None:
            return {"error": "Exercise occurrence not found."}, 404

        data = request.get_json()

        if not isinstance(data, dict):
            return {"error": "Expected a JSON object."}, 400

        note = data.get("note")

        if not isinstance(note, str) or not note.strip():
            return {"error": "Enter a note before saving."}, 400

        note = note.strip()

        if len(note) > 5000:
            return {"error": "Notes must be 5,000 characters or fewer."}, 400

        created_at = datetime.now().isoformat(timespec="seconds")

        with conn:
            cursor = conn.execute(
                """
                INSERT INTO exercise_review_notes
                    (exercise_id, session_item_id, note, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    item["exercise_id"],
                    item_id,
                    note,
                    created_at,
                ),
            )

        return {
            "ok": True,
            "review": {
                "id": cursor.lastrowid,
                "note": note,
                "created_at": created_at,
            },
        }, 201

    @app.post("/reviews/<int:review_id>/resolve")
    def resolve_exercise_review(review_id):
        conn = get_db()

        review = conn.execute(
            "SELECT id FROM exercise_review_notes WHERE id = ?",
            (review_id,),
        ).fetchone()

        if review is None:
            abort(404, description="Review note not found.")

        with conn:
            conn.execute(
                """
                UPDATE exercise_review_notes
                SET resolved_at = ?
                WHERE id = ?
                  AND resolved_at IS NULL
                """,
                (
                    datetime.now().isoformat(timespec="seconds"),
                    review_id,
                ),
            )

        return redirect(url_for("exercise_reviews", status="open"))