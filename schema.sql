-- book-recommendations: single SQLite database
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS books (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    author TEXT,
    series TEXT,
    source TEXT NOT NULL DEFAULT 'award',      -- audible | goodreads | manual | award
    genres TEXT DEFAULT '',                     -- pipe-separated, e.g. 'Science Fiction|Space Opera'
    published_year INTEGER,
    added_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(title COLLATE NOCASE, author COLLATE NOCASE)
);

CREATE TABLE IF NOT EXISTS ratings (
    id INTEGER PRIMARY KEY,
    book_id INTEGER NOT NULL REFERENCES books(id),
    rating REAL NOT NULL,                       -- 1-5, decimals allowed
    note TEXT DEFAULT '',
    rated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS recommendations (
    id INTEGER PRIMARY KEY,
    book_id INTEGER NOT NULL REFERENCES books(id),
    recommended_at TEXT NOT NULL DEFAULT (datetime('now')),
    run_id INTEGER,
    reason TEXT DEFAULT '',
    score REAL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'new'          -- new | interested | queued | finished | declined
);

CREATE TABLE IF NOT EXISTS awards (
    id INTEGER PRIMARY KEY,
    book_id INTEGER NOT NULL REFERENCES books(id),
    award TEXT NOT NULL,                        -- Hugo | Nebula | Clarke | Locus-SF | WorldFantasy | BritishFantasy | Mythopoeic | Locus-Fantasy
    year INTEGER,
    result TEXT DEFAULT 'nominee'               -- winner | nominee
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    ran_at TEXT NOT NULL DEFAULT (datetime('now')),
    mode TEXT NOT NULL DEFAULT 'auto',          -- auto | interactive
    output_file TEXT
);

CREATE TABLE IF NOT EXISTS blocklist (
    id INTEGER PRIMARY KEY,
    series TEXT NOT NULL UNIQUE,
    reason TEXT DEFAULT '',
    added_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_ratings_book ON ratings(book_id);
CREATE INDEX IF NOT EXISTS idx_recs_book ON recommendations(book_id);
CREATE INDEX IF NOT EXISTS idx_awards_book ON awards(book_id);
