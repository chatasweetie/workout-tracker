"""Decide which exercises to do today.

Everything here is a plain function: exercises and history go in, an ordered
workout comes out. There is no database, no Flask and no clock, so it can be
tested on its own.

An exercise is a dict (or a sqlite3.Row) with at least:
    id, type, focus, name, on_floor

History is a dict keyed by exercise id:
    {12: {"times_done": 3, "last_done": "2026-11-13T07:30:00"}, ...}
An exercise missing from it has never been done. Skipped exercises are simply
not recorded, which is why a skipped exercise stays at the front of its queue.
"""
import random

import config


def day_type_for_weekday(weekday):
    """0 = Monday ... 6 = Sunday. Returns "full", "flex", or "rest"."""
    return config.DAY_TYPE_BY_WEEKDAY.get(weekday, "rest")


# --- Choosing how many exercises each body area gets ---------------------------


def allocate_slots(order, capacity, slots, priority=config.PRIORITY_AREAS):
    """Split `slots` between body areas.

    order:    areas sorted by longest time since last worked, first
    capacity: {area: how many exercises it still has available}
    Returns {area: number of slots}.

    Every area gets one slot. If there are more slots than areas, the extras
    go one at a time to the priority areas first, then to everything else,
    each in `order`, round and round until the slots run out. No area ever gets
    more slots than it has exercises.
    """
    if slots <= len(order):
        return {area: 1 for area in order[:slots]}

    allocation = {area: 1 for area in order}
    remaining = slots - len(order)
    hand_out_order = [a for a in order if a in priority] + [a for a in order if a not in priority]

    while remaining > 0:
        gave_any = False
        for area in hand_out_order:
            if remaining == 0:
                break
            if allocation[area] < capacity[area]:
                allocation[area] += 1
                remaining -= 1
                gave_any = True
        if not gave_any:  # every area is out of exercises
            break
    return allocation


# --- Picking exercises -----------------------------------------------------------


def _history_for(history, exercise):
    return history.get(exercise["id"], {"times_done": 0, "last_done": None})


def pick_block(pool, slots, history, rng, exclude_ids=()):
    """Pick up to `slots` exercises from `pool`.

    1. Work out how many slots each body area gets (allocate_slots).
    2. Inside an area, take the exercises done the fewest times first, then the
       ones done longest ago (never done counts as longest), then random.
    """
    excluded = set(exclude_ids)
    by_area = {}
    for ex in pool:
        if ex["id"] not in excluded:
            by_area.setdefault(ex["focus"], []).append(ex)

    # How long since each area was last worked, looking at the whole pool.
    last_worked = {}
    for ex in pool:
        done = _history_for(history, ex)["last_done"] or ""
        last_worked[ex["focus"]] = max(last_worked.get(ex["focus"], ""), done)

    # Longest gap first. "" (never done) sorts before any date. Sorted names
    # first, so the same seed always gives the same result.
    areas = sorted(by_area)
    tie_break = {area: rng.random() for area in areas}
    order = sorted(areas, key=lambda a: (last_worked.get(a, ""), tie_break[a]))

    capacity = {area: len(by_area[area]) for area in areas}
    allocation = allocate_slots(order, capacity, slots)

    picks = []
    for area in order:
        count = allocation.get(area, 0)
        if count == 0:
            continue
        ranked = sorted(
            by_area[area],
            key=lambda ex: (
                _history_for(history, ex)["times_done"],
                _history_for(history, ex)["last_done"] or "",
                rng.random(),
            ),
        )
        picks.extend(ranked[:count])
    return picks


# --- Ordering a block ------------------------------------------------------------


def _spread_by_area(items, rng, previous_area=None):
    """Reorder so the same body area is not back to back, when that is possible."""
    buckets = {}
    for ex in items:
        buckets.setdefault(ex["focus"], []).append(ex)
    for area in sorted(buckets):
        rng.shuffle(buckets[area])

    result = []
    last = previous_area
    while any(buckets.values()):
        options = [a for a in sorted(buckets) if buckets[a] and a != last]
        if not options:  # only the area we just used is left
            options = [a for a in sorted(buckets) if buckets[a]]
        most = max(len(buckets[a]) for a in options)
        area = rng.choice([a for a in options if len(buckets[a]) == most])
        result.append(buckets[area].pop())
        last = area
    return result


def order_block(picks, rng, floor_first=False, previous_area=None):
    """Group standing and floor exercises so you get up and down as little as possible.

    Standing first by default; floor_first=True reverses it. Inside each group
    the same area is kept apart.
    """
    standing = [ex for ex in picks if not ex["on_floor"]]
    floor = [ex for ex in picks if ex["on_floor"]]
    groups = [floor, standing] if floor_first else [standing, floor]

    ordered = []
    last = previous_area
    for group in groups:
        arranged = _spread_by_area(group, rng, last)
        ordered.extend(arranged)
        if arranged:
            last = arranged[-1]["focus"]
    return ordered


# --- Building the day ------------------------------------------------------------


def plan_day(day_type, exercises, history, rng):
    """Return today's workout as an ordered list:
        [{"position": 1, "block": "warmup", "exercise": {...}}, ...]

    full:  warmup (10 stretches, standing then floor)
           strength (10, floor then standing)
           cooldown (10 more stretches, standing then floor)
    flex:  stretch (20 stretches: 3 Balance, the rest from other areas)
    Stretches on a full day never include Balance, and the cooldown never
    repeats a warmup exercise.
    """
    stretches = [e for e in exercises if e["type"] == "stretch" and e["focus"] != config.BALANCE_AREA]
    balance = [e for e in exercises if e["type"] == "stretch" and e["focus"] == config.BALANCE_AREA]
    strength = [e for e in exercises if e["type"] == "strength" and e["focus"] != config.BALANCE_AREA]

    if day_type == "full":
        warmup = pick_block(stretches, config.BLOCK_SIZE, history, rng)
        cooldown = pick_block(stretches, config.BLOCK_SIZE, history, rng,
                              exclude_ids={e["id"] for e in warmup})
        lifting = pick_block(strength, config.BLOCK_SIZE, history, rng)

        blocks = [
            ("warmup", order_block(warmup, rng)),
            ("strength", order_block(lifting, rng, floor_first=True)),
            ("cooldown", order_block(cooldown, rng)),
        ]
    elif day_type == "flex":
        balance_picks = pick_block(balance, config.FLEX_BALANCE, history, rng)
        others = pick_block(stretches, config.FLEX_STRETCHES - len(balance_picks), history, rng)
        blocks = [("stretch", order_block(balance_picks + others, rng))]
    else:
        raise ValueError(f"No workout for day type {day_type!r}")

    plan = []
    for block, items in blocks:
        for ex in items:
            plan.append({"position": len(plan) + 1, "block": block, "exercise": ex})
    return plan


def make_rng(seed=None):
    """A random generator. Pass a number to get the same workout every time (for tests)."""
    return random.Random(seed)
