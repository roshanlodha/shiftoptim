"""Assert-based post-solve sanity checks."""

from .config import EXTRA_SHIFT, SHIFT_MIN_PER_HALF, SHIFTS


def verify(result, shift_min_per_half=SHIFT_MIN_PER_HALF):
    solver = result["solver"]
    works = result["works"]
    dates = result["dates"]
    residents = result["residents"]
    active_halves = result["active_halves"]
    num_days = len(dates)

    for d, date in enumerate(dates):
        weekday = date.weekday()
        for s, info in SHIFTS.items():
            count = sum(solver.Value(works[(r, d, s)]) for r in range(len(residents)))
            if weekday in info["required_weekdays"]:
                assert count == 1, f"{date} {info['name']} should have exactly 1 resident, got {count}"
            elif s == EXTRA_SHIFT:
                assert count <= 1, f"{date} relief shift should have at most 1 resident, got {count}"
            else:
                assert count == 0, f"{date} {info['name']} should be unstaffed, got {count}"

    for r in range(len(residents)):
        for d in range(num_days):
            total = sum(solver.Value(works[(r, d, s)]) for s in SHIFTS)
            assert total <= 1, f"{residents[r]} works more than one shift on {dates[d]}"

    for r in range(len(residents)):
        for d in range(max(0, num_days - 6)):
            window = range(d, min(d + 7, num_days))
            ed_hours = sum(solver.Value(works[(r, i, s)]) * SHIFTS[s]["duration"] for i in window for s in SHIFTS)
            assert ed_hours <= 60, f"{residents[r]} exceeds 60h in window starting {dates[d]}"

    for r, name in enumerate(residents):
        total = sum(solver.Value(works[(r, d, s)]) for d in range(num_days) for s in SHIFTS)
        required_min = shift_min_per_half * active_halves[name]
        assert total >= required_min, f"{name} has {total} shifts, below minimum {required_min}"

    print(f"[Block {result['block']}] verify() passed.")
