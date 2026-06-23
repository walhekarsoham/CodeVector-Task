"""
db.py — psycopg2 connection pool management.

─────────────────────────────────────────────────────────────────────────────
KEY DECISIONS:

  ThreadedConnectionPool (not SimpleConnectionPool)
    FastAPI runs synchronous route handlers in a thread pool executor — each
    incoming request may run on a different OS thread concurrently.
    SimpleConnectionPool is NOT thread-safe; concurrent getconn() calls on it
    can corrupt internal state. ThreadedConnectionPool wraps every operation
    with a threading.Lock, making it safe to share across threads.

  min_conn=2, max_conn=10
    minconn pre-warms two connections at startup so the first requests don't
    pay connection-establishment latency. maxconn=10 caps DB load; Neon's free
    tier allows ~100 connections, so this leaves plenty of room for other
    clients. Both values are env-configurable for tuning in production.

  Context manager (get_connection)
    Guarantees the connection is always returned to the pool — even if the
    route handler raises an exception. Also rolls back any uncommitted
    transaction on error so the connection is clean before being reused.

  load_dotenv() here
    Called once at module import. db.py is the single place that reads
    DATABASE_URL, keeping credential handling in one file.
─────────────────────────────────────────────────────────────────────────────
"""

import os
from contextlib import contextmanager
from typing import Generator

import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from dotenv import load_dotenv

load_dotenv()

# Module-level pool — initialised by init_pool(), closed by close_pool().
_pool: ThreadedConnectionPool | None = None


def init_pool(
    min_conn: int = 2,
    max_conn: int = 10,
) -> None:
    """Create the connection pool.  Called once during FastAPI lifespan startup."""
    global _pool
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL is not set. Check your .env file.")
    _pool = ThreadedConnectionPool(min_conn, max_conn, dsn=db_url)


def close_pool() -> None:
    """Close every connection in the pool.  Called during FastAPI lifespan shutdown."""
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None


@contextmanager
def get_connection() -> Generator[psycopg2.extensions.connection, None, None]:
    """
    Yield a connection from the pool and return it afterwards.

    Usage:
        with db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(...)

    The connection is rolled back and returned to the pool on any exception,
    ensuring it is always in a clean state when reused.

    Stale-connection handling: Neon (and any managed Postgres) will silently
    close idle connections after a timeout. psycopg2's pool doesn't detect
    this until the next use. If the connection is already closed when we try
    to roll back, we swallow the InterfaceError and return the dead connection
    with close=True so the pool discards it and opens a fresh one next time.
    """
    if _pool is None:
        raise RuntimeError("Connection pool is not initialised.")

    conn = _pool.getconn()
    broken = False
    try:
        yield conn
    except Exception:
        # conn.closed == 0 means open; > 0 means closed/broken.
        if conn.closed == 0:
            try:
                conn.rollback()
            except psycopg2.InterfaceError:
                broken = True
        else:
            broken = True
        raise
    finally:
        # Return (and optionally discard) the connection.
        # close=True tells the pool to destroy this slot and open a fresh
        # connection the next time getconn() is called.
        _pool.putconn(conn, close=broken)
