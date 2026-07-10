"""One-shot (idempotent) seed script for the web app database.

Populates:
  - admin user (jaba/thehutt) and one resident login per PGY-4 resident
  - the 26 half-blocks of AY 2026-2027 with dates, extracted from
    data/AY 2026-2027 Block Schedule (Final) - PGY-4.csv
  - each resident's rotation for every half-block (from the same CSV)
  - jeopardy assignments per half-block
  - time-off requests carried over from config.ini's [time off] section
  - history_baseline counts carried over from data/history.json

Run with: python -m webapp.seed
"""

import configparser
import json
import os

from werkzeug.security import generate_password_hash

from . import db as dbmod

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_INI = os.path.join(REPO_ROOT, "config.ini")
HISTORY_JSON = os.path.join(REPO_ROOT, "data", "history.json")

PGY4_LEVEL = 4
DEFAULT_RESIDENT_PASSWORD = "changeme"

# R-code -> (last_name, full_name), in CSV row order (R1..R15).
ROSTER = [
    ("D'Amore", "Aaron D'Amore"),
    ("Raynor", "Abigail (Abby) Raynor"),
    ("Qi", "Xin Qi"),
    ("Hurwitz", "Jacob (Jake) Hurwitz"),
    ("Traboulsi", "Abd Al-Rahman Traboulsi"),
    ("Eappen", "Brendan Eappen"),
    ("Okonkwo", "Nneoma Okonkwo"),
    ("Anyaso", "Chiaka (Jackie) Anyaso"),
    ("Fonjungo", "Ashfott (Ash) Fonjungo"),
    ("Botticelli", "Brittany Botticelli"),
    ("Menzies", "Julia Menzies"),
    ("Tamirian", "Richard (Rich) Tamirian"),
    ("Chandran", "Kira Chandran"),
    ("Shoaib", "Muhammad Shoaib"),
    ("Malits", "Julia Malits"),
]

# 26 half-blocks in order (block_number, half, start_date, end_date), ISO dates.
# Extracted from the CSV header rows; the academic year starts 6/29/2026 and
# rolls into 2027 at block 7b (12/28/2026-1/10/2027).
HALF_BLOCKS = [
    (1, "a", "2026-06-29", "2026-07-12"),
    (1, "b", "2026-07-13", "2026-07-26"),
    (2, "a", "2026-07-27", "2026-08-09"),
    (2, "b", "2026-08-10", "2026-08-23"),
    (3, "a", "2026-08-24", "2026-09-06"),
    (3, "b", "2026-09-07", "2026-09-20"),
    (4, "a", "2026-09-21", "2026-10-04"),
    (4, "b", "2026-10-05", "2026-10-18"),
    (5, "a", "2026-10-19", "2026-11-01"),
    (5, "b", "2026-11-02", "2026-11-15"),
    (6, "a", "2026-11-16", "2026-11-29"),
    (6, "b", "2026-11-30", "2026-12-13"),
    (7, "a", "2026-12-14", "2026-12-27"),
    (7, "b", "2026-12-28", "2027-01-10"),
    (8, "a", "2027-01-11", "2027-01-24"),
    (8, "b", "2027-01-25", "2027-02-07"),
    (9, "a", "2027-02-08", "2027-02-21"),
    (9, "b", "2027-02-22", "2027-03-07"),
    (10, "a", "2027-03-08", "2027-03-21"),
    (10, "b", "2027-03-22", "2027-04-04"),
    (11, "a", "2027-04-05", "2027-04-18"),
    (11, "b", "2027-04-19", "2027-05-02"),
    (12, "a", "2027-05-03", "2027-05-16"),
    (12, "b", "2027-05-17", "2027-05-30"),
    (13, "a", "2027-05-31", "2027-06-13"),
    (13, "b", "2027-06-14", "2027-06-27"),
]

# Rotation per resident (row order matches ROSTER) for each of the 26 halves
# in HALF_BLOCKS order. Extracted verbatim from the block schedule CSV.
ROTATIONS = [
    ["MGB", "MGB", "NWH", "NWH", "Vacation", "Flex", "MGB", "MGB", "MGB", "MGB Nights",
     "Elective/LTD", "MGB", "MGB", "Elective", "Elective", "Elective/LTD", "MGB", "MGB",
     "MGB", "MGB", "Teaching", "Teaching", "MGB", "Vacation", "Flex", "MGB"],
    ["MGB", "MGB", "MGB Nights", "Vacation", "NWH", "NWH", "MGB", "Elective", "Elective",
     "MGB", "MGB", "MGB", "Teaching", "Teaching", "Elective/LTD", "Elective/LTD", "Flex",
     "MGB", "MGB", "Vacation", "Flex", "MGB", "MGB", "MGB", "MGB", "MGB"],
    ["Teaching", "Teaching", "MGB", "MGB", "MGB", "MGB Nights", "Vacation", "MGB",
     "Elective/LTD", "Elective/LTD", "MGB", "MGB", "MGB", "MGB", "MGB", "Flex", "Elective",
     "Elective", "MGB", "MGB", "MGB", "MGB", "Vacation", "Flex", "NWH", "NWH"],
    ["Teaching", "Teaching", "Elective", "Elective", "MGB", "MGB", "MGB", "Vacation",
     "Flex", "MGB", "MGB", "MGB", "MGB", "MGB", "MGB", "MGB", "MGB", "MGB", "Vacation",
     "Flex", "NWH", "NWH", "MGB", "MGB Nights", "Elective/LTD", "Elective/LTD"],
    ["MGB", "MGB", "MGB", "MGB", "MGB", "Elective", "Elective", "Flex", "MGB", "MGB",
     "MGB Nights", "NWH", "NWH", "MGB", "MGB", "Vacation", "Flex", "MGB", "Elective/LTD",
     "Elective/LTD", "MGB", "Teaching", "Teaching", "MGB", "MGB", "Vacation"],
    ["Elective", "Elective", "Teaching", "Teaching", "Flex", "MGB", "MGB", "MGB",
     "MGB Nights", "Vacation", "MGB", "MGB", "MGB", "MGB", "Vacation", "MGB",
     "Elective/LTD", "Elective/LTD", "NWH", "NWH", "MGB", "MGB", "MGB", "MGB", "Flex", "MGB"],
    ["Elective/LTD", "Elective/LTD", "MGB", "MGB", "MGB Nights", "Vacation", "NWH", "NWH",
     "MGB", "MGB", "MGB", "MGB", "Elective", "Elective", "Flex", "Flex", "MGB", "MGB",
     "Teaching", "Teaching", "MGB", "MGB", "MGB", "Vacation", "MGB", "MGB"],
    ["MGB", "MGB", "MGB", "MGB", "Elective/LTD", "Elective/LTD", "MGB", "MGB", "NWH",
     "NWH", "Vacation", "Flex", "MGB", "MGB", "MGB", "MGB", "Elective", "Elective", "Flex",
     "MGB", "MGB", "MGB", "MGB Nights", "Teaching", "Teaching", "Vacation"],
    ["NWH", "NWH", "MGB", "MGB", "MGB", "MGB", "MGB", "MGB Nights", "Vacation", "MGB",
     "Elective", "Elective", "Flex", "MGB", "MGB", "MGB", "Teaching", "Teaching", "MGB",
     "Vacation", "Flex", "MGB", "Elective/LTD", "Elective/LTD", "MGB", "MGB"],
    ["MGB", "Flex", "MGB", "Flex", "Teaching", "Teaching", "Elective", "Elective/LTD",
     "MGB", "MGB", "Elective/LTD", "Elective", "MGB", "MGB", "MGB", "MGB", "MGB",
     "MGB Nights", "Vacation", "MGB", "MGB", "MGB", "NWH", "NWH", "Vacation", "MGB"],
    ["MGB", "Elective", "Elective", "MGB", "MGB", "MGB", "MGB Nights", "Vacation",
     "Teaching", "Teaching", "NWH", "NWH", "MGB", "Flex", "Elective/LTD", "Elective/LTD",
     "MGB", "MGB", "MGB", "MGB", "Vacation", "Flex", "MGB", "MGB", "MGB", "MGB"],
    ["MGB", "MGB", "MGB", "Vacation", "Elective", "Elective", "Flex", "MGB", "MGB", "MGB",
     "MGB", "MGB Nights", "NWH", "NWH", "MGB", "MGB", "MGB", "MGB", "Vacation", "Flex",
     "Elective/LTD", "Elective/LTD", "MGB", "MGB", "Teaching", "Teaching"],
    ["Vacation", "MGB", "Elective/LTD", "Elective/LTD", "MGB", "MGB", "MGB", "MGB",
     "Elective", "Elective", "Teaching", "Teaching", "Flex", "MGB", "NWH", "NWH", "MGB",
     "MGB", "MGB", "MGB", "MGB", "MGB Nights", "Vacation", "MGB", "MGB", "Flex"],
    ["MGB", "MGB", "MGB", "MGB", "MGB", "MGB", "Elective/LTD", "MGB", "MGB", "Vacation",
     "Flex", "Elective/LTD", "MGB", "MGB", "Teaching", "Teaching", "NWH", "NWH",
     "MGB Nights", "Vacation", "Elective", "Elective", "Flex", "MGB", "MGB", "MGB"],
    ["Flex", "Flex", "MGB", "MGB Nights", "Vacation", "MGB", "Teaching", "Teaching",
     "MGB", "MGB", "MGB", "MGB", "Elective/LTD", "Elective/LTD", "MGB", "MGB", "Vacation",
     "MGB", "MGB", "MGB", "NWH", "NWH", "MGB", "MGB", "Elective", "Elective"],
]

# Jeopardy R-codes per half-block, in HALF_BLOCKS order. Some halves list two
# residents (e.g. "R3/R4"); ponytail: we only record the first as the FK
# target since jeopardy is informational, not solver input. Upgrade path:
# switch jeopardy_resident_id to a join table if a second on-call is ever needed.
JEOPARDY = [
    "R3", "R3", "R6", "R6", "R10", "R10", "R15", "R15", "R11", "R11", "R13", "R13",
    "R2", "R2", "R14", "R14", "R9", "R9", "R7", "R7", "R1", "R1", "R5", "R8", "R8", "R12",
]


def _r_index(code):
    return int(code[1:]) - 1  # "R3" -> 2


def _parse_date(text):
    month, day, year = (int(x) for x in text.strip().split("/"))
    return f"{year:04d}-{month:02d}-{day:02d}"


def _parse_date_range(text):
    if "-" in text:
        start_text, end_text = text.split("-", 1)
        return _parse_date(start_text), _parse_date(end_text)
    d = _parse_date(text)
    return d, d


def seed(conn):
    dbmod.init_db(conn)

    resident_ids = {}
    for last_name, full_name in ROSTER:
        cur = conn.execute(
            "INSERT INTO residents (full_name, last_name, pgy_level) VALUES (?, ?, ?) "
            "ON CONFLICT (last_name, pgy_level) DO UPDATE SET full_name = excluded.full_name "
            "RETURNING id",
            (full_name, last_name, PGY4_LEVEL),
        )
        resident_ids[last_name] = cur.fetchone()[0]

    _seed_users(conn, resident_ids)
    half_block_ids = _seed_half_blocks_and_rotations(conn, resident_ids)
    _seed_jeopardy(conn, half_block_ids, resident_ids)
    _seed_time_off(conn, resident_ids)
    _seed_history_baseline(conn, resident_ids)

    conn.commit()


def _seed_users(conn, resident_ids):
    conn.execute(
        "INSERT INTO users (username, password_hash, role, resident_id) VALUES (?, ?, 'admin', NULL) "
        "ON CONFLICT (username) DO NOTHING",
        ("jaba", generate_password_hash("thehutt")),
    )
    for last_name, full_name in ROSTER:
        first_token = full_name.split()[0].strip("()").lower()
        username = f"{first_token}.{last_name.lower().replace(chr(39), '').replace(' ', '')}"
        conn.execute(
            "INSERT INTO users (username, password_hash, role, resident_id) VALUES (?, ?, 'resident', ?) "
            "ON CONFLICT (username) DO NOTHING",
            (username, generate_password_hash(DEFAULT_RESIDENT_PASSWORD), resident_ids[last_name]),
        )


def _seed_half_blocks_and_rotations(conn, resident_ids):
    half_block_ids = {}
    for idx, (block_number, half, start, end) in enumerate(HALF_BLOCKS):
        cur = conn.execute(
            "INSERT INTO half_blocks (pgy_level, block_number, half, start_date, end_date) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (pgy_level, block_number, half) "
            "DO UPDATE SET start_date = excluded.start_date, end_date = excluded.end_date "
            "RETURNING id",
            (PGY4_LEVEL, block_number, half, start, end),
        )
        hb_id = cur.fetchone()[0]
        half_block_ids[idx] = hb_id

        for row, (last_name, _full_name) in enumerate(ROSTER):
            rotation = ROTATIONS[row][idx]
            conn.execute(
                "INSERT INTO rotations (resident_id, half_block_id, rotation) VALUES (?, ?, ?) "
                "ON CONFLICT (resident_id, half_block_id) DO UPDATE SET rotation = excluded.rotation",
                (resident_ids[last_name], hb_id, rotation),
            )
    return half_block_ids


def _seed_jeopardy(conn, half_block_ids, resident_ids):
    for idx, code in enumerate(JEOPARDY):
        last_name = ROSTER[_r_index(code)][0]
        conn.execute(
            "UPDATE half_blocks SET jeopardy_resident_id = ? WHERE id = ?",
            (resident_ids[last_name], half_block_ids[idx]),
        )


def _seed_time_off(conn, resident_ids):
    if not os.path.exists(CONFIG_INI):
        return
    parser = configparser.ConfigParser()
    parser.optionxform = str
    parser.read(CONFIG_INI)
    if "time off" not in parser:
        return
    for name, raw in parser["time off"].items():
        resident_id = resident_ids.get(name)
        if resident_id is None:
            continue
        conn.execute("DELETE FROM time_off WHERE resident_id = ?", (resident_id,))
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            start, end = _parse_date_range(part)
            conn.execute(
                "INSERT INTO time_off (resident_id, start_date, end_date) VALUES (?, ?, ?)",
                (resident_id, start, end),
            )


def _seed_history_baseline(conn, resident_ids):
    if not os.path.exists(HISTORY_JSON):
        return
    with open(HISTORY_JSON) as f:
        raw = json.load(f)
    # history.json's "Kira" key predates full-name migration; it's Kira Chandran.
    name_fixups = {"Kira": "Chandran"}
    for name, entry in raw.items():
        last_name = name_fixups.get(name, name)
        resident_id = resident_ids.get(last_name)
        if resident_id is None:
            continue
        conn.execute(
            "INSERT INTO history_baseline (resident_id, shift_name, count) VALUES (?, 'half_blocks_worked', ?) "
            "ON CONFLICT (resident_id, shift_name) DO UPDATE SET count = excluded.count",
            (resident_id, entry.get("half_blocks_worked", 0)),
        )
        conn.execute(
            "INSERT INTO history_baseline (resident_id, shift_name, count) VALUES (?, 'weekend', ?) "
            "ON CONFLICT (resident_id, shift_name) DO UPDATE SET count = excluded.count",
            (resident_id, entry.get("weekend", 0)),
        )
        for shift_name, count in entry.get("shifts", {}).items():
            conn.execute(
                "INSERT INTO history_baseline (resident_id, shift_name, count) VALUES (?, ?, ?) "
                "ON CONFLICT (resident_id, shift_name) DO UPDATE SET count = excluded.count",
                (resident_id, shift_name, count),
            )


def main():
    conn = dbmod.get_db()
    seed(conn)
    conn.close()
    print(f"Seeded database at {dbmod.DB_PATH}")


if __name__ == "__main__":
    main()
