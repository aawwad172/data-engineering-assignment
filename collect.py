"""Collect English Wikipedia articles about health and diseases into a CSV.

Pipeline:
    Phase 1 - Walk the category tree (breadth-first) to find article page IDs.
    Phase 2 - Fetch each article's intro text and metadata in batches of 20,
              saving every batch to a JSONL checkpoint file right away.
    Phase 3 - Clean, dedupe and export the result to CSV.

Run:
    python collect.py          (or: make run FILE=collect.py)

It is safe to stop (Ctrl+C) and re-run: pages already in the checkpoint
file are skipped. Only the MediaWiki Action API is used, no HTML scraping.
All HTTP details (retries, continuation, rate limiting) live in
wikipedia_client.py.
"""

from __future__ import annotations

import json
import logging
import os
from collections import deque
from collections.abc import Iterable, Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
from dotenv import load_dotenv

from wikipedia_client import MAX_PAGES_PER_REQUEST, WikipediaClient

# ---------------------------------------------------------------------------
# Config (HTTP settings like the API URL, retries and pauses live in
# wikipedia_client.py)
# ---------------------------------------------------------------------------

# Filled in with CONTACT_EMAIL from .env, as Wikipedia's User-Agent policy asks.
USER_AGENT_TEMPLATE = "PSUT-DataEngineering-Assignment/1.0 ({contact})"

ROOT_CATEGORIES = [
    "Category:Diseases and disorders",
    "Category:Infectious diseases",
    "Category:Medical conditions",
    "Category:Symptoms and signs",
]

MAX_DEPTH = 3          # root categories are depth 0
TARGET_RAW = 8500      # stop category traversal after this many article IDs
MIN_WORDS = 30         # drop articles whose summary is shorter than this
MIN_FINAL_ROWS = 7000  # the assignment's minimum row count
BATCH_SIZE = MAX_PAGES_PER_REQUEST  # 20 page IDs per request

BASE_DIR = Path(__file__).resolve().parent
RAW_PATH = BASE_DIR / "data" / "raw" / "articles.jsonl"
CSV_PATH = BASE_DIR / "data" / "articles.csv"

COLUMNS = [
    "page_id",
    "title",
    "url",
    "summary",
    "source_category",
    "category_depth",
    "word_count",
    "char_count",
    "page_length_bytes",
    "last_edited",
    "scraped_at",
]

log = logging.getLogger("collect")


def get_user_agent() -> str:
    """Build the User-Agent from CONTACT_EMAIL in .env, or stop with a clear message."""
    load_dotenv()
    contact = os.getenv("CONTACT_EMAIL", "").strip()
    if not contact:
        raise SystemExit(
            "CONTACT_EMAIL is not set. Wikipedia asks API clients to put contact info "
            "in the User-Agent.\nAdd a line like `CONTACT_EMAIL=you@example.com` to .env "
            "(see .env.example)."
        )
    return USER_AGENT_TEMPLATE.format(contact=contact)


def make_client() -> WikipediaClient:
    return WikipediaClient(user_agent=get_user_agent())


# ---------------------------------------------------------------------------
# Phase 1 - category traversal
# ---------------------------------------------------------------------------


def discover_articles(client: WikipediaClient) -> dict[int, dict[str, Any]]:
    """BFS over the category tree.

    Returns {page_id: {"source_category": ..., "category_depth": ...}}, where the
    category is the first one the article was found in.
    """
    articles: dict[int, dict[str, Any]] = {}
    visited: set[str] = set(ROOT_CATEGORIES)
    queue: deque[tuple[str, int]] = deque((cat, 0) for cat in ROOT_CATEGORIES)
    categories_done = 0

    while queue and len(articles) < TARGET_RAW:
        category, depth = queue.popleft()
        for member in client.category_members(category):
            if member["ns"] == 0:
                articles.setdefault(
                    member["pageid"], {"source_category": category, "category_depth": depth}
                )
                if len(articles) >= TARGET_RAW:
                    break
            elif member["ns"] == 14 and depth < MAX_DEPTH and member["title"] not in visited:
                visited.add(member["title"])
                queue.append((member["title"], depth + 1))

        categories_done += 1
        if categories_done % 25 == 0:
            log.info(
                "Phase 1: %d categories visited, %d queued, %d articles found (depth %d)",
                categories_done, len(queue), len(articles), depth,
            )

    log.info("Phase 1 done: %d categories visited, %d articles found", categories_done, len(articles))
    return articles


# ---------------------------------------------------------------------------
# Phase 2 - batch fetch with JSONL checkpoint
# ---------------------------------------------------------------------------


def chunked(items: list[int], size: int) -> Iterator[list[int]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def build_record(page: dict[str, Any], meta: dict[str, Any]) -> dict[str, Any]:
    summary = (page.get("extract") or "").strip()
    revisions = page.get("revisions") or [{}]
    return {
        "page_id": page["pageid"],
        "title": page.get("title", ""),
        "url": page.get("fullurl", ""),
        "summary": summary,
        "source_category": meta["source_category"],
        "category_depth": meta["category_depth"],
        "word_count": len(summary.split()),
        "char_count": len(summary),
        "page_length_bytes": page.get("length"),
        "last_edited": revisions[0].get("timestamp"),
        "scraped_at": utc_now_iso(),
    }


def read_checkpoint(path: Path) -> list[dict[str, Any]]:
    """Read all records from the JSONL file. Skips broken lines (e.g. from a crash)."""
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                log.warning("Skipping broken line %d in %s", line_no, path)
    return records


def append_checkpoint(path: Path, records: Iterable[dict[str, Any]]) -> None:
    """Append records as JSON lines and flush to disk immediately."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # If a previous run crashed mid-line, start on a fresh line so we don't
    # glue a new record onto the broken one.
    needs_newline = False
    if path.exists() and path.stat().st_size > 0:
        with path.open("rb") as f:
            f.seek(-1, os.SEEK_END)
            needs_newline = f.read(1) != b"\n"
    text = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)
    with path.open("a", encoding="utf-8") as f:
        f.write(("\n" if needs_newline else "") + text)
        f.flush()
        os.fsync(f.fileno())


def fetch_articles(client: WikipediaClient, articles: dict[int, dict[str, Any]]) -> None:
    done = {r["page_id"] for r in read_checkpoint(RAW_PATH)}
    todo = [pid for pid in articles if pid not in done]
    total_batches = (len(todo) + BATCH_SIZE - 1) // BATCH_SIZE
    log.info("Phase 2: %d already fetched, %d to fetch in %d batches", len(done), len(todo), total_batches)

    for i, batch in enumerate(chunked(todo, BATCH_SIZE), start=1):
        pages = client.fetch_pages(batch)
        records = [build_record(pages[pid], articles[pid]) for pid in batch if pid in pages]
        append_checkpoint(RAW_PATH, records)
        if i % 10 == 0 or i == total_batches:
            log.info("Phase 2: batch %d/%d saved", i, total_batches)

    log.info("Phase 2 done")


# ---------------------------------------------------------------------------
# Phase 3 - clean and export
# ---------------------------------------------------------------------------


def clean_and_export(records: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(records, columns=COLUMNS)
    raw_count = len(df)

    too_short = df["word_count"] < MIN_WORDS
    is_list = df["title"].str.startswith("List of")
    is_disambiguation = df["summary"].str.contains("may refer to:", case=False, regex=False)
    log.info(
        "Phase 3: dropping %d too short (<%d words), %d 'List of', %d disambiguation",
        too_short.sum(), MIN_WORDS, is_list.sum(), is_disambiguation.sum(),
    )

    df = df[~(too_short | is_list | is_disambiguation)]
    df = df.drop_duplicates(subset="page_id", keep="first").reset_index(drop=True)

    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(CSV_PATH, index=False, encoding="utf-8")

    print(f"\nRaw records:  {raw_count}")
    print(f"Final rows:   {len(df)}")
    print(f"Columns:      {list(df.columns)}")
    print(f"Saved to:     {CSV_PATH}")

    if len(df) < MIN_FINAL_ROWS:
        raise AssertionError(
            f"Only {len(df)} rows after cleaning, need at least {MIN_FINAL_ROWS}. "
            f"Try raising MAX_DEPTH (now {MAX_DEPTH}) or TARGET_RAW (now {TARGET_RAW}), "
            "or adding more ROOT_CATEGORIES, then re-run (fetched pages are kept)."
        )
    return df


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    with make_client() as client:
        articles = discover_articles(client)
        fetch_articles(client, articles)
    clean_and_export(read_checkpoint(RAW_PATH))


if __name__ == "__main__":
    main()
