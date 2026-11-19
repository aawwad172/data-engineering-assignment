"""Load data/articles.csv (made by collect.py) into MongoDB.

Run:
    python load.py          (or: make run FILE=load.py)

Safe to re-run: articles are matched by page_id, so running it again updates
existing articles instead of creating duplicates. MongoDB must be running
(docker compose up -d).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from article_repository import ArticleRepository
from collect import CSV_PATH
from db_context import DbContext

# Stored as real dates in MongoDB (not text), so you can sort and filter by date.
DATE_COLUMNS = ["last_edited", "scraped_at"]

log = logging.getLogger("load")


def read_articles(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise SystemExit(f"{path} not found. Run collect.py first.")
    df = pd.read_csv(path)
    for column in DATE_COLUMNS:
        df[column] = pd.to_datetime(df[column], utc=True)
    log.info("Read %d articles from %s", len(df), path)
    return df


def to_documents(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Turn DataFrame rows into MongoDB documents (plain Python values, no NaN)."""
    loaded_at = datetime.now(timezone.utc)
    documents = []
    for row in df.to_dict("records"):
        doc = {key: (None if _is_missing(value) else value) for key, value in row.items()}
        for column in DATE_COLUMNS:
            if doc[column] is not None:
                doc[column] = doc[column].to_pydatetime()
        doc["loaded_at"] = loaded_at
        documents.append(doc)
    return documents


def _is_missing(value: Any) -> bool:
    return not isinstance(value, (list, dict)) and pd.isna(value)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    df = read_articles(CSV_PATH)
    documents = to_documents(df)

    with DbContext() as context:
        repo = ArticleRepository(context)
        repo.ensure_indexes()
        summary = repo.bulk_upsert(documents)

        page_ids = df["page_id"].tolist()
        stored = repo.count({ArticleRepository.KEY: {"$in": page_ids}})
        total = repo.count()

    print(f"\nCSV rows:          {len(df)}")
    print(f"Inserted:          {summary.inserted}")
    print(f"Updated:           {summary.updated}")
    print(f"Unchanged:         {summary.unchanged}")
    print(f"Total in MongoDB:  {total}")

    if stored != len(df):
        raise AssertionError(f"Only {stored} of {len(df)} CSV articles are in MongoDB.")


if __name__ == "__main__":
    main()
