-- Schema for the shiftoptim web app. See the plan doc for rationale.

CREATE TABLE IF NOT EXISTS residents (
    id INTEGER PRIMARY KEY,
    full_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    pgy_level INTEGER NOT NULL,
    UNIQUE (last_name, pgy_level)
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'resident')),
    resident_id INTEGER REFERENCES residents(id)
);

CREATE TABLE IF NOT EXISTS half_blocks (
    id INTEGER PRIMARY KEY,
    pgy_level INTEGER NOT NULL,
    block_number INTEGER NOT NULL,
    half TEXT NOT NULL CHECK (half IN ('a', 'b')),
    start_date TEXT NOT NULL,      -- ISO date
    end_date TEXT NOT NULL,
    jeopardy_resident_id INTEGER REFERENCES residents(id),
    UNIQUE (pgy_level, block_number, half)
);

CREATE TABLE IF NOT EXISTS rotations (
    resident_id INTEGER NOT NULL REFERENCES residents(id),
    half_block_id INTEGER NOT NULL REFERENCES half_blocks(id),
    rotation TEXT NOT NULL,        -- MGB / MGB Nights / Flex / Vacation / Elective / Elective/LTD / NWH / Teaching
    PRIMARY KEY (resident_id, half_block_id)
);

CREATE TABLE IF NOT EXISTS time_off (
    id INTEGER PRIMARY KEY,
    resident_id INTEGER NOT NULL REFERENCES residents(id),
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    pgy_level INTEGER NOT NULL,
    block_number INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published')),
    min_shifts INTEGER NOT NULL,
    time_limit REAL NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS assignments (
    run_id INTEGER NOT NULL REFERENCES runs(id),
    resident_id INTEGER NOT NULL REFERENCES residents(id),
    day TEXT NOT NULL,             -- ISO date
    shift_name TEXT NOT NULL,
    PRIMARY KEY (run_id, resident_id, day)
);

CREATE INDEX IF NOT EXISTS idx_assignments_resident ON assignments(resident_id);
CREATE INDEX IF NOT EXISTS idx_assignments_run ON assignments(run_id);
CREATE INDEX IF NOT EXISTS idx_rotations_half_block ON rotations(half_block_id);
CREATE INDEX IF NOT EXISTS idx_time_off_resident ON time_off(resident_id);
