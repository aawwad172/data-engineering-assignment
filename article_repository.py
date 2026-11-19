"""The single way to read and write Wikipedia articles in MongoDB.

Usage:
    from db_context import DbContext
    from article_repository import ArticleRepository

    context = DbContext()
    repo = ArticleRepository(context)
    repo.bulk_upsert(documents)          # load / re-load data
    repo.count({"category_depth": 0})    # how many root-category articles?
    repo.aggregate([{"$group": {"_id": "$source_category", "n": {"$sum": 1}}}])
    df = repo.to_dataframe()             # everything as a pandas DataFrame
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd
from pymongo import ReplaceOne
from pymongo.collection import Collection
from pymongo.errors import BulkWriteError

from db_context import DbContext

log = logging.getLogger(__name__)

Document = dict[str, Any]
DUPLICATE_KEY_ERROR = 11000


@dataclass
class BulkWriteSummary:
    """What a bulk write did. Example: BulkWriteSummary(inserted=7219, updated=0, ...)."""

    inserted: int = 0    # new documents added
    updated: int = 0     # existing documents whose content changed
    unchanged: int = 0   # existing documents that were already identical
    duplicates: int = 0  # documents skipped because their page_id already existed


class ArticleRepository:
    KEY = "page_id"  # each article is identified by its Wikipedia page ID

    def __init__(self, context: DbContext) -> None:
        self.collection: Collection = context.articles

    # ---- setup ----

    def ensure_indexes(self) -> None:
        """Create indexes. Safe to call many times (existing indexes are kept).

        The unique index on page_id makes MongoDB itself refuse duplicate articles.
        """
        self.collection.create_index(self.KEY, unique=True)
        self.collection.create_index("source_category")

    # ---- writes ----

    def bulk_insert(self, documents: Iterable[Document], batch_size: int = 1000) -> BulkWriteSummary:
        """Insert many documents using MongoDB's insert_many.

        Articles whose page_id is already stored are skipped (counted as duplicates),
        not overwritten. Use bulk_upsert if you want existing ones updated.
        """
        summary = BulkWriteSummary()
        for batch in _chunked(documents, batch_size):
            # Copy each dict: insert_many adds an "_id" key to whatever it is given.
            batch = [dict(doc) for doc in batch]
            try:
                result = self.collection.insert_many(batch, ordered=False)
                summary.inserted += len(result.inserted_ids)
            except BulkWriteError as exc:
                details = exc.details
                errors = details.get("writeErrors", [])
                if any(err["code"] != DUPLICATE_KEY_ERROR for err in errors):
                    raise
                summary.inserted += details.get("nInserted", 0)
                summary.duplicates += len(errors)
        log.info("bulk_insert: %s", summary)
        return summary

    def bulk_upsert(self, documents: Iterable[Document], batch_size: int = 1000) -> BulkWriteSummary:
        """Insert new articles and replace existing ones (matched by page_id).

        Uses MongoDB's bulk_write, which sends many operations in one request.
        Running it twice with the same data does not create duplicates.
        """
        summary = BulkWriteSummary()
        for batch in _chunked(documents, batch_size):
            operations = [ReplaceOne({self.KEY: doc[self.KEY]}, doc, upsert=True) for doc in batch]
            result = self.collection.bulk_write(operations, ordered=False)
            summary.inserted += result.upserted_count
            summary.updated += result.modified_count
            summary.unchanged += result.matched_count - result.modified_count
        log.info("bulk_upsert: %s", summary)
        return summary

    def delete_all(self) -> int:
        """Delete every article. Returns how many were deleted."""
        return self.collection.delete_many({}).deleted_count

    # ---- reads ----

    def count(self, filter: Mapping[str, Any] | None = None) -> int:
        return self.collection.count_documents(filter or {})

    def find_by_page_id(self, page_id: int) -> Document | None:
        return self.collection.find_one({self.KEY: page_id}, {"_id": 0})

    def find(
        self,
        filter: Mapping[str, Any] | None = None,
        projection: Mapping[str, Any] | None = None,
        sort: Sequence[tuple[str, int]] | None = None,
        limit: int = 0,
    ) -> list[Document]:
        """Find articles. Example: repo.find({"word_count": {"$gt": 500}}, limit=10)."""
        cursor = self.collection.find(filter or {}, _without_id(projection))
        if sort:
            cursor = cursor.sort(list(sort))
        if limit:
            cursor = cursor.limit(limit)
        return list(cursor)

    def aggregate(self, pipeline: Sequence[Mapping[str, Any]]) -> list[Document]:
        """Run an aggregation pipeline (MongoDB's group-by / stats queries)."""
        return list(self.collection.aggregate(list(pipeline)))

    def to_dataframe(
        self,
        filter: Mapping[str, Any] | None = None,
        projection: Mapping[str, Any] | None = None,
        limit: int = 0,
    ) -> pd.DataFrame:
        """Load matching articles into a pandas DataFrame."""
        return pd.DataFrame(self.find(filter, projection, limit=limit))


def _without_id(projection: Mapping[str, Any] | None) -> dict[str, Any]:
    """Hide MongoDB's internal _id unless the caller asks for it."""
    result = dict(projection or {})
    result.setdefault("_id", 0)
    return result


def _chunked(items: Iterable[Document], size: int) -> Iterator[list[Document]]:
    batch: list[Document] = []
    for item in items:
        batch.append(item)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch
