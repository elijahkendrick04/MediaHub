-- Swim Content Automation — canonical schema (SQLite)
-- See BLUEPRINT.md §4 for the design rationale.

CREATE TABLE IF NOT EXISTS club (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    short_name   TEXT,
    brand_json   TEXT
);

CREATE TABLE IF NOT EXISTS swimmer (
    id              INTEGER PRIMARY KEY,
    display_name    TEXT NOT NULL,
    aka_json        TEXT DEFAULT '[]',     -- known alternate spellings
    gender          TEXT,                  -- 'M' | 'F'
    dob             TEXT,                  -- ISO yyyy-mm-dd, optional
    club_id         INTEGER REFERENCES club(id),
    swim_england_id TEXT,                  -- canonical UK id once resolved
    swimrankings_id TEXT
);

CREATE TABLE IF NOT EXISTS meet (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    venue        TEXT,
    course       TEXT NOT NULL,            -- 'LC' (50m) | 'SC' (25m)
    start_date   TEXT,
    end_date     TEXT,
    source_type  TEXT,                     -- 'csv'|'hytek'|'pdf'|'sportsystems'|'url'
    source_uri   TEXT,
    status       TEXT DEFAULT 'final'      -- 'live'|'final'
);

CREATE TABLE IF NOT EXISTS race_result (
    id                       INTEGER PRIMARY KEY,
    meet_id                  INTEGER NOT NULL REFERENCES meet(id),
    swimmer_id               INTEGER NOT NULL REFERENCES swimmer(id),
    event_code               TEXT NOT NULL,        -- e.g. 'M_50_FR_LC'
    round                    TEXT,                 -- 'heat'|'semi'|'final'|'timed_final'
    place                    INTEGER,
    time_cs                  INTEGER NOT NULL,     -- centiseconds
    entry_time_cs            INTEGER,
    dq                       INTEGER DEFAULT 0,
    dq_reason                TEXT,
    splits_json              TEXT
);
CREATE INDEX IF NOT EXISTS ix_race_swimmer_event ON race_result(swimmer_id, event_code);

-- The canonical PB store. Never updated from a single meet without a recompute job.
CREATE TABLE IF NOT EXISTS personal_best (
    swimmer_id   INTEGER NOT NULL REFERENCES swimmer(id),
    event_code   TEXT NOT NULL,
    course       TEXT NOT NULL,
    best_time_cs INTEGER NOT NULL,
    best_date    TEXT,
    source       TEXT,                          -- 'meet'|'imported'|'swim_england'|'manual'
    confidence   REAL DEFAULT 1.0,
    PRIMARY KEY (swimmer_id, event_code, course)
);

CREATE TABLE IF NOT EXISTS club_record (
    club_id      INTEGER NOT NULL REFERENCES club(id),
    event_code   TEXT NOT NULL,
    course       TEXT NOT NULL,
    age_band     TEXT,
    time_cs      INTEGER NOT NULL,
    holder       TEXT,
    date_set     TEXT,
    PRIMARY KEY (club_id, event_code, course, age_band)
);

CREATE TABLE IF NOT EXISTS qualifying_time (
    standard     TEXT NOT NULL,                  -- 'BUCS_LC_2025_26'
    event_code   TEXT NOT NULL,
    course       TEXT NOT NULL,
    gender       TEXT NOT NULL,
    age_band     TEXT,
    time_cs      INTEGER NOT NULL,
    PRIMARY KEY (standard, event_code, course, gender, age_band)
);

CREATE TABLE IF NOT EXISTS achievement (
    id                   INTEGER PRIMARY KEY,
    meet_id              INTEGER NOT NULL REFERENCES meet(id),
    swimmer_id           INTEGER REFERENCES swimmer(id),
    race_id              INTEGER REFERENCES race_result(id),
    type                 TEXT NOT NULL,          -- see taxonomy
    evidence_json        TEXT NOT NULL,          -- raw data points used
    explanation          TEXT NOT NULL,          -- "PB by 1.2s, first sub-60"
    confidence           REAL NOT NULL,
    content_worthiness   INTEGER NOT NULL,
    suggested_formats    TEXT                    -- json list
);
CREATE INDEX IF NOT EXISTS ix_ach_meet ON achievement(meet_id);

CREATE TABLE IF NOT EXISTS content_item (
    id                INTEGER PRIMARY KEY,
    achievement_id    INTEGER REFERENCES achievement(id),
    format            TEXT NOT NULL,             -- 'feed'|'story'|'reel_script'|'recap'
    captions_json     TEXT,                      -- list of variants
    approved_caption  TEXT,
    approval_status   TEXT DEFAULT 'pending'     -- 'pending'|'approved'|'rejected'|'edited'
);
