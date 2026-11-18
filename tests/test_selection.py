"""Tests for selection.py. Run from the project folder with:  pytest"""
from collections import Counter

import pytest

import config
import selection

# Same area sizes as the real sheets, so the tests behave like the real app.
STRETCH_COUNTS = {
    "Hips & Glutes": 33, "Thighs": 28, "Back": 12, "Balance": 8, "Shoulders": 7,
    "Lower legs & Feet": 6, "Neck": 6, "Whole body": 6, "Chest": 3, "Core": 3,
    "Arms & hands": 2,
}
STRENGTH_COUNTS = {
    "Core": 22, "Thighs": 21, "Hips & Glutes": 17, "Shoulders": 13, "Arms & hands": 12,
    "Back": 11, "Whole body": 10, "Chest": 8, "Lower legs & Feet": 5,
}


def build(ex_type, counts, start_id):
    """Make fake exercises. Every third one is a floor exercise."""
    exercises, next_id = [], start_id
    for area, count in counts.items():
        for n in range(count):
            exercises.append({
                "id": next_id, "type": ex_type, "focus": area,
                "name": f"{area} {ex_type} {n + 1}", "on_floor": int(n % 3 == 0),
            })
            next_id += 1
    return exercises


@pytest.fixture
def exercises():
    stretch = build("stretch", STRETCH_COUNTS, 1)
    return stretch + build("strength", STRENGTH_COUNTS, 1000)


def record_done(history, picks, when):
    """Pretend the picked exercises were completed at `when`."""
    for ex in picks:
        entry = history.get(ex["id"], {"times_done": 0, "last_done": None})
        history[ex["id"]] = {"times_done": entry["times_done"] + 1, "last_done": when}


def areas_of(items):
    return Counter(item["focus"] for item in items)


def exercises_of(plan):
    return [item["exercise"] for item in plan]


# --- Schedule ----------------------------------------------------------------


def test_day_types():
    assert [selection.day_type_for_weekday(d) for d in range(7)] == [
        "full", "flex", "full", "flex", "full", "rest", "rest",
    ]


# --- Splitting slots between areas ----------------------------------------------


def test_one_slot_per_area_when_slots_equal_areas(exercises):
    pool = [e for e in exercises if e["type"] == "stretch" and e["focus"] != "Balance"]
    picks = selection.pick_block(pool, 10, {}, selection.make_rng(1))
    assert len(picks) == 10
    assert set(areas_of(picks).values()) == {1}


def test_extra_slots_go_to_priority_areas_first(exercises):
    pool = [e for e in exercises if e["type"] == "stretch" and e["focus"] != "Balance"]
    picks = selection.pick_block(pool, 13, {}, selection.make_rng(1))
    counts = areas_of(picks)
    for area in config.PRIORITY_AREAS:
        assert counts[area] == 2
    assert sum(counts.values()) == 13
    assert all(counts[a] == 1 for a in counts if a not in config.PRIORITY_AREAS)


def test_flex_17_slots_split(exercises):
    # One each (10 areas), one extra each for the 3 priority areas, then
    # one extra for the 4 other areas that have gone longest without work.
    pool = [e for e in exercises if e["type"] == "stretch" and e["focus"] != "Balance"]
    history = {}
    # Make Neck, Core, Chest and Arms & hands the most recently worked areas...
    # so they should be last in line for an extra slot.
    for area in ("Neck", "Core", "Chest", "Arms & hands"):
        record_done(history, [e for e in pool if e["focus"] == area], "2026-11-13")
    counts = areas_of(selection.pick_block(pool, 17, history, selection.make_rng(3)))
    assert sum(counts.values()) == 17
    assert all(counts[a] == 2 for a in config.PRIORITY_AREAS)
    # ...and Shoulders, Lower legs & Feet and Whole body (never done) get the extras.
    assert counts["Shoulders"] == counts["Lower legs & Feet"] == counts["Whole body"] == 2
    # 3 priority + 3 never-done + 1 more of the 4 recently worked = 7 extras.
    assert sum(1 for c in counts.values() if c == 2) == 7


def test_strength_extra_slot_goes_to_priority_area_with_longest_gap(exercises):
    pool = [e for e in exercises if e["type"] == "strength"]  # 9 areas, 10 slots
    history = {}
    record_done(history, [e for e in pool if e["focus"] == "Back"], "2026-11-13")
    record_done(history, [e for e in pool if e["focus"] == "Thighs"], "2026-11-12")
    # Hips & Glutes was never done, so it has gone longest.
    counts = areas_of(selection.pick_block(pool, 10, history, selection.make_rng(5)))
    assert counts["Hips & Glutes"] == 2
    assert counts["Back"] == counts["Thighs"] == 1


def test_fewer_slots_than_areas_picks_the_longest_neglected(exercises):
    pool = [e for e in exercises if e["type"] == "stretch" and e["focus"] != "Balance"]
    history = {}
    recent = [a for a in STRETCH_COUNTS if a not in ("Balance", "Neck", "Chest")]
    for area in recent:
        record_done(history, [e for e in pool if e["focus"] == area], "2026-11-13")
    picks = selection.pick_block(pool, 2, history, selection.make_rng(2))
    assert {e["focus"] for e in picks} == {"Neck", "Chest"}


def test_small_area_never_gets_more_than_it_has(exercises):
    pool = [e for e in exercises if e["type"] == "stretch" and e["focus"] != "Balance"]
    for seed in range(20):
        picks = selection.pick_block(pool, 25, {}, selection.make_rng(seed))
        assert areas_of(picks)["Arms & hands"] <= 2
        assert len({e["id"] for e in picks}) == len(picks)


# --- Rotation --------------------------------------------------------------------


def test_neck_cycles_before_repeating_while_hips_keeps_new_ones(exercises):
    pool = [e for e in exercises if e["type"] == "stretch" and e["focus"] != "Balance"]
    history, rng = {}, selection.make_rng(7)
    neck_days, hip_days = [], []
    for day in range(6):
        picks = selection.pick_block(pool, 13, history, rng)  # Hips gets 2 a day
        record_done(history, picks, f"2026-11-{day + 1:02d}")
        neck_days.append([e["id"] for e in picks if e["focus"] == "Neck"])
        hip_days.extend(e["id"] for e in picks if e["focus"] == "Hips & Glutes")

    neck = [i for day in neck_days for i in day]
    assert len(neck) == 6 and len(set(neck)) == 6  # all 6 Neck exercises, no repeat
    assert len(hip_days) == 12 and len(set(hip_days)) == 12  # 12 different Hips exercises

    # Day 7: Neck starts over, Hips still serves exercises it has not shown yet.
    picks = selection.pick_block(pool, 13, history, rng)
    seen_hips = set(hip_days)
    assert all(e["id"] not in seen_hips for e in picks if e["focus"] == "Hips & Glutes")
    assert all(history[e["id"]]["times_done"] == 1 for e in picks if e["focus"] == "Neck")


def test_skipped_exercise_stays_at_the_front(exercises):
    pool = [e for e in exercises if e["focus"] == "Neck" and e["type"] == "stretch"]
    history = {}
    record_done(history, pool[:5], "2026-11-01")  # five of six done once
    for seed in range(10):
        # Skipping is not recorded, so the one never-done exercise comes up every time.
        pick = selection.pick_block(pool, 1, history, selection.make_rng(seed))
        assert pick[0]["id"] == pool[5]["id"]


def test_least_recently_done_is_picked_among_equals(exercises):
    pool = [e for e in exercises if e["focus"] == "Chest" and e["type"] == "stretch"]
    history = {}
    record_done(history, [pool[0]], "2026-11-03")
    record_done(history, [pool[1]], "2026-11-01")
    record_done(history, [pool[2]], "2026-11-02")
    pick = selection.pick_block(pool, 1, history, selection.make_rng(0))
    assert pick[0]["id"] == pool[1]["id"]  # all done once; this one is the oldest


# --- Ordering ----------------------------------------------------------------------


def test_standing_then_floor(exercises):
    pool = [e for e in exercises if e["type"] == "stretch" and e["focus"] != "Balance"]
    picks = selection.pick_block(pool, 10, {}, selection.make_rng(4))
    flags = [e["on_floor"] for e in selection.order_block(picks, selection.make_rng(4))]
    assert flags == sorted(flags)  # all 0s, then all 1s


def test_floor_then_standing(exercises):
    pool = [e for e in exercises if e["type"] == "strength"]
    picks = selection.pick_block(pool, 10, {}, selection.make_rng(4))
    flags = [e["on_floor"] for e in selection.order_block(picks, selection.make_rng(4), floor_first=True)]
    assert flags == sorted(flags, reverse=True)


def test_same_area_is_not_back_to_back(exercises):
    pool = [e for e in exercises if e["type"] == "stretch" and e["focus"] != "Balance"]
    for seed in range(30):
        rng = selection.make_rng(seed)
        picks = selection.pick_block(pool, 17, {}, rng)
        ordered = selection.order_block(picks, rng)
        floor_start = next((i for i, e in enumerate(ordered) if e["on_floor"]), len(ordered))
        for group in (ordered[:floor_start], ordered[floor_start:]):
            for a, b in zip(group, group[1:]):
                assert a["focus"] != b["focus"]


# --- Whole days ----------------------------------------------------------------------


def test_full_day_shape(exercises):
    plan = selection.plan_day("full", exercises, {}, selection.make_rng(11))
    assert len(plan) == 30
    assert [i["position"] for i in plan] == list(range(1, 31))
    assert [i["block"] for i in plan] == ["warmup"] * 10 + ["strength"] * 10 + ["cooldown"] * 10
    assert all(i["exercise"]["type"] == "strength" for i in plan if i["block"] == "strength")
    assert all(i["exercise"]["type"] == "stretch" for i in plan if i["block"] != "strength")
    assert all(i["exercise"]["focus"] != "Balance" for i in plan)


def test_full_day_has_20_different_stretches(exercises):
    for seed in range(20):
        plan = selection.plan_day("full", exercises, {}, selection.make_rng(seed))
        stretch_ids = [i["exercise"]["id"] for i in plan if i["block"] != "strength"]
        assert len(stretch_ids) == 20 and len(set(stretch_ids)) == 20


def test_full_day_floor_changes(exercises):
    # warmup standing -> floor, strength floor -> standing, cooldown standing -> floor:
    # the most you can need is 3 changes between standing and floor.
    for seed in range(20):
        plan = selection.plan_day("full", exercises, {}, selection.make_rng(seed))
        flags = [i["exercise"]["on_floor"] for i in plan]
        changes = sum(1 for a, b in zip(flags, flags[1:]) if a != b)
        assert changes <= 3


def test_flex_day_shape(exercises):
    plan = selection.plan_day("flex", exercises, {}, selection.make_rng(11))
    items = exercises_of(plan)
    assert len(plan) == 20 and len({e["id"] for e in items}) == 20
    assert {i["block"] for i in plan} == {"stretch"}
    assert all(e["type"] == "stretch" for e in items)
    assert areas_of(items)["Balance"] == 3
    flags = [e["on_floor"] for e in items]
    assert flags == sorted(flags)  # standing, then floor


def test_flex_day_split_of_the_other_17(exercises):
    plan = selection.plan_day("flex", exercises, {}, selection.make_rng(2))
    counts = areas_of(e for e in exercises_of(plan) if e["focus"] != "Balance")
    assert sum(counts.values()) == 17
    assert all(counts[a] == 2 for a in config.PRIORITY_AREAS)  # 10 areas + 7 extras


def test_rest_day_raises(exercises):
    with pytest.raises(ValueError):
        selection.plan_day("rest", exercises, {}, selection.make_rng(1))


def test_same_seed_same_plan(exercises):
    a = selection.plan_day("full", exercises, {}, selection.make_rng(99))
    b = selection.plan_day("full", exercises, {}, selection.make_rng(99))
    assert [i["exercise"]["id"] for i in a] == [i["exercise"]["id"] for i in b]


def test_small_library_does_not_crash():
    tiny = build("stretch", {"Neck": 2, "Back": 1, "Balance": 1}, 1) + build("strength", {"Core": 3}, 100)
    full = selection.plan_day("full", tiny, {}, selection.make_rng(1))
    flex = selection.plan_day("flex", tiny, {}, selection.make_rng(1))
    assert len(full) == 3 + 3  # 3 stretches split across two blocks (no repeats) + 3 strength
    assert len(flex) == 4  # 3 non-Balance + 1 Balance


# --- A month of workouts -------------------------------------------------------------


def test_everything_gets_used_before_anything_repeats(exercises):
    """Do Monday/Tuesday/Wednesday/Thursday/Friday for several weeks, completing everything."""
    history, rng = {}, selection.make_rng(21)
    for week in range(8):
        for weekday in range(5):
            day_type = selection.day_type_for_weekday(weekday)
            plan = selection.plan_day(day_type, exercises, history, rng)
            record_done(history, exercises_of(plan), f"2026-{week + 1:02d}-{weekday + 1:02d}")

    # Within each area, the number of times any two exercises were done never differs by more than 1,
    # so nothing is being starved and nothing is being repeated early.
    for ex_type in ("stretch", "strength"):
        for area in {e["focus"] for e in exercises if e["type"] == ex_type}:
            counts = [history.get(e["id"], {"times_done": 0})["times_done"]
                      for e in exercises if e["type"] == ex_type and e["focus"] == area]
            assert max(counts) - min(counts) <= 1, f"{ex_type} {area}: {sorted(counts)}"
