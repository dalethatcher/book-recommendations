#!/usr/bin/env python3
"""Extract award CSVs from awards_raw/*.wiki.

Output: awards_raw/<name>.csv with header title,author,award,year,result
"""
import csv
import os
import re

RAW = os.path.join(os.path.dirname(os.path.abspath(__file__)), "awards_raw")

YEAR_RE = re.compile(r"\b(19[4-9]\d|20[0-2]\d)\b")


def _apply_templates(t):
    """Resolve templates innermost-out: {{sort|X|Y}} -> Y, others dropped."""
    while "{{" in t:
        m = re.search(r"\{\{[^{}]*\}\}", t)
        if not m:
            break
        inner = m.group(0)[2:-2]
        parts = inner.split("|")
        if parts[0].strip().lower() == "sort":
            repl = parts[-1] if len(parts) > 1 else ""
        elif parts[0].strip().lower() == "sortname":
            repl = " ".join(re.sub(r"^\d+=", "", p).strip() for p in parts[1:3])
        else:
            repl = ""
        t = t[:m.start()] + repl + t[m.end():]
    return t


def clean(text):
    t = text
    t = re.sub(r"<ref[^>]*>.*?</ref>", "", t, flags=re.S)
    t = re.sub(r"<ref[^>]*/>", "", t)
    t = re.sub(r"{{cite[^}]*}}", "", t, flags=re.S)
    t = re.sub(r"{{efn[^}]*}}", "", t, flags=re.S)
    t = _apply_templates(t)
    t = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", t)
    t = re.sub(r"\[+|\]+", "", t)
    t = re.sub(r"'''?", "", t)
    t = re.sub(r"<[^>]+>", "", t)
    t = t.replace("&nbsp;", " ").replace("&amp;", "&")
    # strip cell attribute prefixes: everything up to the last '|'
    if "|" in t:
        t = t.rsplit("|", 1)[-1]
    t = re.sub(r"\s+", " ", t).strip(" ;,*–-")
    return t.strip()


def _raw_clean(text):
    """Light clean that preserves row-attr markers we test on raw cells."""
    t = re.sub(r"<ref[^>]*>.*?</ref>", "", text, flags=re.S)
    return t


def split_rows(tbl):
    """Split a wikitext table into (attrs, [(cell, rowspan)]) rows.
    Header lines ('!') are kept; if the header sits before the first |- it is
    emitted as the first row."""
    rows = []
    parts = re.split(r"(?m)^\|-", tbl)
    for i, chunk in enumerate(parts):
        attrs = ""
        nl = chunk.find("\n")
        if nl != -1 and not chunk[:nl].lstrip().startswith(("|", "!")):
            attrs = chunk[:nl]
            chunk = chunk[nl + 1:]
        cells = []
        for line in chunk.split("\n"):
            line = line.strip()
            if not line or line.startswith(("|}", "{|", "|+", "!!")):
                continue
            if line.startswith(("!", "|")):
                line = line[1:]
            for piece in line.split("||"):
                piece = piece.strip()
                if piece:
                    span = 1
                    rm = re.search(r"rowspan\s*=\s*\"?(\d+)", piece)
                    if rm:
                        span = int(rm.group(1))
                    cells.append((piece, span))
        if cells:
            rows.append((attrs, cells))
    return rows


def to_grid(rows, width):
    """Resolve rowspans into a fixed-width grid of cleaned cells."""
    carry = {}  # col -> [raw_text, remaining]
    grid = []
    for attrs, cells in rows:
        row = [None] * width
        for col, (val, rem) in list(carry.items()):
            row[col] = val
            if rem - 1 <= 0:
                del carry[col]
            else:
                carry[col] = [val, rem - 1]
        free = [c for c in range(width) if row[c] is None]
        idx = 0
        for cell, span in cells:
            if idx >= len(free):
                break
            col = free[idx]
            idx += 1
            row[col] = cell
            if span > 1:
                carry[col] = [cell, span - 1]
        grid.append((attrs, [clean(c) if c else "" for c in row]))
    return grid


def extract_shape_a(text):
    """Tables with columns year|author|title|publisher|ref; winner = lightyellow
    row attr (or author asterisk)."""
    recs = []
    for tbl in re.findall(r"\{\|.*?\n\|\}", text, flags=re.S):
        rows = split_rows(tbl)
        if not rows:
            continue
        header_cells = [clean(c) for c, _ in rows[0][1]]
        width = len(rows[0][1])
        if "Year" not in " ".join(header_cells):
            continue
        grid = to_grid(rows, width)
        for attrs, vals in grid:
            joined = " ".join(vals)
            if "Year" in vals[0] and "Novel" in joined and ("Author" in joined or "Work" in joined):
                continue  # header
            winner = "lightyellow" in attrs
            year = None
            m = YEAR_RE.search(vals[0] or "")
            if m:
                year = int(m.group(0))
            author = vals[1]
            title = vals[2]
            if year is None or not title or title.lower() == "not awarded":
                continue
            if not author:
                continue
            recs.append((year, author, title, winner))
    return recs


def extract_locus(text, award):
    recs = []
    for tbl in re.findall(r"\{\|.*?\n\|\}", text, flags=re.S):
        rows = split_rows(tbl)
        if not rows:
            continue
        header_cells = [clean(c) for c, _ in rows[0][1]]
        width = len(rows[0][1])
        h = " ".join(header_cells).lower()
        if "year" not in h or ("novel" not in h and "author" not in h):
            continue
        author_col = 1 if "author" in header_cells[1].lower() else 2
        title_col = 1 if author_col == 2 else 2
        grid = to_grid(rows, width)
        for attrs, vals in grid:
            if vals and "year" in vals[0].lower():
                continue
            m = YEAR_RE.search(vals[0] or "")
            if not m:
                continue
            year = int(m.group(0))
            title, author = vals[title_col], vals[author_col]
            if title and title.lower() != "not awarded":
                recs.append((year, author, title, True))
    return recs


def extract_myth(text):
    """Multiple tables under per-category headings; keep Adult Literature ones
    plus the original combined award (1971-1991). Category headings are level
    <=3 ('==='), decade sub-headings are level 4."""
    heads = [(m.start(), len(m.group(1)), m.group(2).strip())
             for m in re.finditer(r"(?m)^(={2,4})\s*([^=\n].*?)\s*\1\s*$", text)]
    recs = []
    for m in re.finditer(r"\{\|.*?\n\|\}", text, flags=re.S):
        tpos = m.start()
        category = ""
        for hpos, level, name in heads:
            if hpos < tpos and level <= 3:
                category = name
        hl = category.lower()
        keep = hl.startswith("adult") or hl.startswith("fantasy (1971")
        if not keep:
            continue
        rows = split_rows(m.group(0))
        if not rows:
            continue
        width = len(rows[0][1])
        grid = to_grid(rows, width)
        for attrs, vals in grid:
            if vals and "year" in vals[0].lower():
                continue
            m2 = YEAR_RE.search(vals[0] or "")
            if not m2:
                continue
            year = int(m2.group(0))
            author, title = vals[1], vals[2]
            winner = "lightyellow" in attrs
            if title and title.lower() != "not awarded" and author:
                recs.append((year, author, title, winner))
    return recs


def write_csv(name, recs, min_year=2000):
    out = os.path.join(RAW, f"{name}.csv")
    seen, n = set(), 0
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["title", "author", "award", "year", "result"])
        for year, author, title, winner in recs:
            if year is None or year < min_year or not title or not author:
                continue
            key = (title.lower(), author.lower(), year, winner)
            if key in seen:
                continue
            seen.add(key)
            w.writerow([title, author, name, year, "winner" if winner else "nominee"])
            n += 1
    print(f"{name}.csv: {n} rows (2000+)")


JOBS = {
    "hugo": ("hugo.wiki", extract_shape_a),
    "nebula": ("nebula.wiki", extract_shape_a),
    "clarke": ("clarke.wiki", extract_shape_a),
    "worldfantasy": ("wf.wiki", extract_shape_a),
    "britishfantasy": ("bfa.wiki", extract_shape_a),
    "locus-fantasy": ("locus.wiki", lambda t: extract_locus(t, "Locus-Fantasy")),
    "locus-sf": ("locus-sf.wiki", lambda t: extract_locus(t, "Locus-SF")),
    "mythopoeic": ("myth.wiki", extract_myth),
}

if __name__ == "__main__":
    for name, (wiki_fn, extractor) in JOBS.items():
        path = os.path.join(RAW, wiki_fn)
        if not os.path.exists(path):
            print(f"skip {name}: {wiki_fn} missing")
            continue
        text = open(path, encoding="utf-8").read()
        write_csv(name, extractor(text))
