"""MongoDB connection, wrapped in a DbContext class.

Create one DbContext and pass it to every repository, so they all share the
same connection:

    from db_context import DbContext
    from article_repository import ArticleRepository

    with DbContext() as context:
        articles = ArticleRepository(context)
        print(articles.count())
"""

from __future__ import annotations

import os
from types import TracebackType

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database


class DbContext:
    """Owns the connection to MongoDB and gives access to its collections.

    By default it reads MONGO_URI and MONGO_DB from .env. You can pass them in
    instead, e.g. DbContext(db_name="test_db") to work on a separate database.
    """

    ARTICLES = "articles"

    def __init__(
        self,
        uri: str | None = None,
        db_name: str | None = None,
        timeout_ms: int = 5000,
    ) -> None:
        load_dotenv()
        uri = uri or os.getenv("MONGO_URI")
        db_name = db_name or os.getenv("MONGO_DB")
        if not uri or not db_name:
            raise RuntimeError(
                "MONGO_URI and MONGO_DB must be set. Copy .env.example to .env and fill them in."
            )

        self.client: MongoClient = MongoClient(uri, serverSelectionTimeoutMS=timeout_ms)
        self.client.admin.command("ping")  # fails fast if Docker isn't running
        self.db: Database = self.client[db_name]

    # ---- collections ----

    @property
    def articles(self) -> Collection:
        return self.db[self.ARTICLES]

    def collection(self, name: str) -> Collection:
        """Any other collection by name, for future repositories."""
        return self.db[name]

    # ---- lifecycle: lets you write `with DbContext() as context:` ----

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> DbContext:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
