# check_pg.py
import asyncio, asyncpg
from app.core.config import settings
from app.services.vector_store.postgres_store import PostgresStore
from pydantic_settings import BaseSettings, SettingsConfigDict

from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"   # qpg-generator/.env

model_config = SettingsConfigDict(env_file=ENV_FILE, env_file_encoding="utf-8")


async def main():
    store = PostgresStore()
    url = store._build_connection_url()
    print("host:", settings.postgres_host, "| port:", settings.postgres_port,
          "| db:", settings.postgres_db, "| ssl:", settings.postgres_ssl_mode)
    print("DATABASE_URL starts with:", settings.database_url.split("://")[0])

    for step, coro in [
        ("connect", asyncpg.connect(url, timeout=15)),
    ]:
        try:
            conn = await coro
            print(f"{step}: OK")
        except Exception as e:
            print(f"{step}: FAILED -> {type(e).__name__}: {e!r}")
            return

    try:
        print("version:", await conn.fetchval("select version()"))
        print("extension:", await conn.execute("CREATE EXTENSION IF NOT EXISTS vector"))
        print("vector installed:", await conn.fetchval(
            "select extversion from pg_extension where extname='vector'"))
    except asyncpg.FeatureNotSupportedError as e:
        if "extension \"vector\" is not allow-listed" in str(e):
            print("FAILED -> Azure PostgreSQL requires the 'vector' extension to be allow-listed.")
            print("  Go to: Azure Portal → PostgreSQL Flexible Server →")
            print("        Server parameters → azure.extensions → add 'vector'")
            print("  Then restart the server and re-run this check.")
        else:
            print(f"FAILED -> {type(e).__name__}: {e!r}")
    except Exception as e:
        print(f"FAILED -> {type(e).__name__}: {e!r}")
    finally:
        await conn.close()

asyncio.run(main())