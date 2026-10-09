"""PostgreSQL vector store backend using pgvector extension.

Provides vector similarity search capabilities using PostgreSQL with the pgvector
extension. Requires:
- PostgreSQL database where the pgvector extension is available. The extension is
  enabled automatically (CREATE EXTENSION IF NOT EXISTS vector) on first connect,
  so the DB role needs permission to create extensions. On Azure Database for
  PostgreSQL, allow-list VECTOR in the `azure.extensions` server parameter first.
- Connection details via environment variables

The table schema (created lazily once the embedding dimension is known) is:
    CREATE TABLE IF NOT EXISTS question_paper_chunks (
        id UUID PRIMARY KEY,
        chunk_id TEXT UNIQUE NOT NULL,
        source_document_id TEXT NOT NULL,
        content TEXT NOT NULL,
        embedding VECTOR(<dim>) NOT NULL,  -- dim depends on the embedding model
        chapter TEXT,
        topic TEXT,
        heading_path TEXT,
        page_start INTEGER,
        page_end INTEGER,
        image_references JSONB,
        created_at TIMESTAMP WITH TIME ZONE
    );

    CREATE INDEX IF NOT EXISTS idx_question_paper_chunks_embedding
        ON question_paper_chunks USING hnsw (embedding vector_cosine_ops);

    CREATE INDEX IF NOT EXISTS idx_question_paper_chunks_source_document
        ON question_paper_chunks(source_document_id);

    CREATE INDEX IF NOT EXISTS idx_question_paper_chunks_topic
        ON question_paper_chunks(topic);

HNSW requires pgvector >= 0.5.0 and a fixed vector dimension. If you switch to an
embedding model with a different dimension, drop the table and re-ingest.

See https://github.com/pgvector/pgvector for installation instructions.
"""

import asyncio
import json
import logging
import uuid
from typing import Optional
from datetime import datetime, timezone
from urllib.parse import quote as urlquote

import asyncpg
from pgvector.asyncpg import register_vector

from app.core.config import settings
from app.services.vector_store.base import VectorRecord, VectorSearchResult, VectorStoreClient

logger = logging.getLogger(__name__)

# Namespace for generating deterministic UUIDs from chunk IDs
_ID_NAMESPACE = uuid.UUID("a9f36c9e-6b34-4c8b-9c34-2f1a6a7b9c11")


def _point_id(chunk_id: str) -> str:
    """Generate a deterministic UUID from a chunk ID for use as primary key."""
    return str(uuid.uuid5(_ID_NAMESPACE, chunk_id))


class PostgresStore(VectorStoreClient):
    """Vector search backed by PostgreSQL with pgvector extension."""

    def __init__(self) -> None:
        self._pool: Optional[asyncpg.Pool] = None
        self._vector_size: Optional[int] = None
        self._table_name = "question_paper_chunks"
        # Tracks the dimension for which the schema has already been ensured,
        # so we don't re-run DDL on every upsert/search call.
        self._schema_ready_size: Optional[int] = None
        self._pool_lock = asyncio.Lock()
        self._schema_lock = asyncio.Lock()

    def _build_connection_url(self) -> str:
        """Build the PostgreSQL connection URL from settings.

        If DATABASE_URL is already a PostgreSQL URL, it is used directly.
        Otherwise, the URL is assembled from the individual POSTGRES_* settings.
        """
        db_url = settings.database_url
        if db_url.startswith("postgresql") or db_url.startswith("postgres"):
            return db_url

        host = settings.postgres_host
        port = settings.postgres_port
        db = settings.postgres_db
        user = settings.postgres_user
        password = settings.postgres_password
        ssl = settings.postgres_ssl_mode

        auth = user
        if password:
            # Quote special chars in password (e.g. @ must be %40 in a URL)
            auth = f"{user}:{urlquote(password)}"

        url = f"postgresql://{auth}@{host}:{port}/{db}"
        if ssl:
            url += f"?sslmode={ssl}"

        return url

    async def _get_pool(self) -> asyncpg.Pool:
        """Get or create the connection pool."""
        if self._pool is not None:
            return self._pool

        async with self._pool_lock:
            if self._pool is None:
                conn_url = self._build_connection_url()

                # Bootstrap: the extension must exist BEFORE register_vector()
                # runs on pooled connections, otherwise asyncpg raises
                # "unknown type: public.vector".
                boot = await asyncpg.connect(conn_url)
                try:
                    await boot.execute("CREATE EXTENSION IF NOT EXISTS vector")
                finally:
                    await boot.close()

                self._pool = await asyncpg.create_pool(
                    conn_url,
                    min_size=1,
                    max_size=10,
                    command_timeout=60,
                    init=self._init_connection,
                )
                logger.info(
                    "PostgreSQL connection pool initialized for %s:%s/%s",
                    settings.postgres_host, settings.postgres_port, settings.postgres_db,
                )
        return self._pool

    async def _init_connection(self, conn: asyncpg.Connection) -> None:
        """Per-connection setup only.

        The table and indexes are created in _ensure_table_and_dimensions(),
        because the embedding column needs a fixed dimension that is only known
        once we see the first batch of vectors.
        """
        await register_vector(conn)

    async def _ensure_table_and_dimensions(self, conn: asyncpg.Connection, vector_size: int) -> None:
        """Ensure the table and indexes exist with the correct vector dimension."""
        self._vector_size = vector_size

        if self._schema_ready_size == vector_size:
            return

        async with self._schema_lock:
            if self._schema_ready_size == vector_size:
                return

            t = self._table_name

            # If the table already exists, make sure its dimension matches.
            # For pgvector, atttypmod holds the dimension (-1 means no dimension).
            existing_dim = await conn.fetchval(
                """
                SELECT atttypmod
                FROM pg_attribute
                WHERE attrelid = to_regclass($1::text)
                  AND attname = 'embedding'
                  AND NOT attisdropped
                """,
                t,
            )
            if existing_dim is not None and existing_dim != vector_size:
                raise ValueError(
                    f"Table '{t}' has embedding dimension {existing_dim} "
                    f"but the current embedding model produces {vector_size}. "
                    f"Drop the table (DROP TABLE {t};) and re-ingest, or switch "
                    f"back to the original embedding model."
                )

            await conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {t} (
                    id UUID PRIMARY KEY,
                    chunk_id TEXT UNIQUE NOT NULL,
                    source_document_id TEXT NOT NULL,
                    content TEXT NOT NULL,
                    embedding VECTOR({int(vector_size)}) NOT NULL,
                    chapter TEXT,
                    topic TEXT,
                    heading_path TEXT,
                    page_start INTEGER,
                    page_end INTEGER,
                    image_references JSONB,
                    created_at TIMESTAMP WITH TIME ZONE
                )
                """
            )

            # HNSW works from the first insert (no training step like ivfflat)
            # and needs no list-count tuning.
            await conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_{t}_embedding
                    ON {t} USING hnsw (embedding vector_cosine_ops)
                """
            )
            await conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_{t}_source_document
                    ON {t}(source_document_id)
                """
            )
            await conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_{t}_topic
                    ON {t}(topic)
                """
            )

            self._schema_ready_size = vector_size

    async def upsert_chunks(self, document_id: str, records: list[VectorRecord]) -> list[str]:
        """Write embedded chunks to the PostgreSQL store."""
        if not records:
            return []

        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await self._ensure_table_and_dimensions(
                conn, vector_size=len(records[0].embedding)
            )

            # Prepare data for batch insert
            now = datetime.now(timezone.utc)
            values = []
            for r in records:
                # asyncpg requires a datetime object for TIMESTAMPTZ, not a string
                created = r.created_at
                if isinstance(created, str):
                    created = datetime.fromisoformat(created)
                if created is None:
                    created = now
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)

                values.append((
                    _point_id(r.id),  # id (UUID)
                    r.id,             # chunk_id
                    r.source_document_id,
                    r.content,
                    r.embedding,      # embedding (handled by pgvector codec)
                    r.chapter,
                    r.topic,
                    r.heading_path,
                    r.page_start,
                    r.page_end,
                    json.dumps(r.image_references) if r.image_references else None,
                    created,
                ))

            # Upsert chunks (insert or update on conflict)
            await conn.executemany(
                f"""
                INSERT INTO {self._table_name} (
                    id, chunk_id, source_document_id, content, embedding,
                    chapter, topic, heading_path, page_start, page_end,
                    image_references, created_at
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
                ON CONFLICT (chunk_id) DO UPDATE SET
                    source_document_id = EXCLUDED.source_document_id,
                    content = EXCLUDED.content,
                    embedding = EXCLUDED.embedding,
                    chapter = EXCLUDED.chapter,
                    topic = EXCLUDED.topic,
                    heading_path = EXCLUDED.heading_path,
                    page_start = EXCLUDED.page_start,
                    page_end = EXCLUDED.page_end,
                    image_references = EXCLUDED.image_references,
                    created_at = EXCLUDED.created_at
                """,
                values,
            )

            logger.info(
                "Indexed %d chunks to PostgreSQL table '%s'",
                len(records), self._table_name,
            )
            return [r.id for r in records]

    async def search(
        self,
        *,
        query_text: str,
        query_vector: list[float],
        document_id: str,
        top_k: int = 5,
        filter_category: Optional[str] = None,
    ) -> list[VectorSearchResult]:
        """Search for similar vectors using cosine similarity."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            await self._ensure_table_and_dimensions(
                conn, vector_size=len(query_vector)
            )

            # Build WHERE clause
            where_conditions = ["source_document_id = $1"]
            params = [document_id]
            param_idx = 2

            if filter_category:
                where_conditions.append(f"topic = ${param_idx}")
                params.append(filter_category)
                param_idx += 1

            where_clause = " AND ".join(where_conditions)

            # NOTE: the vector param is appended after the filters, so its
            # placeholder index must follow them (it was hard-coded to $2 before,
            # which broke whenever filter_category was set).
            vector_idx = param_idx
            params.append(query_vector)
            param_idx += 1
            limit_idx = param_idx
            params.append(top_k)

            query = f"""
                SELECT
                    chunk_id, content, embedding <=> ${vector_idx} AS distance,
                    chapter, topic, heading_path, page_start, page_end
                FROM {self._table_name}
                WHERE {where_clause}
                ORDER BY distance ASC
                LIMIT ${limit_idx}
            """

            rows = await conn.fetch(query, *params)

            # Convert results to VectorSearchResult objects
            search_results = []
            for row in rows:
                # Convert distance to similarity score (1 - distance for cosine)
                score = 1.0 - row["distance"] if row["distance"] is not None else 0.0

                search_results.append(
                    VectorSearchResult(
                        chunk_id=row["chunk_id"],
                        content=row["content"],
                        score=score,
                        chapter=row["chapter"],
                        topic=row["topic"],
                        page_start=row["page_start"],
                        page_end=row["page_end"],
                        heading_path=row["heading_path"],
                    )
                )

            logger.info("PostgreSQL search returned %d results", len(search_results))
            return search_results

    async def count_chunks(self, document_id: str) -> int:
        """Count the number of chunks for a specific document."""
        pool = await self._get_pool()
        async with pool.acquire() as conn:
            # The table is created lazily on first upsert/search, so it may
            # not exist yet.
            exists = await conn.fetchval(
                "SELECT to_regclass($1::text) IS NOT NULL", self._table_name
            )
            if not exists:
                return 0

            result = await conn.fetchval(
                f"SELECT COUNT(*) FROM {self._table_name} WHERE source_document_id = $1",
                document_id,
            )
            return result or 0

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
            self._schema_ready_size = None