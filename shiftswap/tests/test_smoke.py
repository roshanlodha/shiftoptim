from pathlib import Path
from shiftoptim.ingest import load_preferences, build_schedule
from shiftoptim.optimizer import optimize
from shiftoptim.render import render_html
import shiftoptim.config as config

def test_load_preferences_normalization():
    # Keep track of the original config setting
    orig_ignore = config.IGNORE_WEIGHT
    try:
        config.IGNORE_WEIGHT = True
        residents = load_preferences(Path("data/preferences.csv"))
        
        # Roshan has MGH (weight 1), Morning (weight 0.5), days_weight 1.
        # Under IGNORE_WEIGHT = True, all three are overridden to 1.0.
        # Sum = 3.0. Normalized weights should be 1/3 each.
        roshan = residents["roshan lodha"]
        assert abs(roshan.loc_weight - 1/3) < 1e-6
        assert abs(roshan.type_weight - 1/3) < 1e-6
        assert abs(roshan.days_weight - 1/3) < 1e-6

        # Justin has BWH (weight 1), Swing (weight 1), days_weight 1.
        # Under IGNORE_WEIGHT = True, all three are 1.0.
        # Sum = 3.0. Normalized weights should be 1/3 each.
        if "justin yang" in residents:
            justin = residents["justin yang"]
            assert abs(justin.loc_weight - 1/3) < 1e-6
            assert abs(justin.type_weight - 1/3) < 1e-6
            assert abs(justin.days_weight - 1/3) < 1e-6
    finally:
        config.IGNORE_WEIGHT = orig_ignore

def test_end_to_end_pipeline():
    sched = build_schedule(Path("data/07_27_2026.ics"), Path("data/preferences.csv"))
    original_assignment = {n: set(uids) for n, uids in sched.assignment.items()}
    log = optimize(sched, max_swaps_per_person=-1, n_max=2)
    html = render_html(sched, log, original_assignment)
    assert html is not None
    assert "/*__INJECT_DATA__*/" not in html
    assert "class=\"md3-segmented-button" in html

def test_resident_metrics_payload():
    from shiftoptim.render import build_payload
    sched = build_schedule(Path("data/07_27_2026.ics"), Path("data/preferences.csv"))
    original_assignment = {n: set(uids) for n, uids in sched.assignment.items()}
    log = optimize(sched, max_swaps_per_person=-1, n_max=2)
    payload = build_payload(sched, log, original_assignment)
    
    roshan = payload["residents"]["roshan lodha"]
    assert "loc" in roshan
    assert "orig" in roshan["loc"]
    assert "opt" in roshan["loc"]
    assert "type" in roshan
    assert "streak" in roshan
    assert "happiness" in roshan
    
    # Check startHour and endHour are in shifts
    for suid, s in payload["shifts"].items():
        assert "startHour" in s
        assert "endHour" in s

    # Check partnerDelta is in swaps
    for name, swaps in payload["swaps"].items():
        for sw in swaps:
            assert "partnerDelta" in sw

def test_midnight_shift_end_hour():
    from shiftoptim.render import build_payload
    from datetime import datetime
    orig_start_date = config.START_DATE
    try:
        config.START_DATE = datetime(2026, 6, 29)
        sched = build_schedule(Path("data/07_27_2026.ics"), Path("data/preferences.csv"))
        original_assignment = {n: set(uids) for n, uids in sched.assignment.items()}
        payload = build_payload(sched, [], original_assignment)
        
        # Wendy has ad3ab74e-f5d9-4966-8f50-edb35c7806a0 (BWH Jr.  - Exe Jr 12p-12a - Memishian)
        # which starts at 12:00 PM on 2026-07-09 and ends at 12:00 AM on 2026-07-10.
        # Its endHour should be overridden to 24.0.
        target_uid = "ad3ab74e-f5d9-4966-8f50-edb35c7806a0"
        assert target_uid in payload["shifts"]
        s = payload["shifts"][target_uid]
        assert s["startHour"] == 12.0
        assert s["endHour"] == 24.0
    finally:
        config.START_DATE = orig_start_date


def test_work_streak_calculation():
    from datetime import date, timedelta
    from shiftoptim.feasibility import _streaks
    
    worked = {
        date(2026, 6, 22),
        date(2026, 6, 23),
        date(2026, 6, 24),
        date(2026, 6, 26),
    }
    runs = _streaks(worked)
    assert runs == [3, 1]

    # User's example: 5 worked, 3 off, 3 worked, 2 off.
    timeline_user = [date(2026, 6, 22) + timedelta(days=i) for i in range(13)]
    worked_user = {timeline_user[i] for i in [0, 1, 2, 3, 4, 8, 9, 10]}
    runs_user = _streaks(worked_user)
    assert runs_user == [5, 3]
    avg = sum(runs_user) / len(runs_user)
    assert avg == 4.0


def _make_shift(uid, owner, work_date, is_jeopardy=False, loc="MGH", stype="Morning"):
    """Helper: build a minimal Shift for unit tests."""
    from datetime import datetime, timedelta
    from dateutil import tz
    from shiftoptim.models import Shift
    LOCAL = tz.gettz("America/New_York")
    t_start = datetime(work_date.year, work_date.month, work_date.day, 7, 0, tzinfo=LOCAL)
    t_end = t_start + timedelta(hours=9)
    return Shift(
        uid=uid, owner=owner, t_start=t_start, t_end=t_end,
        loc=None if is_jeopardy else loc,
        type=None if is_jeopardy else stype,
        work_date=work_date, summary="test", is_jeopardy=is_jeopardy,
    )


def test_jeopardy_isolation_no_cross_type_edges():
    """Jeopardy shifts must never have trade-graph edges to/from regular shifts."""
    from datetime import date
    from shiftoptim.models import Resident, Schedule
    from shiftoptim.graph import build_trade_graph

    d1, d2 = date(2026, 7, 1), date(2026, 7, 2)
    s_reg = _make_shift("reg1", "alice", d1, is_jeopardy=False, loc="BWH")
    s_jep = _make_shift("jep1", "bob",   d2, is_jeopardy=True)

    alice = Resident("alice", "MGH", 0.5, "Morning", 0.5, 4, 0.0, frozenset())
    bob   = Resident("bob",   "MGH", 0.5, "Morning", 0.5, 4, 0.0, frozenset())

    sched = Schedule(
        assignment={"alice": {"reg1"}, "bob": {"jep1"}},
        shifts={"reg1": s_reg, "jep1": s_jep},
        residents={"alice": alice, "bob": bob},
    )

    orig_allow = config.ALLOW_JEOPARDY_SWAPS
    try:
        config.ALLOW_JEOPARDY_SWAPS = True
        G = build_trade_graph(sched)
        # No edge in either direction between a jeopardy and a regular shift.
        assert not G.has_edge("reg1", "jep1"), "regular→jeopardy edge should not exist"
        assert not G.has_edge("jep1", "reg1"), "jeopardy→regular edge should not exist"
    finally:
        config.ALLOW_JEOPARDY_SWAPS = orig_allow


def test_jeopardy_swaps_enabled_same_type():
    """Two jeopardy shifts owned by different residents CAN form edges."""
    from datetime import date
    from shiftoptim.models import Resident, Schedule
    from shiftoptim.graph import build_trade_graph

    d1, d2 = date(2026, 7, 1), date(2026, 7, 2)
    s1 = _make_shift("j1", "alice", d1, is_jeopardy=True)
    s2 = _make_shift("j2", "bob",   d2, is_jeopardy=True)

    # Both residents are indifferent — swapping is feasible and non-harmful.
    alice = Resident("alice", "ANY", 0.0, "ANY", 0.0, 4, 1.0, frozenset())
    bob   = Resident("bob",   "ANY", 0.0, "ANY", 0.0, 4, 1.0, frozenset())

    sched = Schedule(
        assignment={"alice": {"j1"}, "bob": {"j2"}},
        shifts={"j1": s1, "j2": s2},
        residents={"alice": alice, "bob": bob},
    )

    orig_allow = config.ALLOW_JEOPARDY_SWAPS
    try:
        config.ALLOW_JEOPARDY_SWAPS = True
        G = build_trade_graph(sched)
        # At least one direction should have an edge (swap is neutral/improving).
        has_edge = G.has_edge("j1", "j2") or G.has_edge("j2", "j1")
        assert has_edge, "same-type jeopardy swap should produce at least one edge"
    finally:
        config.ALLOW_JEOPARDY_SWAPS = orig_allow


def test_jeopardy_swaps_disabled_pins_shifts():
    """When ALLOW_JEOPARDY_SWAPS is False, jeopardy shifts have zero edges."""
    from datetime import date
    from shiftoptim.models import Resident, Schedule
    from shiftoptim.graph import build_trade_graph

    d1, d2 = date(2026, 7, 1), date(2026, 7, 2)
    s1 = _make_shift("j1", "alice", d1, is_jeopardy=True)
    s2 = _make_shift("j2", "bob",   d2, is_jeopardy=True)

    alice = Resident("alice", "ANY", 0.0, "ANY", 0.0, 4, 1.0, frozenset())
    bob   = Resident("bob",   "ANY", 0.0, "ANY", 0.0, 4, 1.0, frozenset())

    sched = Schedule(
        assignment={"alice": {"j1"}, "bob": {"j2"}},
        shifts={"j1": s1, "j2": s2},
        residents={"alice": alice, "bob": bob},
    )

    orig_allow = config.ALLOW_JEOPARDY_SWAPS
    try:
        config.ALLOW_JEOPARDY_SWAPS = False
        G = build_trade_graph(sched)
        assert not G.has_edge("j1", "j2"), "pinned jeopardy should have no outgoing edges"
        assert not G.has_edge("j2", "j1"), "pinned jeopardy should have no outgoing edges"
        # Verify zero total edges involving jeopardy nodes.
        assert G.degree("j1") == 0, "pinned jeopardy node j1 should be isolated"
        assert G.degree("j2") == 0, "pinned jeopardy node j2 should be isolated"
    finally:
        config.ALLOW_JEOPARDY_SWAPS = orig_allow


def test_start_date_filtering():
    from datetime import datetime
    orig_start_date = config.START_DATE
    try:
        # 1. Test when START_DATE is set to 2026-06-29.
        # Shift starting before June 29, 2026 should be filtered out.
        # Shift starting on or after June 29, 2026 should be kept.
        config.START_DATE = datetime(2026, 6, 29)
        sched = build_schedule(Path("data/07_27_2026.ics"), Path("data/preferences.csv"))
        for s in sched.shifts.values():
            assert s.t_start >= datetime(2026, 6, 29, tzinfo=s.t_start.tzinfo)

        # 2. Test when START_DATE is set to empty string (allow all dates)
        config.START_DATE = ""
        sched_all = build_schedule(Path("data/07_27_2026.ics"), Path("data/preferences.csv"))
        # Verify that shifts before June 29 are now included
        has_earlier = any(s.t_start < datetime(2026, 6, 29, tzinfo=s.t_start.tzinfo) for s in sched_all.shifts.values())
        assert has_earlier, "Should have shifts before June 29 when START_DATE is empty"
    finally:
        config.START_DATE = orig_start_date


def test_swap_cannot_extend_resident_past_last_shift_date():
    from datetime import date
    from shiftoptim.feasibility import is_valid_swap

    current = [
        _make_shift("early", "roshan", date(2026, 8, 1)),
        _make_shift("last", "roshan", date(2026, 8, 9)),
    ]
    proposed_after_last = [
        _make_shift("early", "roshan", date(2026, 8, 1)),
        _make_shift("future", "sara", date(2026, 8, 14)),
    ]
    proposed_on_last = [
        _make_shift("early", "roshan", date(2026, 8, 1)),
        _make_shift("same-last", "sara", date(2026, 8, 9)),
    ]

    assert not is_valid_swap(proposed_after_last, current, frozenset())
    assert is_valid_swap(proposed_on_last, current, frozenset())


def test_combined_ics_filters_to_preferences_and_maps_last_names(tmp_path):
    from datetime import datetime
    orig_start_date = config.START_DATE
    try:
        config.START_DATE = datetime(2026, 7, 27)
        prefs = tmp_path / "preferences.csv"
        prefs.write_text(
            "\n".join([
                "Timestamp,Name,Preferred Location,Preferred Shift Time,Days Needed Off (MM/DD/YYYY),Location Weight,Time Weight,Consecutive Days Worked,Streak Weight,Calendar iCS",
                "6/23/26 11:49,Roshan Lodha,MGH,Morning,,5,5,No preference,1,",
            ]),
            encoding="utf-8",
        )
        combined_ics = tmp_path / "combined.ics"
        combined_ics.write_text(
            """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
SUMMARY:BWH Jr.  - FF Jr 3p-12a - Lodha
UID:keep-lodha
DTSTART:20260727T150000
DTEND:20260728T000000
LOCATION:BWH Junior
END:VEVENT
BEGIN:VEVENT
SUMMARY:MGH Jr. - AC PGY2 7a-4p - Macrae
UID:skip-macrae
DTSTART:20260727T070000
DTEND:20260727T160000
LOCATION:MGH Junior
END:VEVENT
END:VCALENDAR
""",
            encoding="utf-8",
        )

        sched = build_schedule(combined_ics, prefs)
        assert set(sched.residents) == {"roshan lodha"}
        assert set(sched.shifts) == {"keep-lodha"}
        assert sched.assignment == {"roshan lodha": {"keep-lodha"}}
        assert sched.shifts["keep-lodha"].owner == "roshan lodha"
    finally:
        config.START_DATE = orig_start_date


def test_swap_limit_enforced_for_beneficiary():
    from collections import Counter
    sched = build_schedule(Path("data/07_27_2026.ics"), Path("data/preferences.csv"))
    log = optimize(sched, max_swaps_per_person=1, n_max=2)

    # Under the new participation cap every resident (any role) may appear in
    # at most max_swaps_per_person trades. A cap of 1 means no resident can
    # appear in more than one trade, so the beneficiary count is also <= 1.
    participation_counts: Counter = Counter()
    for res in log:
        for name in res.deltas:
            participation_counts[name] += 1

    for name, count in participation_counts.items():
        assert count <= 1, f"Resident {name} participates in {count} swaps, exceeds cap of 1"


def test_swap_sorting_by_max_happiness():
    from shiftoptim.render import build_payload
    sched = build_schedule(Path("data/07_27_2026.ics"), Path("data/preferences.csv"))
    original_assignment = {n: set(uids) for n, uids in sched.assignment.items()}
    # Let's get some log of swaps
    log = optimize(sched, max_swaps_per_person=-1, n_max=2)
    payload = build_payload(sched, log, original_assignment)
    
    # Check that for each resident, the swaps list is sorted by max(delta, partnerDelta) descending
    for name, swaps_list in payload["swaps"].items():
        if len(swaps_list) > 1:
            max_deltas = [max(sw["delta"], sw["partnerDelta"]) for sw in swaps_list]
            # Ensure it is sorted descending
            assert max_deltas == sorted(max_deltas, reverse=True), f"Swaps for {name} not sorted descending by max happiness gained: {max_deltas}"


def test_trades_are_independently_executable():
    """Every subset of the recommended trades, applied in any order, must be
    ACGME-legal and leave no participant's utility below their original value.
    This is the core independence guarantee of the new optimizer."""
    from itertools import combinations
    from shiftoptim.feasibility import is_valid_swap
    from shiftoptim.utility import utility

    sched = build_schedule(Path("data/07_27_2026.ics"), Path("data/preferences.csv"))
    orig_uids = {n: set(uids) for n, uids in sched.assignment.items()}
    orig_util = {
        n: utility(sched.shifts_of(n), sched.residents[n])
        for n in sched.assignment
    }

    log = optimize(sched, max_swaps_per_person=-1, n_max=2)

    if not log:
        return  # nothing to check

    # For every non-empty subset of the recommended trades, verify that each
    # affected resident's resulting shift set is legal and Pareto vs original.
    for size in range(1, len(log) + 1):
        for subset in combinations(log, size):
            # Reconstruct each participant's shift set after this subset.
            affected: dict[str, set[str]] = {}
            for trade in subset:
                for giver, u, v in trade.moves:
                    if giver not in affected:
                        affected[giver] = set(orig_uids[giver])
                    affected[giver].discard(u)
                    affected[giver].add(v)

            for name, uid_set in affected.items():
                r = sched.residents[name]
                orig_shifts = [sched.shifts[uid] for uid in orig_uids[name]]
                proposed = [sched.shifts[uid] for uid in uid_set]
                assert is_valid_swap(proposed, orig_shifts, r.days_off), (
                    f"Subset of size {size} makes {name}'s schedule illegal"
                )
                assert utility(proposed, r) >= orig_util[name] - 1e-9, (
                    f"Subset of size {size} lowers {name}'s utility"
                )


def test_time_diff_weight():
    """Verify that TIME_DIFF_WEIGHT correctly penalizes/rewards shift length differences."""
    from datetime import date, datetime, timedelta
    from dateutil import tz
    from shiftoptim import config
    from shiftoptim.models import Resident, Shift, Schedule
    from shiftoptim.utility import utility

    LOCAL = tz.gettz("America/New_York")
    
    # 1. Setup Resident and mock shifts
    r = Resident(
        name="alice",
        loc_pref="MGH",
        loc_weight=1.0,  # 100% location weight
        type_pref="ANY",
        type_weight=0.0,
        days_pref=4,
        days_weight=0.0,
        days_off=frozenset(),
        orig_hours=18.0
    )
    
    s1 = Shift(
        uid="s1", owner="alice",
        t_start=datetime(2026, 7, 1, 7, 0, tzinfo=LOCAL),
        t_end=datetime(2026, 7, 1, 16, 0, tzinfo=LOCAL),  # 9 hours
        loc="MGH", type="Morning", work_date=date(2026, 7, 1),
        summary="test", is_jeopardy=False
    )
    s2 = Shift(
        uid="s2", owner="alice",
        t_start=datetime(2026, 7, 2, 7, 0, tzinfo=LOCAL),
        t_end=datetime(2026, 7, 2, 17, 0, tzinfo=LOCAL),  # 10 hours
        loc="MGH", type="Morning", work_date=date(2026, 7, 2),
        summary="test", is_jeopardy=False
    )
    
    # Total hours: 19.0 (1.0 hour more than orig_hours of 18.0)
    shifts = [s1, s2]
    
    # Base utility should be 1.0 (since all locations match MGH, weights sum to 1.0)
    
    orig_weight = config.TIME_DIFF_WEIGHT
    try:
        # A. When weight is 0.0, utility has no penalty
        config.TIME_DIFF_WEIGHT = 0.0
        assert abs(utility(shifts, r) - 1.0) < 1e-9
        
        # B. When weight is 0.1, utility has a penalty of 0.1 * 1.0 = 0.1
        config.TIME_DIFF_WEIGHT = 0.1
        assert abs(utility(shifts, r) - 0.9) < 1e-9
        
        # C. Test reward when shifts are shorter (e.g. 17.0 hours total)
        s2_short = Shift(
            uid="s2", owner="alice",
            t_start=datetime(2026, 7, 2, 7, 0, tzinfo=LOCAL),
            t_end=datetime(2026, 7, 2, 15, 0, tzinfo=LOCAL),  # 8 hours (total 17.0 hours)
            loc="MGH", type="Morning", work_date=date(2026, 7, 2),
            summary="test", is_jeopardy=False
        )
        assert abs(utility([s1, s2_short], r) - 1.1) < 1e-9
        
        # 2. Verify that Schedule __post_init__ computes orig_hours correctly when Resident orig_hours is 0.0
        r_manual = Resident(
            name="alice",
            loc_pref="MGH",
            loc_weight=1.0,
            type_pref="ANY",
            type_weight=0.0,
            days_pref=4,
            days_weight=0.0,
            days_off=frozenset(),
            orig_hours=0.0
        )
        sched = Schedule(
            assignment={"alice": {"s1", "s2"}},
            shifts={"s1": s1, "s2": s2},
            residents={"alice": r_manual}
        )
        # s1 (9 hours) + s2 (10 hours) = 19.0 hours
        assert abs(r_manual.orig_hours - 19.0) < 1e-9

    finally:
        config.TIME_DIFF_WEIGHT = orig_weight


def test_complete_mode_pipeline():
    sched = build_schedule(Path("data/07_27_2026.ics"), Path("data/preferences.csv"))
    original_assignment = {n: set(uids) for n, uids in sched.assignment.items()}
    log = optimize(sched, max_swaps_per_person=-1, n_max=2, complete=True)
    html = render_html(sched, log, original_assignment)
    assert html is not None
