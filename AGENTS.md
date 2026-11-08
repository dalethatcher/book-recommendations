# AGENTS.md — book-recommendations

A periodically-run book recommendation system for dale, focused on sci-fi/fantasy.
All state lives in ONE SQLite database: `books.db` (schema in `schema.sql`).

## How to work with the data

`books.db` is the source of truth. Inspect with plain SQL:

    sqlite3 books.db "SELECT b.title, r.rating FROM ratings r JOIN books b ON b.id=r.book_id"

Tables:
- `books(id, title, author, series, source, genres, published_year)` — genres are pipe-separated
- `ratings(book_id, rating 1-5 REAL, note, rated_at)`
- `recommendations(book_id, recommended_at, run_id, reason, score, status)` — status: new/interested/queued/finished/declined. NEVER re-recommend a book that has status finished/declined, or appears in ratings.
- `awards(book_id, award, year, result)` — award names: Hugo, Nebula, Clarke, Locus-SF, Locus-Fantasy, WorldFantasy, BritishFantasy, Mythopoeic
- `blocklist(series UNIQUE, reason)` — series the user opted out of continuing; gen skips them
- `runs(ran_at, mode, output_file)`

Use a venv for ALL Python work here: `.venv/bin/python recommend.py ...`
(create it with `python3 -m venv .venv` if missing — user rule: never bare `python3`).

`recommend.py` is the CLI covering all normal operations — use it rather than hand-writing SQL for writes:

    .venv/bin/python recommend.py status
    .venv/bin/python recommend.py rate "Dungeon Crawler Carl" 5 "absurdly fun"
    .venv/bin/python recommend.py gen --n 8            # writes recommendations-YYYY-MM-DD.md + logs run
    .venv/bin/python recommend.py import-audible audible_library.csv
    .venv/bin/python recommend.py import-awards awards_raw/   # CSVs: title,author,award,year,result
    .venv/bin/python extract_awards.py  # rebuild awards_raw/*.csv from awards_raw/*.wiki

## The algorithm (do not change casually)

Content-based + taste-affinity scoring. Weights come from the user's own ratings only
(single-user system; collaborative filtering is not applicable — see research notes below).
- score = sum(genre weights) + 3×author weight + 2×(award wins) + 0.5×(award nominations)
- Diversity cap: max 2 titles per author per digest (user request).
- Cold start: under 10 ratings → calibration phase, digest says so explicitly.
- One "stretch pick" per run outside the user's top genre (bandit-lite exploration) — keep this.

Research basis: Su & Khoshgoftaar 2009 (CF survey — CF needs multi-user data, hence
content-based here); ACL R19-2009 (content-based book recommenders work well);
MeLU / arXiv:1908.00413 and arXiv:1412.7156 (elicitation: ask the user to rate a small
diverse set to calibrate); arXiv:1407.2806 (exploration/exploitation → the stretch pick).

## Recurring run (on demand — NO cron by user choice)

The user deliberately declined scheduled runs. Generate digests only when the user
asks: run `.venv/bin/python recommend.py gen --n 8`, which writes
`recommendations-YYYY-MM-DD.md` and logs the run. If the user says ratings casually
("X was a 5"), log them via `recommend.py rate` as they say them.

## Rules

- Never ask for or handle Amazon/Audible credentials. `setup_audible.sh` is user-run.
- Award data comes from `awards_raw/*.csv` scraped from Wikipedia; re-scrape rather than inventing entries.
- Rating scale 1–5, decimals allowed. Negative feedback ("that rec was terrible") → status=declined with a note.
- When adding award entries to `awards`, match books by title/author; create the book row with source='award' if missing (the import command does this).
