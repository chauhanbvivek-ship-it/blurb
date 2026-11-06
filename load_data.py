"""
ETL script: stream Goodreads JSON → CSV → PostgreSQL COPY.
Run:  python3 load_data.py
"""

import csv
import gzip
import io
import json
import os
import sys
from datetime import datetime

import psycopg2

DATA = os.path.join(os.path.dirname(__file__), "data")

def connect():
    return psycopg2.connect(
        host=os.environ.get("RDS_HOST", "database-1.cwfuy7jt6vft.us-east-1.rds.amazonaws.com"),
        port=os.environ.get("RDS_PORT", "5432"),
        dbname=os.environ.get("RDS_DB", "blurb"),
        user=os.environ.get("RDS_USER", "postgres"),
        password=os.environ.get("RDS_PASS", ""),
        sslmode="require",
    )

def safe_int(v):
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None

def safe_float(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None

def safe_str(v):
    if v is None or v == "":
        return None
    return str(v).strip() or None

def parse_date(s):
    if not s or not s.strip():
        return None
    try:
        return datetime.strptime(s.strip(), "%a %b %d %H:%M:%S %z %Y").strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None

def copy_from_rows(cur, table, columns, rows):
    buf = io.StringIO()
    count = 0
    for row in rows:
        parts = []
        for v in row:
            if v is None:
                parts.append("\\N")
            else:
                parts.append(str(v).replace("\\", "\\\\").replace("\t", " ").replace("\n", " ").replace("\r", ""))
        buf.write("\t".join(parts) + "\n")
        count += 1
    buf.seek(0)
    cur.copy_from(buf, table, columns=columns, null="\\N")
    return count

def load_books(cur):
    print("Loading books...")
    book_ids = set()
    book_authors_rows = []
    similar_rows = []

    def rows():
        with gzip.open(os.path.join(DATA, "goodreads_books_comics_graphic.json.gz"), "rt") as f:
            for line in f:
                obj = json.loads(line)
                bid = safe_int(obj.get("book_id"))
                if bid is None or bid in book_ids:
                    continue
                book_ids.add(bid)
                for a in obj.get("authors", []):
                    aid = safe_int(a.get("author_id"))
                    if aid:
                        book_authors_rows.append((bid, aid))
                for sb in obj.get("similar_books", []):
                    sbid = safe_int(sb)
                    if sbid and sbid != bid:
                        similar_rows.append((bid, sbid))
                yield (
                    bid,
                    safe_str(obj.get("title")) or "Untitled",
                    safe_str(obj.get("publisher")),
                    safe_int(obj.get("publication_year")),
                    safe_str(obj.get("format")),
                    safe_int(obj.get("num_pages")),
                    safe_float(obj.get("average_rating")),
                    safe_int(obj.get("ratings_count")),
                )

    n = copy_from_rows(cur, "books",
        ["book_id", "title", "publisher", "publication_year", "format", "num_pages", "average_rating", "ratings_count"],
        rows())
    print(f"  books: {n}")
    return book_ids, book_authors_rows, similar_rows

def load_authors(cur, needed_ids):
    print("Loading authors...")
    seen = set()
    def rows():
        with gzip.open(os.path.join(DATA, "goodreads_book_authors.json.gz"), "rt") as f:
            for line in f:
                obj = json.loads(line)
                aid = safe_int(obj.get("author_id"))
                if aid is None or aid in seen or aid not in needed_ids:
                    continue
                seen.add(aid)
                yield (
                    aid,
                    safe_str(obj.get("name")) or "Unknown",
                    safe_float(obj.get("average_rating")),
                    safe_int(obj.get("ratings_count")),
                )
    n = copy_from_rows(cur, "authors",
        ["author_id", "name", "average_rating", "ratings_count"], rows())
    print(f"  authors: {n}")
    return seen

def load_book_authors(cur, pairs, valid_authors):
    print("Loading book_authors...")
    seen = set()
    def rows():
        for bid, aid in pairs:
            if aid in valid_authors and (bid, aid) not in seen:
                seen.add((bid, aid))
                yield (bid, aid)
    n = copy_from_rows(cur, "book_authors", ["book_id", "author_id"], rows())
    print(f"  book_authors: {n}")

def load_genres(cur, book_ids):
    print("Loading genres...")
    genre_map = {}
    bg_rows = []
    with gzip.open(os.path.join(DATA, "goodreads_book_genres_initial.json.gz"), "rt") as f:
        for line in f:
            obj = json.loads(line)
            bid = safe_int(obj.get("book_id"))
            if bid is None or bid not in book_ids:
                continue
            for gname, count in obj.get("genres", {}).items():
                gname = gname.strip()
                if not gname:
                    continue
                if gname not in genre_map:
                    genre_map[gname] = len(genre_map) + 1
                bg_rows.append((bid, genre_map[gname], safe_int(count) or 0))

    genre_rows = [(gid, name) for name, gid in genre_map.items()]
    n = copy_from_rows(cur, "genres", ["genre_id", "name"],
        ((gid, name) for gid, name in genre_rows))
    print(f"  genres: {n}")

    # Reset the identity sequence past our manual IDs
    cur.execute(f"SELECT setval('genres_genre_id_seq', {len(genre_map) + 1})")

    seen = set()
    def unique_bg():
        for bid, gid, tc in bg_rows:
            if (bid, gid) not in seen:
                seen.add((bid, gid))
                yield (bid, gid, tc)
    n = copy_from_rows(cur, "book_genres", ["book_id", "genre_id", "tag_count"], unique_bg())
    print(f"  book_genres: {n}")

def load_users_and_interactions(cur, book_ids):
    print("Loading interactions (streaming)...")
    user_ids = set()
    interaction_seen = set()
    interaction_buf = []
    BATCH = 500_000

    def flush_interactions():
        if not interaction_buf:
            return 0
        new_users = []
        for uid in set(r[0] for r in interaction_buf):
            if uid not in user_ids:
                user_ids.add(uid)
                new_users.append((uid,))
        if new_users:
            copy_from_rows(cur, "users", ["user_id"], new_users)
        n = copy_from_rows(cur, "interactions",
            ["user_id", "book_id", "is_read", "rating"], interaction_buf)
        interaction_buf.clear()
        return n

    total = 0
    skipped_dup = 0
    with gzip.open(os.path.join(DATA, "goodreads_interactions_comics_graphic.json.gz"), "rt") as f:
        for line in f:
            obj = json.loads(line)
            bid = safe_int(obj.get("book_id"))
            uid = obj.get("user_id", "").strip()
            if not uid or bid is None or bid not in book_ids:
                continue
            if (uid, bid) in interaction_seen:
                skipped_dup += 1
                continue
            interaction_seen.add((uid, bid))
            interaction_buf.append((
                uid, bid,
                obj.get("is_read") in (True, "true", "True"),
                safe_int(obj.get("rating")) or 0,
            ))
            if len(interaction_buf) >= BATCH:
                total += flush_interactions()
                print(f"    ... {total:,} interactions loaded")

    total += flush_interactions()
    print(f"  interactions: {total:,} (skipped {skipped_dup:,} duplicates)")
    print(f"  users: {len(user_ids):,}")
    return user_ids

def load_reviews(cur, book_ids, user_ids):
    print("Loading reviews...")
    seen = set()
    skipped_no_user = 0
    def rows():
        nonlocal skipped_no_user
        with gzip.open(os.path.join(DATA, "goodreads_reviews_comics_graphic.json.gz"), "rt") as f:
            for line in f:
                obj = json.loads(line)
                rid = obj.get("review_id", "").strip()
                bid = safe_int(obj.get("book_id"))
                uid = obj.get("user_id", "").strip()
                if not rid or not uid or bid is None or bid not in book_ids:
                    continue
                if rid in seen:
                    continue
                seen.add(rid)
                if uid not in user_ids:
                    skipped_no_user += 1
                    continue
                yield (
                    rid, uid, bid,
                    safe_int(obj.get("rating")) or 0,
                    safe_str(obj.get("review_text")),
                    parse_date(obj.get("date_added")),
                    safe_int(obj.get("n_votes")),
                    safe_int(obj.get("n_comments")),
                )
    n = copy_from_rows(cur, "reviews",
        ["review_id", "user_id", "book_id", "rating", "review_text", "review_date", "n_votes", "n_comments"],
        rows())
    print(f"  reviews: {n:,} (skipped {skipped_no_user:,} with no matching user)")

def load_similar_books(cur, pairs, book_ids):
    print("Loading similar_books...")
    seen = set()
    def rows():
        for bid, sbid in pairs:
            if sbid in book_ids and (bid, sbid) not in seen:
                seen.add((bid, sbid))
                yield (bid, sbid)
    n = copy_from_rows(cur, "similar_books", ["book_id", "similar_book_id"], rows())
    print(f"  similar_books: {n:,}")

def create_indexes(cur):
    print("Creating indexes...")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_books_title ON books (title);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_interactions_book_rating ON interactions (book_id, rating);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_interactions_user ON interactions (user_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_reviews_book ON reviews (book_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_book_genres_genre ON book_genres (genre_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_similar_books_target ON similar_books (similar_book_id);")
    print("  done")

def main():
    conn = connect()
    conn.autocommit = False
    cur = conn.cursor()
    try:
        book_ids, ba_pairs, sim_pairs = load_books(cur)
        conn.commit()

        needed_author_ids = set(aid for _, aid in ba_pairs)
        valid_authors = load_authors(cur, needed_author_ids)
        conn.commit()

        load_book_authors(cur, ba_pairs, valid_authors)
        conn.commit()

        load_genres(cur, book_ids)
        conn.commit()

        user_ids = load_users_and_interactions(cur, book_ids)
        conn.commit()

        load_reviews(cur, book_ids, user_ids)
        conn.commit()

        load_similar_books(cur, sim_pairs, book_ids)
        conn.commit()

        create_indexes(cur)
        conn.commit()

        print("\nVerifying row counts...")
        for t in ["books", "authors", "book_authors", "genres", "book_genres",
                   "users", "interactions", "reviews", "similar_books"]:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            print(f"  {t}: {cur.fetchone()[0]:,}")

        print("\nDone!")
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    main()
