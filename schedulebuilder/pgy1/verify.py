"""Assert-based post-solve sanity checks for PGY-1 scheduler."""

from .config import SHIFTS, SHIFT_MIN_PER_HALF, SHIFT_MAX_PER_HALF, BASE_DEMAND, WED


def verify(result, shift_min_per_half=SHIFT_MIN_PER_HALF, shift_max_per_half=SHIFT_MAX_PER_HALF):
    solver = result["solver"]
    works = result["works"]
    dates = result["dates"]
    residents = result["residents"]
    active_halves = result["active_halves"]
    num_days = len(dates)

    # 1. Verify coverage constraints
    for d, date in enumerate(dates):
        weekday = date.weekday()
        for s in SHIFTS:
            count = sum(solver.Value(works[(r, d, s)]) for r in range(len(residents)))
            demand = BASE_DEMAND[s][weekday]
            assert count <= demand, f"{date} {SHIFTS[s]['name']} should have <= {demand} residents, got {count}"

    # 2. Verify single shift per day limit
    for r in range(len(residents)):
        for d in range(num_days):
            total = sum(solver.Value(works[(r, d, s)]) for s in SHIFTS)
            assert total <= 1, f"{residents[r]} works more than one shift on {dates[d]}"

    # 3. Verify ACGME weekly hours limit
    for r in range(len(residents)):
        for d in range(max(0, num_days - 6)):
            window = range(d, min(d + 7, num_days))
            ed_hours = sum(solver.Value(works[(r, i, s)]) * SHIFTS[s]["duration"] for i in window for s in SHIFTS)
            assert ed_hours <= 60, f"{residents[r]} exceeds 60h in window starting {dates[d]}"

    # 4. Verify Wednesday conference protection
    EM_PROPER_INTERNS = {
        "Brian", "Ashleigh", "Sara", "Emily", "Isabella", "Wendy",
        "Daem", "Bailey", "JP", "Roshan", "Mauranda", "Justin",
        "Jethel", "Clifford", "Andrea"
    }
    for d, date in enumerate(dates):
        if date.weekday() == WED:
            for r in range(len(residents)):
                if residents[r] in EM_PROPER_INTERNS:
                    for s, info in SHIFTS.items():
                        if solver.Value(works[(r, d, s)]):
                            start = info["start"]
                            end = info["end"]
                            if end < start:
                                end += 24
                            assert max(7, start) >= min(17, end), (
                                f"{residents[r]} scheduled on Wednesday Wed shift {info['name']} "
                                f"overlapping 7a-5p on {date}"
                            )

    # 5. Verify shift counts (min/max)
    for r, name in enumerate(residents):
        total = sum(solver.Value(works[(r, d, s)]) for d in range(num_days) for s in SHIFTS)
        required_min = shift_min_per_half * active_halves[name]
        required_max = shift_max_per_half * active_halves[name]
        assert total >= required_min, f"{name} has {total} shifts, below minimum {required_min}"
        assert total <= required_max, f"{name} has {total} shifts, above maximum {required_max}"

    print(f"[Block {result['block']}] PGY-1 verify() passed.")
