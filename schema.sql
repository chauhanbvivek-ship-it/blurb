DROP TABLE IF EXISTS similar_books CASCADE;
DROP TABLE IF EXISTS reviews CASCADE;
DROP TABLE IF EXISTS interactions CASCADE;
DROP TABLE IF EXISTS book_genres CASCADE;
DROP TABLE IF EXISTS genres CASCADE;
DROP TABLE IF EXISTS book_authors CASCADE;
DROP TABLE IF EXISTS authors CASCADE;
DROP TABLE IF EXISTS users CASCADE;
DROP TABLE IF EXISTS books CASCADE;

CREATE TABLE books (
    book_id    BIGINT PRIMARY KEY,
    title      TEXT NOT NULL,
    publisher  TEXT,
    publication_year INTEGER,
    format     TEXT,
    num_pages  INTEGER,
    average_rating NUMERIC(3,2),
    ratings_count  INTEGER
);

CREATE TABLE authors (
    author_id      BIGINT PRIMARY KEY,
    name           TEXT NOT NULL,
    average_rating NUMERIC(3,2),
    ratings_count  INTEGER
);

CREATE TABLE book_authors (
    book_id   BIGINT REFERENCES books(book_id),
    author_id BIGINT REFERENCES authors(author_id),
    PRIMARY KEY (book_id, author_id)
);

CREATE TABLE genres (
    genre_id INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name     TEXT UNIQUE NOT NULL
);

CREATE TABLE book_genres (
    book_id   BIGINT  REFERENCES books(book_id),
    genre_id  INTEGER REFERENCES genres(genre_id),
    tag_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (book_id, genre_id)
);

CREATE TABLE users (
    user_id TEXT PRIMARY KEY
);

CREATE TABLE interactions (
    user_id TEXT    REFERENCES users(user_id),
    book_id BIGINT  REFERENCES books(book_id),
    is_read BOOLEAN,
    rating  SMALLINT CHECK (rating BETWEEN 0 AND 5),
    PRIMARY KEY (user_id, book_id)
);

CREATE TABLE reviews (
    review_id   TEXT PRIMARY KEY,
    user_id     TEXT   REFERENCES users(user_id),
    book_id     BIGINT REFERENCES books(book_id),
    rating      SMALLINT CHECK (rating BETWEEN 0 AND 5),
    review_text TEXT,
    review_date TIMESTAMP,
    n_votes     INTEGER,
    n_comments  INTEGER
);

CREATE TABLE similar_books (
    book_id         BIGINT REFERENCES books(book_id),
    similar_book_id BIGINT REFERENCES books(book_id),
    PRIMARY KEY (book_id, similar_book_id),
    CHECK (book_id <> similar_book_id)
);
