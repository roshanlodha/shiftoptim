from datetime import datetime, timedelta

# --- ACGME hard constraints ---
MIN_REST = timedelta(hours=12)      # min gap between consecutive shifts
MAX_CONSECUTIVE_DAYS = 6            # max length of a working streak

# --- Time-of-day classification, keyed on LOCAL start hour [0..23] ---
# Morning:   start hour in [4, 11)
# Swing:     start hour in [11, 18)
# Overnight: start hour in [18, 24) or [0, 4)
MORNING_START, SWING_START, OVERNIGHT_START = 4, 11, 18

# --- Streak preference normalization (max possible |len - target|) ---
# target in [3,6], streak length in [1,6]  => max deviation = 5
STREAK_BETA = 5.0

# --- Location parsing: first N chars of ICS LOCATION field ---
LOC_PREFIX_LEN = 3                  # "MGH Junior" -> "MGH"
VALID_LOCATIONS = {"MGH", "BWH"}

# --- Shifts containing any of these keywords (case-insensitive) in the
#     SUMMARY are "jeopardy"/backup shifts. They ARE swappable like any other
#     shift, but they are location-agnostic and time-agnostic: they carry
#     loc=None and type=None, so they neither help nor hurt the location and
#     time-of-day scores. They DO count as a worked day toward the streak. ---
JEOPARDY_KEYWORDS = ("jeopardy", "backup")

# --- Jeopardy/backup shift swap behavior ---
# True  = jeopardy shifts can be swapped, but ONLY with other jeopardy shifts.
# False = jeopardy shifts are pinned and never participate in any trade.
ALLOW_JEOPARDY_SWAPS = True

# --- Sentinel values for "no preference" ---
NO_PREF = "ANY"

# --- Optimizer defaults (overridable via CLI) ---
DEFAULT_MAX_SWAPS_PER_PERSON = -1    # max swaps any single person can make;
                                     # -1 = unlimited.  Ensures equity.
# ALLOW_MULTI_SWAPS: False = 1:1 trades only (cycle length 2);
#                    True  = also allow 3-way trades (cycle length 3, the cap).
ALLOW_MULTI_SWAPS = False

# Timezone: all .ics events use TZID=EDT with a fixed -0400 offset.
LOCAL_TZ = "America/New_York"

# Ignore user weights in CSV preference (True = ignore weights and normalize them to 1.0)
IGNORE_WEIGHT = False

# --- Start Date Filter ---
# Empty string corresponds to allowing all dates, otherwise should be a datetime object.
# Before this date, all scheduled shifts should be tossed out.
START_DATE = datetime(2026, 7, 27)

# --- Shift Length Swap Penalty Weight ---
# Penalty for swapping a shift with a longer shift: (curr utility - (weight * additional_shift_time)).
# Set to 0.0 to restore the existing behavior.
TIME_DIFF_WEIGHT = 0.02