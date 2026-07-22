"""One-shot (idempotent) seed script for the web app database.

Populates both PGY-4 and PGY-1:
  - Admin login and resident logins
  - Half-blocks for AY 2026-2027
  - Rotations and jeopardy
  - Time-off requests
"""

import csv
import configparser
import os
import re

from werkzeug.security import generate_password_hash
from . import db as dbmod

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_INI = os.path.join(REPO_ROOT, "config.ini")
PGY1_CSV = os.path.join(REPO_ROOT, "data", "Final Intern Year 2026-2027 Block Schedules - PGY-1.csv")

PGY4_LEVEL = 4
PGY1_LEVEL = 1
DEFAULT_RESIDENT_PASSWORD = "changeme"

# PGY-4 Roster
ROSTER_PGY4 = [
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

ROTATIONS_PGY4 = [
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

JEOPARDY_PGY4 = [
    "R3", "R3", "R6", "R6", "R10", "R10", "R15", "R15", "R11", "R11", "R13", "R13",
    "R2", "R2", "R14", "R14", "R9", "R9", "R7", "R7", "R1", "R1", "R5", "R8", "R8", "R12",
]


def _r_index(code):
    return int(code[1:]) - 1


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
    conn.execute("DROP TABLE IF EXISTS history_baseline")

    # 1. Seed PGY-4
    seed_pgy(conn, PGY4_LEVEL, ROSTER_PGY4, ROTATIONS_PGY4, JEOPARDY_PGY4)

    # 2. Seed PGY-1
    seed_pgy1_from_csv(conn)

    conn.commit()


def seed_pgy(conn, pgy_level, roster, rotations, jeopardy):
    resident_ids = {}
    for last_name, full_name in roster:
        cur = conn.execute(
            "INSERT INTO residents (full_name, last_name, pgy_level) VALUES (?, ?, ?) "
            "ON CONFLICT (last_name, pgy_level) DO UPDATE SET full_name = excluded.full_name "
            "RETURNING id",
            (full_name, last_name, pgy_level),
        )
        resident_ids[last_name] = cur.fetchone()[0]

    # Seed logins
    for last_name, full_name in roster:
        first_token = full_name.split()[0].strip("()").lower()
        username = f"{first_token}.{last_name.lower().replace(chr(39), '').replace(' ', '')}"
        conn.execute(
            "INSERT INTO users (username, password_hash, role, resident_id) VALUES (?, ?, 'resident', ?) "
            "ON CONFLICT (username) DO NOTHING",
            (username, generate_password_hash(DEFAULT_RESIDENT_PASSWORD, method='pbkdf2:sha256'), resident_ids[last_name]),
        )

    # Admin user
    conn.execute(
        "INSERT INTO users (username, password_hash, role, resident_id) VALUES (?, ?, 'admin', NULL) "
        "ON CONFLICT (username) DO NOTHING",
        ("jaba", generate_password_hash("thehutt", method='pbkdf2:sha256')),
    )

    # Seed half blocks and rotations
    half_block_ids = {}
    for idx, (block_number, half, start, end) in enumerate(HALF_BLOCKS):
        cur = conn.execute(
            "INSERT INTO half_blocks (pgy_level, block_number, half, start_date, end_date) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (pgy_level, block_number, half) "
            "DO UPDATE SET start_date = excluded.start_date, end_date = excluded.end_date "
            "RETURNING id",
            (pgy_level, block_number, half, start, end),
        )
        hb_id = cur.fetchone()[0]
        half_block_ids[idx] = hb_id

        for row, (last_name, _full_name) in enumerate(roster):
            rotation = rotations[row][idx]
            conn.execute(
                "INSERT INTO rotations (resident_id, half_block_id, rotation) VALUES (?, ?, ?) "
                "ON CONFLICT (resident_id, half_block_id) DO UPDATE SET rotation = excluded.rotation",
                (resident_ids[last_name], hb_id, rotation),
            )

    # Jeopardy update
    for idx, code in enumerate(jeopardy):
        last_name = roster[_r_index(code)][0]
        conn.execute(
            "UPDATE half_blocks SET jeopardy_resident_id = ? WHERE id = ?",
            (resident_ids[last_name], half_block_ids[idx]),
        )

    # Seed config.ini timeoff requests for PGY4
    if pgy_level == PGY4_LEVEL and os.path.exists(CONFIG_INI):
        parser = configparser.ConfigParser()
        parser.optionxform = str
        parser.read(CONFIG_INI)
        if "time off" in parser:
            for name, raw in parser["time off"].items():
                res_id = resident_ids.get(name)
                if res_id is None:
                    continue
                conn.execute("DELETE FROM time_off WHERE resident_id = ?", (res_id,))
                for part in raw.split(","):
                    part = part.strip()
                    if not part:
                        continue
                    start, end = _parse_date_range(part)
                    conn.execute(
                        "INSERT INTO time_off (resident_id, start_date, end_date) VALUES (?, ?, ?)",
                        (res_id, start, end),
                    )


ROSTER_PGY1_DEFAULT = [
    ("Alex", "Alex Intern"),
    ("Ben", "Ben Intern"),
    ("Chloe", "Chloe Intern"),
    ("David", "David Intern"),
    ("Emma", "Emma Intern"),
    ("Felix", "Felix Intern"),
    ("Grace", "Grace Intern"),
    ("Hannah", "Hannah Intern"),
    ("Ian", "Ian Intern"),
    ("Julia", "Julia Intern"),
    ("Kevin", "Kevin Intern"),
    ("Liam", "Liam Intern"),
    ("Maya", "Maya Intern"),
    ("Noah", "Noah Intern"),
    ("Olivia", "Olivia Intern"),
]


def seed_pgy1_from_csv(conn):
    roster_pgy1 = []
    rotations_raw = []
    jeopardy_row = []

    if os.path.exists(PGY1_CSV):
        with open(PGY1_CSV) as f:
            r = csv.reader(f)
            rows = list(r)
        jeopardy_row = [cell.strip() for cell in rows[20][1:21]]
        for row in rows[5:20]:
            label = row[0].strip()
            m = re.match(r"(R\d+):\s*(.*)", label)
            if m:
                name = m.group(2).strip()
                blocks_raw = [cell.strip() for cell in row[1:21]]
                roster_pgy1.append((name, name))
                rotations_raw.append(blocks_raw)
    else:
        # Default fallback synthetic PGY-1 data
        roster_pgy1 = ROSTER_PGY1_DEFAULT
        default_rot = ["MGB", "MGB", "Flex", "NWH", "Vacation", "Ultrasound", "MGB", "MGB", "MGB Nights", "MGB",
                       "Elective", "Elective", "MGB", "MGB", "Vacation", "Flex", "NWH", "NWH", "MGB", "MGB"]
        rotations_raw = [default_rot for _ in roster_pgy1]
        jeopardy_row = [f"R{(i % 15) + 1}" for i in range(20)]

    resident_ids = {}
    for last_name, full_name in roster_pgy1:
        cur = conn.execute(
            "INSERT INTO residents (full_name, last_name, pgy_level) VALUES (?, ?, ?) "
            "ON CONFLICT (last_name, pgy_level) DO UPDATE SET full_name = excluded.full_name "
            "RETURNING id",
            (full_name, last_name, PGY1_LEVEL),
        )
        resident_ids[last_name] = cur.fetchone()[0]

    for last_name, full_name in roster_pgy1:
        username = last_name.lower().replace(chr(39), "").replace(" ", "")
        stale = f"{username}.pgy1"
        conn.execute("DELETE FROM users WHERE username = ?", (stale,))
        conn.execute(
            "INSERT INTO users (username, password_hash, role, resident_id) VALUES (?, ?, 'resident', ?) "
            "ON CONFLICT (username) DO UPDATE SET "
            "password_hash = excluded.password_hash, role = 'resident', resident_id = excluded.resident_id",
            (username, generate_password_hash(DEFAULT_RESIDENT_PASSWORD, method="pbkdf2:sha256"),
             resident_ids[last_name]),
        )

    half_block_ids = {}
    for idx, (block_number, half, start, end) in enumerate(HALF_BLOCKS):
        cur = conn.execute(
            "INSERT INTO half_blocks (pgy_level, block_number, half, start_date, end_date) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (pgy_level, block_number, half) "
            "DO UPDATE SET start_date = excluded.start_date, end_date = excluded.end_date "
            "RETURNING id",
            (PGY1_LEVEL, block_number, half, start, end),
        )
        hb_id = cur.fetchone()[0]
        half_block_ids[idx] = hb_id

        for row_idx, (last_name, _) in enumerate(roster_pgy1):
            if idx >= 6:
                csv_col_idx = idx - 6
                rotation = rotations_raw[row_idx][csv_col_idx]
            else:
                rotation = "Vacation" if idx in [0, 1] else "Ultrasound"
            
            conn.execute(
                "INSERT INTO rotations (resident_id, half_block_id, rotation) VALUES (?, ?, ?) "
                "ON CONFLICT (resident_id, half_block_id) DO UPDATE SET rotation = excluded.rotation",
                (resident_ids[last_name], hb_id, rotation),
            )

    for idx, code in enumerate(jeopardy_row):
        half_block_idx = idx + 6
        if "/" in code:
            code = code.split("/")[0].strip()
        last_name = roster_pgy1[_r_index(code)][0]
        conn.execute(
            "UPDATE half_blocks SET jeopardy_resident_id = ? WHERE id = ?",
            (resident_ids[last_name], half_block_ids[half_block_idx]),
        )


def main():
    conn = dbmod.get_db()
    seed(conn)
    conn.close()
    print(f"Seeded database at {dbmod.DB_PATH}")


if __name__ == "__main__":
    main()
