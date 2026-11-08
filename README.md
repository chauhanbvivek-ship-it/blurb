# Blurb: Finding Your Next Graphic Novel

**CIS 5500 — Database & Information Systems, Fall 2026**

Team: Angie Choi, Vivek Chauhan, Mariya Siddiqui, Sunni Lowe

---

## Overview

Blurb helps readers discover graphic novels and comics through data-driven recommendations. The application is backed by the [UCSD Goodreads Book Graph](https://mengtingwan.github.io/data/goodreads.html) (Comics & Graphic subset), which contains:

| Table | Rows |
|---|---|
| books | 89,311 |
| authors | 39,551 |
| book_authors | 107,425 |
| genres | 38 |
| book_genres | 298,012 |
| users | 603,668 |
| interactions | 7,322,579 |
| reviews | 542,070 |
| similar_books | 393,562 |

## Database

- **Engine:** PostgreSQL 16 on AWS RDS (`db.t4g.micro`, `us-east-1`)
- **Host:** `database-1.cwfuy7jt6vft.us-east-1.rds.amazonaws.com`
- **Database:** `blurb`
- **Read-only credentials:** user `grader` / password `BlurbGuest2026`

## Schema

See [`schema.sql`](schema.sql) for the full DDL. The ER diagram is in [`er_diagram.svg`](er_diagram.svg).

**9 tables** in 3NF:
- `books` — one row per book (89K)
- `authors` — one row per author (40K)
- `book_authors` — many-to-many junction
- `genres` / `book_genres` — genre tags with tag counts
- `users` — reader identifiers (anonymised 32-char hex hashes)
- `interactions` — 7.3M user–book events (read flag + 0–5 rating)
- `reviews` — 542K written reviews with votes and comments
- `similar_books` — Goodreads "readers also enjoyed" edges

## Data Cleaning & Entity Resolution

The raw dataset is five gzip-compressed JSON files (one JSON object per line). The ETL script [`load_data.py`](load_data.py) handles all cleaning:

1. **Type coercion** — Every numeric field in the source JSON is a string. The ETL converts to `INT`, `BIGINT`, `NUMERIC`, or `FLOAT` as appropriate. Empty strings become `NULL`.

2. **Deduplication** — Books, authors, interactions, and reviews are deduplicated by their primary key during load. For interactions, duplicate `(user_id, book_id)` pairs are dropped (the first occurrence wins).

3. **Foreign-key integrity** — Tables are loaded in dependency order (books → authors → book_authors → genres → users → interactions → reviews → similar_books). Authors that don't appear in any book's author list are excluded. Reviews referencing unknown users are skipped. Similar-book edges where either endpoint is outside the comics subset are dropped.

4. **Nested-object extraction** — Author IDs and similar-book IDs are embedded inside book JSON objects as nested arrays. The ETL extracts them during the books pass and loads the junction tables afterward.

5. **Date parsing** — Review dates arrive as `"Wed Sep 06 00:00:00 -0700 2017"` and are normalised to `TIMESTAMP` format.

6. **Streaming bulk load** — The 7.3M-row interactions file is streamed in batches of 500K rows using PostgreSQL `COPY` (tab-separated, `\N` for NULLs) to avoid loading the entire file into memory.

## How to Reproduce the Database

```bash
# 1. Install dependencies
pip install psycopg2-binary requests

# 2. Download the raw data (~1.5 GB)
python download_goodreads.py          # saves to ./data/

# 3. Set connection env vars (or edit defaults in load_data.py)
export RDS_HOST="database-1.cwfuy7jt6vft.us-east-1.rds.amazonaws.com"
export RDS_PASS="<password>"

# 4. Create schema
psql "$CONNECTION_STRING" -f schema.sql

# 5. Run ETL (~15 min on a laptop)
python load_data.py
```

## Queries

All 12 queries are in [`queries.sql`](queries.sql): 8 simple, 4 complex.

### Complex Queries — Optimization Summary

| # | Name | Techniques | Before | After | Speedup |
|---|---|---|---|---|---|
| Q3 | Readers Also Loved | Self-join, COUNT(DISTINCT), GROUP BY, HAVING, MATERIALIZED CTE | 53.348 ms | 21.239 ms | 2.5× |
| Q4 | Hidden Gems | PERCENTILE_CONT, DISTINCT ON, CTEs, multi-table joins | 28.924 s | 0.437 s | 66.2× |
| Q5 | Top-Rated Authors | COUNT, AVG, LATERAL JOIN, MATERIALIZED CTE, aggregation optimization | 487.608 ms | 364.421 ms | 1.3× |
| Q11 | Divisive Books | STDDEV, FILTER, RANK(), HAVING, index-only scan | 18.298 s | 1.030 s | 17.8× |

**"Before" conditions:** all custom indexes dropped, `max_parallel_workers_per_gather = 0`, `enable_hashjoin = off`.

**"After" conditions:** custom indexes created (see below), default parallelism and join settings.

### Indexes

```sql
-- Partial indexes
CREATE INDEX idx_interactions_rating_user_book ON interactions (rating, user_id, book_id) WHERE rating >= 4;
CREATE INDEX idx_reviews_book_engagement ON reviews (book_id, n_votes DESC, n_comments DESC) WHERE review_text IS NOT NULL;
CREATE INDEX idx_books_pubyear ON books (publication_year) WHERE publication_year IS NOT NULL;

-- Expression index
CREATE INDEX idx_books_title_lower ON books (LOWER(title) text_pattern_ops);

-- Covering / composite indexes
CREATE INDEX idx_book_genres_book_tagcount ON book_genres (book_id, tag_count DESC, genre_id);
CREATE INDEX idx_book_authors_author ON book_authors (author_id, book_id);
CREATE INDEX idx_interactions_book_rating ON interactions (book_id, rating);

-- Single-column FK indexes
CREATE INDEX idx_interactions_user ON interactions (user_id);
CREATE INDEX idx_reviews_book ON reviews (book_id);
CREATE INDEX idx_book_genres_genre ON book_genres (genre_id);
CREATE INDEX idx_similar_books_target ON similar_books (similar_book_id);
CREATE INDEX idx_books_title ON books (title);
```

## Repository Structure

```
├── README.md              ← this file
├── schema.sql             ← DDL (CREATE TABLE statements)
├── queries.sql            ← all 12 queries with comments
├── er_diagram.svg         ← entity-relationship diagram
├── load_data.py           ← streaming ETL pipeline
├── download_goodreads.py  ← dataset download helper
├── .gitignore             ← excludes data/, .env, etc.
└── data/                  ← raw JSON files (not committed)
```
