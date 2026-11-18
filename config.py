"""Settings you might want to change later. Nothing here touches the database."""

# Python's weekday numbers: Monday is 0 ... Sunday is 6.
# "full"  = 10 stretches, 10 strength, 10 different stretches
# "flex"  = 20 stretches including Balance
# Days not listed here (Saturday, Sunday) are rest days.
DAY_TYPE_BY_WEEKDAY = {
    0: "full",  # Monday
    1: "flex",  # Tuesday
    2: "full",  # Wednesday
    3: "flex",  # Thursday
    4: "full",  # Friday
}

BLOCK_SIZE = 10  # slots in each block of a full day
FLEX_STRETCHES = 20  # stretches on a flex day, Balance included
FLEX_BALANCE = 3  # how many of those are Balance

BALANCE_AREA = "Balance"  # only used on flex days

# When a block has more slots than body areas, these areas get the extra slots first.
PRIORITY_AREAS = ("Hips & Glutes", "Thighs", "Back")

WEIGHT_UNIT = "lb"
