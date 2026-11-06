"""
Download the five UCSD Goodreads files our project needs.

Usage:
    pip install requests
    python download_goodreads.py                 # saves into ./data
    python download_goodreads.py --genre poetry  # a different genre subset

Skips files that are already fully downloaded, so it is safe to re-run
if your connection drops.
"""
import argparse, os, sys
import requests

BASE = "https://mcauleylab.ucsd.edu/public_datasets/gdrive/goodreads/"


def files_for(genre):
    return [
        ("byGenre/", f"goodreads_books_{genre}.json.gz"),
        ("byGenre/", f"goodreads_interactions_{genre}.json.gz"),
        ("byGenre/", f"goodreads_reviews_{genre}.json.gz"),
        ("",         "goodreads_book_authors.json.gz"),
        ("",         "goodreads_book_genres_initial.json.gz"),
    ]


def download(url, dest):
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        if total and os.path.exists(dest) and os.path.getsize(dest) == total:
            print(f"  already have {os.path.basename(dest)}, skipping")
            return
        done = 0
        tmp = dest + ".part"
        with open(tmp, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
                done += len(chunk)
                if total:
                    pct = 100 * done / total
                    print(f"\r  {done / 1e6:8.1f} / {total / 1e6:.1f} MB ({pct:5.1f}%)", end="", flush=True)
        os.replace(tmp, dest)
        print(f"\r  saved {os.path.basename(dest)} ({done / 1e6:.1f} MB)" + " " * 20)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--genre", default="comics_graphic")
    ap.add_argument("--dir", default="./data")
    a = ap.parse_args()
    os.makedirs(a.dir, exist_ok=True)

    failed = []
    for folder, name in files_for(a.genre):
        print(f"{name}")
        try:
            download(BASE + folder + name, os.path.join(a.dir, name))
        except Exception as e:
            print(f"\n  FAILED: {e}")
            failed.append(name)

    if failed:
        sys.exit("\nSome downloads failed (re-run to retry): " + ", ".join(failed))
    print(f"\nAll files are in {os.path.abspath(a.dir)}")


if __name__ == "__main__":
    main()
