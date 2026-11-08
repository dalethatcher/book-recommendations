#!/usr/bin/env python3
"""Book recommendation engine.

Single SQLite DB (books.db). Subcommands:

  init                       create/open the database
  import-audible FILE.csv    import an audible library export (title,author columns)
  import-goodreads FILE.csv  import a Goodreads export CSV
  import-awards DIR|FILE.csv import award CSVs (title,author,award,year,result)
  rate "Title" RATING [note] log a rating (1-5, decimals allowed)
  add "Title" "Author"       manually add a book to the library
  status                     show library/rating/recommendation counts
  gen [--n N] [--name X]     generate a digest -> recommendations-YYYY-MM-DD.md

Genres are pipe-separated strings on books.genres.
"""

import argparse
import csv
import glob
import os
import re
import sqlite3
import sys
from datetime import date

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "books.db")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SCHEMA_PATH = os.path.join(BASE_DIR, "schema.sql")


def connect():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init_db():
    with open(SCHEMA_PATH) as f:
        connect().executescript(f.read())


def get_or_create_book(con, title, author="", series="", source="manual", genres=""):
    row = con.execute(
        "SELECT id FROM books WHERE title=? COLLATE NOCASE AND author=? COLLATE NOCASE",
        (title.strip(), (author or "").strip()),
    ).fetchone()
    if row:
        return row["id"]
    cur = con.execute(
        "INSERT INTO books (title, author, series, source, genres) VALUES (?,?,?,?,?)",
        (title.strip(), (author or "").strip(), series, source, genres),
    )
    return cur.lastrowid


def normalize_award(raw):
    r = (raw or "").strip()
    aliases = {
        "hugo": "Hugo", "nebula": "Nebula", "clarke": "Clarke",
        "locus-sf": "Locus-SF", "locus-fantasy": "Locus-Fantasy",
        "worldfantasy": "WorldFantasy", "britishfantasy": "BritishFantasy",
        "mythopoeic": "Mythopoeic",
    }
    return aliases.get(r.lower(), r)


def import_books_csv(con, path, source):
    """Import library exports: title/author based CSVs (Audible or Goodreads)."""
    added = skipped = 0
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            keys = {k.lower().strip(): v for k, v in row.items() if k}
            title = keys.get("title", "").strip()
            author = (keys.get("author") or keys.get("authors") or "").strip()
            if not title:
                continue
            genres = (keys.get("genres") or keys.get("genre") or "").strip()
            # audible exports comma-separated (and duplicated) genres -> dedupe to pipe-separated
            seen, clean = set(), []
            for g in [g.strip() for g in genres.replace("|", ",").split(",")]:
                if g and g.lower() not in seen:
                    seen.add(g.lower())
                    clean.append(g)
            genres = "|".join(clean)
            existing = con.execute(
                "SELECT id FROM books WHERE title=? COLLATE NOCASE AND author=? COLLATE NOCASE",
                (title, author),
            ).fetchone()
            if existing:
                skipped += 1
                continue
            con.execute(
                "INSERT INTO books (title, author, source, genres) VALUES (?,?,?,?)",
                (title, author, source, genres),
            )
            added += 1
    con.commit()
    print(f"imported {added} new, skipped {skipped} existing (source={source})")


def import_awards(con, paths):
    added = 0
    for path in paths:
        if os.path.isdir(path):
            files = sorted(
                os.path.join(path, f) for f in os.listdir(path) if f.endswith(".csv")
            )
        else:
            files = sorted(glob.glob(path)) or [path]
        for fn in files:
            with open(fn, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    title = (row.get("title") or "").strip()
                    author = re.sub(r"\s*\(.*?\)\s*", " ", row.get("author") or "").strip()
                    award = normalize_award(row.get("award"))
                    year = int(row["year"]) if (row.get("year") or "").strip().isdigit() else None
                    result = (row.get("result") or "nominee").strip().lower()
                    if not title or not award:
                        continue
                    book_id = get_or_create_book(con, title, author, source="award")
                    dup = con.execute(
                        "SELECT 1 FROM awards WHERE book_id=? AND award=? AND year=?",
                        (book_id, award, year),
                    ).fetchone()
                    if not dup:
                        con.execute(
                            "INSERT INTO awards (book_id, award, year, result) VALUES (?,?,?,?)",
                            (book_id, award, year, result),
                        )
                        added += 1
    con.commit()
    print(f"imported {added} award entries")


def rate(con, title, rating, note=""):
    # fuzzy: match by substring of title (first match wins)
    row = con.execute(
        "SELECT id, title FROM books WHERE title LIKE ? COLLATE NOCASE ORDER BY length(title)",
        (f"%{title}%",),
    ).fetchone()
    if not row:
        sys.exit(f"no book matching '{title}' in library — add it first (add command)")
    con.execute(
        "INSERT INTO ratings (book_id, rating, note) VALUES (?,?,?)", (row["id"], rating, note)
    )
    con.commit()
    print(f"rated '{row['title']}' {rating}{' — ' + note if note else ''}")


def library_profile(con):
    """Return genre/author affinity weights learned from ratings."""
    genre_w, author_w = {}, {}
    rows = con.execute(
        """SELECT b.author, b.genres, r.rating FROM ratings r JOIN books b ON b.id=r.book_id"""
    ).fetchall()
    for row in rows:
        w = float(row["rating"])
        for g in (row["genres"] or "").split("|"):
            g = g.strip()
            if g:
                genre_w[g] = genre_w.get(g, 0.0) + w
        if row["author"]:
            author_w[row["author"].strip()] = author_w.get(row["author"].strip(), 0.0) + w
    return genre_w, author_w, len(rows)


def norm_title(s):
    """Loose title key for ownership matching: lowercase, drop subtitles in
    parentheses, drop punctuation, collapse whitespace."""
    s = re.sub(r"\(.*?\)", " ", s or "")
    s = s.lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def build_digest(con, n=8, name=""):
    genre_w, author_w, n_ratings = library_profile(con)
    rated_ids = {r["book_id"] for r in con.execute("SELECT book_id FROM ratings")}
    excluded = rated_ids | {
        r["book_id"] for r in con.execute(
            "SELECT book_id FROM recommendations WHERE status IN ('declined','finished','new')"
        )
    }
    # never recommend books the user already owns/listened to
    owned = {
        norm_title(t) for (t,) in con.execute(
            "SELECT title FROM books WHERE source IN ('audible','goodreads','manual')"
        )
    } - {""}

    calibrating = n_ratings < 10
    candidates = con.execute(
        """SELECT DISTINCT b.* FROM books b
           JOIN awards a ON a.book_id = b.id
           WHERE b.id NOT IN (SELECT book_id FROM recommendations WHERE status != 'interested')
           AND b.id NOT IN (SELECT book_id FROM ratings)
           AND b.id NOT IN ({})""".format(",".join(map(str, excluded)) or "-1")
    ).fetchall()

    scored = []
    for c in candidates:
        if norm_title(c["title"]) in owned:
            continue
        score, reasons = 0.0, []
        for g in (c["genres"] or "").split("|"):
            g = g.strip()
            if g and genre_w.get(g, 0) > 0:
                score += genre_w[g]
                reasons.append(f"you rate {g} highly")
        if author_w.get(c["author"] or "", 0) > 0:
            score += 3 * author_w[c["author"]]
            reasons.append(f"you like {c['author']}")
        wins = con.execute(
            "SELECT COUNT(*) c FROM awards WHERE book_id=? AND result='winner'", (c["id"],)
        ).fetchone()["c"]
        if wins:
            score += 2 * wins
            reasons.append(f"{wins} major award win")
        noms = con.execute(
            "SELECT COUNT(*) c FROM awards WHERE book_id=?", (c["id"],)
        ).fetchone()["c"]
        score += 0.5 * noms
        if not reasons:
            reasons.append("award-listed")
        scored.append((score, c, "; ".join(reasons[:2])))

    scored.sort(key=lambda x: -x[0])
    picks = scored[: n - 1]
    # bandit-lite exploration pick: random mid-tier pick outside your top genre
    top_genre = max(genre_w, key=genre_w.get) if genre_w else None
    stretch = [s for s in scored[n - 1:] if not any(
        g.strip() == top_genre for g in (s[1]["genres"] or "").split("|"))]
    if stretch and top_genre:
        picks.append(stretch[0])

    today = date.today().isoformat()
    out = os.path.join(BASE_DIR, f"recommendations-{today}{'-' + name if name else ''}.md")
    cur = con.execute(
        "INSERT INTO runs (mode, output_file) VALUES ('auto', ?)", (out,)
    )
    run_id = cur.lastrowid

    lines = [f"# Book recommendations — {today}", ""]
    if calibrating:
        lines += [
            "> CALIBRATION PHASE: fewer than 10 ratings on file.",
            "> Rankings lean mostly on award prestige; they'll sharpen fast as you rate books.",
            "",
        ]
    if not picks:
        lines += ["No new candidates available (import award data or your library first)."]
    for i, (score, c, reason) in enumerate(picks, 1):
        tag = " (stretch pick — outside your usual genres)" if (i == len(picks) and top_genre) else ""
        awards_txt = con.execute(
            "SELECT group_concat(award || ' ' || year || IFNULL(' ('||result||')',''), ', ') a "
            "FROM awards WHERE book_id=?", (c["id"],)
        ).fetchone()["a"] or ""
        lines += [
            f"## {i}. {c['title']} — {c['author']}{tag}",
            f"- Why: {reason}",
            f"- Score: {score:.1f}" + (f" | Awards: {awards_txt}" if awards_txt else ""),
            "",
        ]
    with open(out, "w") as f:
        f.write("\n".join(lines))

    for score, c, reason in picks:
        con.execute(
            "INSERT INTO recommendations (book_id, run_id, reason, score) VALUES (?,?,?,?)",
            (c["id"], run_id, reason, score),
        )
    con.commit()
    print(f"wrote {len(picks)} recommendations to {out}")


def status(con):
    for t in ("books", "ratings", "recommendations", "awards", "runs"):
        c = con.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
        print(f"{t:>15}: {c}")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    sp = sub.add_parser("import-audible"); sp.add_argument("file")
    sp = sub.add_parser("import-goodreads"); sp.add_argument("file")
    sp = sub.add_parser("import-awards"); sp.add_argument("path")
    sp = sub.add_parser("rate"); sp.add_argument("title"); sp.add_argument("rating", type=float)
    sp.add_argument("note", nargs="*")
    sp = sub.add_parser("add"); sp.add_argument("title"); sp.add_argument("author", nargs="?", default="")
    sub.add_parser("status")
    sp = sub.add_parser("gen"); sp.add_argument("--n", type=int, default=8); sp.add_argument("--name")
    a = p.parse_args()
    init_db()
    con = connect()
    try:
        if a.cmd == "init":
            status(con)
        elif a.cmd in ("import-audible", "import-goodreads"):
            import_books_csv(con, a.file, "audible" if "audible" in a.cmd else "goodreads")
        elif a.cmd == "import-awards":
            import_awards(con, [a.path])
        elif a.cmd == "rate":
            rate(con, a.title, a.rating, " ".join(a.note))
        elif a.cmd == "add":
            bid = get_or_create_book(con, a.title, a.author)
            con.commit()
            print(f"added book id={bid}")
        elif a.cmd == "status":
            status(con)
        elif a.cmd == "gen":
            build_digest(con, a.n, a.name or "")
    finally:
        con.close()


if __name__ == "__main__":
    main()
