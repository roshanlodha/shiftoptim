from datetime import timedelta

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

# --- Sentinel values for "no preference" ---
NO_PREF = "ANY"

# --- Optimizer defaults (overridable via CLI) ---
DEFAULT_MAX_TOTAL_SWAPS = 20        # K: total shifts allowed to change hands
# ALLOW_MULTI_SWAPS: False = 1:1 trades only (cycle length 2);
#                    True  = also allow 3-way trades (cycle length 3, the cap).
ALLOW_MULTI_SWAPS = False

# Timezone: all .ics events use TZID=EDT with a fixed -0400 offset.
LOCAL_TZ = "America/New_York"