"""
seed.py — bulk-insert 200,000 product rows into the products table.

─────────────────────────────────────────────────────────────────────────────
KEY DECISIONS:

  psycopg2 (not an ORM)
    SQLAlchemy / Django ORM add per-row Python overhead and generate one
    INSERT per object unless you reach for lower-level bulk APIs. psycopg2
    gives direct access to execute_values, which lets us control exactly how
    data hits the wire.

  Generate all rows in memory first
    Building a plain Python list before opening a DB connection means the
    expensive random-number generation is decoupled from network I/O. If the
    insert fails we can retry without regenerating. Memory cost is modest:
    200 k tuples of (uuid, str, str, float, datetime, datetime) ≈ ~65 MB.
    UUIDs are generated in Python (uuid.uuid4()) rather than relying on
    gen_random_uuid() at the database level — this makes the script work
    against any Postgres table regardless of whether the column has a DEFAULT
    set, and keeps the ID generation visible and testable in Python.

  execute_values (single multi-row INSERT, not executemany)
    psycopg2's executemany() fires one round-trip per row — catastrophically
    slow over a remote connection. execute_values rewrites the INSERT into
    batches of `page_size` rows per round-trip, slashing latency overhead.
    For a Neon serverless instance over the public internet this alone cuts
    wall-clock time from ~30 min → well under 30 seconds.

    Alternative: COPY FROM STDIN is marginally faster still, but requires
    CSV encoding and bypasses column defaults, making the code harder to
    read. execute_values is the sweet spot of speed and clarity.

  page_size = 10_000
    Larger batches = fewer round-trips. 10 k rows per INSERT statement keeps
    memory/message size well within Postgres and Neon limits while still
    giving near-COPY performance. Tunable if needed.

  created_at spread over 2 years
    Seeding all rows with now() collapses the timeline and makes pagination
    benchmarks meaningless (every cursor page would hit the same hot block).
    Spreading timestamps uniformly exercises the index and gives realistic
    query plans.

  updated_at = created_at
    Products haven't been edited, so setting updated_at == created_at is
    semantically correct for fresh seed data.
─────────────────────────────────────────────────────────────────────────────
"""

import os
import random
import time
import uuid
from datetime import datetime, timedelta, timezone

import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

# ── Configuration ─────────────────────────────────────────────────────────────

load_dotenv()

NUM_ROWS  = 200_000
PAGE_SIZE = 10_000   # rows per execute_values batch

CATEGORIES = [
    "Electronics",
    "Clothing",
    "Books",
    "Home & Garden",
    "Sports",
    "Toys",
    "Beauty",
    "Automotive",
    "Food & Grocery",
    "Health",
]

# Enough adjective × noun combos to produce varied names without a name file.
ADJECTIVES = [
    "Premium", "Portable", "Compact", "Heavy-Duty", "Ultra",
    "Smart", "Classic", "Deluxe", "Pro", "Mini",
    "Advanced", "Essential", "Vintage", "Modern", "Slim",
    "Wireless", "Digital", "Organic", "Natural", "Eco",
    "Rugged", "Foldable", "Rechargeable", "Adjustable", "Thermal",
]

NOUNS = [
    "Headphones", "Keyboard", "Shirt", "Notebook", "Lamp",
    "Watch", "Bag", "Camera", "Shoes", "Jacket",
    "Tablet", "Speaker", "Chair", "Desk", "Monitor",
    "Pen", "Bottle", "Helmet", "Gloves", "Charger",
    "Belt", "Wallet", "Frame", "Mat", "Stand",
    "Brush", "Cooler", "Trimmer", "Tracker", "Blender",
]

# ── Row generation ─────────────────────────────────────────────────────────────

def generate_rows(n: int) -> list[tuple]:
    """Return a list of n tuples ready for bulk insert."""
    now            = datetime.now(timezone.utc)
    two_years_ago  = now - timedelta(days=730)
    window_seconds = int(timedelta(days=730).total_seconds())

    rows = []
    for _ in range(n):
        name       = f"{random.choice(ADJECTIVES)} {random.choice(NOUNS)}"
        category   = random.choice(CATEGORIES)
        # ₹100 – ₹50,000 with 2 decimal places
        price      = round(random.uniform(100.0, 50_000.0), 2)
        created_at = two_years_ago + timedelta(
            seconds=random.randint(0, window_seconds)
        )
        updated_at = created_at  # fresh seed data — no edits yet
        rows.append((str(uuid.uuid4()), name, category, price, created_at, updated_at))

    return rows

# ── Database helpers ───────────────────────────────────────────────────────────

INSERT_SQL = """
    INSERT INTO products (id, name, category, price, created_at, updated_at)
    VALUES %s
"""

def bulk_insert(conn, rows: list[tuple]) -> None:
    with conn.cursor() as cur:
        execute_values(cur, INSERT_SQL, rows, page_size=PAGE_SIZE)
    conn.commit()

# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL is not set. Check your .env file.")

    # 1. Generate all rows in memory before touching the DB.
    print(f"Generating {NUM_ROWS:,} rows in memory …")
    t0   = time.perf_counter()
    rows = generate_rows(NUM_ROWS)
    print(f"  Done in {time.perf_counter() - t0:.2f}s  ({len(rows):,} rows)")

    # 2. Connect and insert.
    print("Connecting to database …")
    conn = psycopg2.connect(db_url)
    conn.autocommit = False

    try:
        print(f"Inserting in batches of {PAGE_SIZE:,} …")
        t1 = time.perf_counter()
        bulk_insert(conn, rows)
        elapsed = time.perf_counter() - t1
        print(f"  Inserted {NUM_ROWS:,} rows in {elapsed:.2f}s")
    except Exception as exc:
        conn.rollback()
        print(f"Insert failed, transaction rolled back: {exc}")
        raise
    finally:
        conn.close()

    print("Seeding complete.")


if __name__ == "__main__":
    main()
