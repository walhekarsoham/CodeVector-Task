"""
main.py — FastAPI product browsing API.

Routes
------
GET /health                     liveness check
GET /api/categories             distinct category list (for filter UI)
GET /api/products               paginated product list (keyset / cursor pagination)

─────────────────────────────────────────────────────────────────────────────
KEY DECISIONS:

  Raw psycopg2 — no ORM
    ORMs build queries in Python objects and add per-row Python overhead.
    Raw SQL lets us write exactly the keyset WHERE clause we need, control
    parameter types (e.g. ::uuid cast), and read the query plan directly
    without any magic in between.

  Cursor = base64url(JSON({created_at, id}))
    base64url is URL-safe so the cursor travels in a query parameter without
    percent-encoding. JSON is self-describing and easy to extend (e.g. add
    a sort field later) without a versioning scheme.

  Fetch limit+1 for has_more
    Instead of a separate COUNT query (expensive on 200 k rows), we ask for
    one extra row. If we get it, there is a next page; we discard it from
    the response. One query, no full-table scan.

  Pydantic response models
    Not ORM — psycopg2 still executes raw SQL and returns plain tuples.
    Pydantic just validates and serialises the Python objects we build from
    those tuples. Swapping it for a dict response would work but we'd lose
    automatic type coercion (Decimal → float, UUID → str, datetime → ISO).
─────────────────────────────────────────────────────────────────────────────
"""

import base64
import json
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import db


# ── Lifespan: pool init / teardown ───────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_pool()
    yield
    db.close_pool()


app = FastAPI(title="Product Browsing API", version="1.0.0", lifespan=lifespan)


# ── CORS ─────────────────────────────────────────────────────────────────────
#
# WHY: Browsers block cross-origin XHR/fetch by default. Adding CORSMiddleware
# sends the required Access-Control-Allow-* headers so a frontend served from
# a different origin (e.g. localhost:3000 in dev, or a CDN in prod) can call
# this API. allow_origins=["*"] is intentionally permissive for development;
# tighten this to specific domains before going to production.

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pydantic models ───────────────────────────────────────────────────────────

class Product(BaseModel):
    id: UUID
    name: str
    category: str
    price: float          # psycopg2 returns Decimal; Pydantic coerces to float
    created_at: datetime
    updated_at: datetime


class ProductsResponse(BaseModel):
    data: list[Product]
    next_cursor: Optional[str]
    has_more: bool


# ── Cursor helpers ────────────────────────────────────────────────────────────

def encode_cursor(created_at: datetime, row_id: str) -> str:
    """Serialize (created_at, id) into a URL-safe opaque string."""
    payload = {"created_at": created_at.isoformat(), "id": row_id}
    # urlsafe_b64encode avoids + and / which would need percent-encoding in URLs
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def decode_cursor(cursor: str) -> tuple[str, str]:
    """
    Decode a cursor string back to (created_at_iso, id_str).
    Raises HTTP 400 if the cursor is malformed — never let a bad cursor
    cause a 500 or a silent wrong-page result.
    """
    try:
        # Re-add base64 padding in case it was stripped by a client
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
        return payload["created_at"], payload["id"]
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid or malformed cursor.")


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}


@app.get("/api/categories", tags=["products"])
def get_categories():
    """Return every distinct category present in the products table."""
    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT category FROM products ORDER BY category"
            )
            categories = [row[0] for row in cur.fetchall()]
    return {"categories": categories}


@app.get("/api/products", response_model=ProductsResponse, tags=["products"])
def get_products(
    category: Optional[str] = Query(default=None, description="Filter by exact category name"),
    cursor:   Optional[str] = Query(default=None, description="Opaque pagination token from previous response"),
    limit:    int            = Query(default=20, ge=1, le=100, description="Page size (1–100, default 20)"),
):
    """
    Return a page of products ordered by newest first.

    ═══════════════════════════════════════════════════════════════════════════
    WHY KEYSET PAGINATION NEVER PRODUCES DUPLICATES OR SKIPS
    ═══════════════════════════════════════════════════════════════════════════

    OFFSET pagination (LIMIT n OFFSET k) works by position: "skip k rows,
    then return n."  If even one row is inserted before position k while a
    user is paginating, every item shifts one slot and the user sees the
    item at the old slot k duplicated on two consecutive pages — and the
    item that "moved into" the previous page's last slot is silently skipped.

    KEYSET pagination works by value, not position.  The cursor encodes the
    (created_at, id) of the last row the client saw.  The next-page query is:

        WHERE (created_at < last_created_at)
           OR (created_at = last_created_at AND id < last_id)

    This means: "give me rows that strictly come after the cursor in the
    sort order."  Crucially:

      • A row inserted AFTER the cursor (newer created_at) has
        created_at > last_created_at → it fails the WHERE clause → it will
        never appear on a subsequent page.  No duplicate.

      • A row inserted BEFORE the cursor (older created_at, or same
        created_at with a smaller UUID) satisfies the WHERE clause → it
        will appear on a future page exactly once.  No skip.

      • The id tie-breaker is essential: two rows can share the same
        created_at.  Without id, the cursor would be ambiguous and boundary
        rows could appear twice or not at all.  UUID primary keys are unique
        by definition, so (created_at, id) is always an unambiguous,
        globally stable position in the ordered dataset.

    The composite index on (category, created_at DESC, id DESC) means
    Postgres satisfies both the WHERE clause and the ORDER BY from a single
    index scan with no sort step, keeping p99 latency flat across all pages.
    ═══════════════════════════════════════════════════════════════════════════
    """

    # Fetch one extra row to determine has_more without a COUNT query.
    fetch_limit = limit + 1

    params: dict = {"limit": fetch_limit}
    where_clauses: list[str] = []

    # ── Optional category filter ──────────────────────────────────────────
    if category:
        where_clauses.append("category = %(category)s")
        params["category"] = category

    # ── Keyset cursor condition ───────────────────────────────────────────
    if cursor:
        last_created_at, last_id = decode_cursor(cursor)
        # Explicit two-branch form rather than row-value syntax (a, b) < (x, y)
        # because it maps directly to the composite index prefix scan and is
        # unambiguous about how each column is compared.
        where_clauses.append(
            "(created_at < %(last_created_at)s"
            " OR (created_at = %(last_created_at)s AND id < %(last_id)s::uuid))"
        )
        params["last_created_at"] = last_created_at
        params["last_id"] = last_id

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    sql = f"""
        SELECT id, name, category, price, created_at, updated_at
        FROM   products
        {where_sql}
        ORDER  BY created_at DESC, id DESC
        LIMIT  %(limit)s
    """

    with db.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    # Determine pagination metadata before trimming the extra row.
    has_more = len(rows) == fetch_limit
    rows     = rows[:limit]

    products = [
        Product(
            id         = row[0],
            name       = row[1],
            category   = row[2],
            price      = row[3],
            created_at = row[4],
            updated_at = row[5],
        )
        for row in rows
    ]

    # Build the next cursor from the last item in this page.
    next_cursor: Optional[str] = None
    if has_more and products:
        last        = products[-1]
        next_cursor = encode_cursor(last.created_at, str(last.id))

    return ProductsResponse(data=products, next_cursor=next_cursor, has_more=has_more)
