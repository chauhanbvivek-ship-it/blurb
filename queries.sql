-- ============================================================
-- Blurb: Finding Your Next Graphic Novel — Milestone 3 Queries
-- CIS 5500, Fall 2026
-- ============================================================

-- ============================================================
-- SIMPLE QUERIES (1–8)
-- ============================================================

-- Q1  Keyword Title Search (Simple)
-- Finds books whose title contains a keyword (case-insensitive).
SELECT book_id, title, average_rating, ratings_count
FROM books
WHERE LOWER(title) LIKE '%batman%'
ORDER BY ratings_count DESC NULLS LAST
LIMIT 20;


-- Q2  Books by Author (Simple)
-- Lists all books by a given author, ordered by rating.
SELECT b.book_id, b.title, b.average_rating, b.ratings_count
FROM books b
JOIN book_authors ba ON ba.book_id = b.book_id
JOIN authors a      ON a.author_id = ba.author_id
WHERE LOWER(a.name) LIKE '%alan moore%'
ORDER BY b.average_rating DESC NULLS LAST;


-- Q3  Top-Rated Books in a Genre (Simple)
-- Returns the highest-rated books for a given genre with at least N ratings.
SELECT b.book_id, b.title, b.average_rating, b.ratings_count
FROM books b
JOIN book_genres bg ON bg.book_id = b.book_id
JOIN genres g       ON g.genre_id = bg.genre_id
WHERE g.name = 'mystery, thriller, crime'
  AND b.ratings_count >= 100
ORDER BY b.average_rating DESC
LIMIT 20;


-- Q4  Reader Activity Profile (Simple)
-- Summarises a single user's reading activity.
SELECT COUNT(*)                          AS books_touched,
       COUNT(*) FILTER (WHERE is_read)   AS books_read,
       ROUND(AVG(rating) FILTER (WHERE rating > 0), 2) AS avg_rating
FROM interactions
WHERE user_id = '8842281e1d1347389f2ab93d60773d4d';


-- Q5  Most-Reviewed Books (Simple)
-- Books with the most written reviews.
SELECT b.book_id, b.title, COUNT(*) AS review_count,
       ROUND(AVG(r.rating), 2) AS avg_review_rating
FROM reviews r
JOIN books b ON b.book_id = r.book_id
WHERE r.review_text IS NOT NULL
GROUP BY b.book_id, b.title
ORDER BY review_count DESC
LIMIT 20;


-- Q6  Similar Books Lookup (Simple)
-- Returns the similar-books list for a given title.
SELECT s.similar_book_id, b2.title, b2.average_rating
FROM similar_books s
JOIN books b1 ON b1.book_id = s.book_id
JOIN books b2 ON b2.book_id = s.similar_book_id
WHERE LOWER(b1.title) LIKE '%watchmen%'
ORDER BY b2.average_rating DESC;


-- Q7  Publication Year Distribution (Simple)
-- Counts how many books were published each year (recent decades).
SELECT publication_year, COUNT(*) AS num_books
FROM books
WHERE publication_year BETWEEN 1980 AND 2020
GROUP BY publication_year
ORDER BY publication_year;


-- Q8  Prolific Authors (Simple)
-- Authors with the most books in the dataset.
SELECT a.author_id, a.name, COUNT(*) AS book_count,
       ROUND(AVG(b.average_rating), 2) AS avg_book_rating
FROM authors a
JOIN book_authors ba ON ba.author_id = a.author_id
JOIN books b         ON b.book_id = ba.book_id
GROUP BY a.author_id, a.name
ORDER BY book_count DESC
LIMIT 20;


-- ============================================================
-- COMPLEX QUERIES (9–12)
-- ============================================================

-- Q9  Readers Also Loved  (Complex)
-- Collaborative filtering: finds books highly rated by readers who also
-- highly rated the same books as a target user. Uses three self-joins
-- on the 7.3 M-row interactions table, plus CTEs and aggregation.
--
-- Techniques: CTEs, multi-table self-join, NOT IN subquery, aggregation
-- Before optimization (no indexes, no parallel): ~62 s
-- After  optimization (indexes + parallel workers):  ~11 s
WITH my_books AS (
    SELECT book_id FROM interactions
    WHERE user_id = '8842281e1d1347389f2ab93d60773d4d' AND rating >= 4
),
co_readers AS (
    SELECT DISTINCT i2.user_id
    FROM my_books mb
    JOIN interactions i2 ON i2.book_id = mb.book_id
    WHERE i2.user_id <> '8842281e1d1347389f2ab93d60773d4d'
      AND i2.rating >= 4
),
recs AS (
    SELECT i3.book_id, COUNT(*) AS fans
    FROM co_readers cr
    JOIN interactions i3 ON i3.user_id = cr.user_id AND i3.rating >= 4
    WHERE i3.book_id NOT IN (SELECT book_id FROM my_books)
    GROUP BY i3.book_id
)
SELECT r.book_id, b.title, b.average_rating, r.fans
FROM recs r
JOIN books b ON b.book_id = r.book_id
ORDER BY r.fans DESC, b.average_rating DESC
LIMIT 20;


-- Q10  Hidden Gems  (Complex)
-- Finds high-rated books with fewer ratings than the 25th-percentile
-- of their primary genre — i.e., overlooked masterpieces.
--
-- Techniques: PERCENTILE_CONT window, DISTINCT ON, CTE, multi-join
-- Before optimization (naive correlated subquery, no indexes): >600 s
-- After  optimization (CTE rewrite + indexes):                  ~2 s
WITH genre_stats AS (
    SELECT bg.genre_id,
           PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY b.ratings_count) AS p25
    FROM book_genres bg
    JOIN books b ON b.book_id = bg.book_id
    WHERE b.ratings_count IS NOT NULL
    GROUP BY bg.genre_id
),
top_genre AS (
    SELECT DISTINCT ON (bg.book_id) bg.book_id, bg.genre_id
    FROM book_genres bg
    ORDER BY bg.book_id, bg.tag_count DESC, bg.genre_id
)
SELECT b.book_id, b.title, b.average_rating, b.ratings_count,
       g.name AS genre
FROM books b
JOIN top_genre tg ON tg.book_id = b.book_id
JOIN genre_stats gs ON gs.genre_id = tg.genre_id
JOIN genres g ON g.genre_id = tg.genre_id
WHERE b.average_rating >= 4.30
  AND b.ratings_count IS NOT NULL
  AND b.ratings_count < gs.p25
ORDER BY b.average_rating DESC, b.ratings_count ASC
LIMIT 50;


-- Q11  Divisive Books  (Complex)
-- Finds books with the highest rating standard deviation — titles that
-- polarise readers. Uses STDDEV, FILTER, and RANK.
--
-- Techniques: STDDEV, FILTER, RANK() window, HAVING, subquery
-- Before optimization (no indexes, no parallel): ~10 s
-- After  optimization (indexes + parallel):       ~3 s
SELECT ranked.*
FROM (
    SELECT b.book_id, b.title,
           ROUND(STDDEV(i.rating), 3)                           AS rating_sd,
           COUNT(*)                                              AS num_ratings,
           COUNT(*) FILTER (WHERE i.rating >= 4)                 AS fans,
           COUNT(*) FILTER (WHERE i.rating <= 2)                 AS haters,
           RANK() OVER (ORDER BY STDDEV(i.rating) DESC NULLS LAST) AS sd_rank
    FROM interactions i
    JOIN books b ON b.book_id = i.book_id
    WHERE i.rating > 0
    GROUP BY b.book_id, b.title
    HAVING COUNT(*) >= 50
) ranked
WHERE sd_rank <= 25
ORDER BY sd_rank;


-- Q12  Tough Critics  (Complex)
-- Identifies reviewers whose average review rating is significantly below
-- the book's community average, using correlated aggregation and NOT EXISTS
-- to restrict to users without any 5-star reviews.
--
-- Techniques: correlated subquery (AVG per book), NOT EXISTS, HAVING
-- Before optimization (no indexes): ~2.4 s
-- After  optimization (indexes):    ~1.4 s
SELECT r.user_id,
       COUNT(*)                        AS reviews_written,
       ROUND(AVG(r.rating), 2)        AS avg_given,
       ROUND(AVG(b.average_rating), 2) AS avg_community,
       ROUND(AVG(b.average_rating) - AVG(r.rating), 2) AS gap
FROM reviews r
JOIN books b ON b.book_id = r.book_id
WHERE r.rating > 0
  AND NOT EXISTS (
      SELECT 1 FROM reviews r2
      WHERE r2.user_id = r.user_id AND r2.rating = 5
  )
GROUP BY r.user_id
HAVING COUNT(*) >= 10
ORDER BY gap DESC
LIMIT 25;
