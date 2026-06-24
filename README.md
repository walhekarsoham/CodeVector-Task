# CodeVector Task — Product Browsing Backend

A full-stack product catalogue built with **FastAPI + PostgreSQL + React**.  
Handles **200,000 products** with cursor-based pagination that stays fast and correct even as data changes.

🔗 **Live Demo:** [https://codevector-task-frontend.onrender.com](https://codevector-task-frontend.onrender.com)  
⚙️ **API:** [https://codevector-task-3t46.onrender.com](https://codevector-task-3t46.onrender.com)

---

## What it does

- Browse 200,000 products ordered newest first
- Filter by category
- Paginate without ever seeing a duplicate or missing a product — even if new data is added mid-browse
- Sub-second response times on every page

---

## Tech Stack

| Layer | Choice |
|---|---|
| Backend | Python, FastAPI, psycopg2 |
| Database | PostgreSQL (Neon) |
| Frontend | React, Vite |
| Hosting | Render (free tier) |

---

## Project Structure

```
├── main.py           API routes and pagination logic
├── db.py             PostgreSQL connection pool
├── seed.py           Bulk inserts 200k rows in under 30 seconds
├── schema.sql        Table definition and indexes
├── requirements.txt  Python dependencies
└── frontend/
    └── src/
        ├── App.jsx   Product table, category filter, pagination
        ├── api.js    API calls
        └── index.css Styles
```

---

## Running Locally

**1. Clone and set up Python**
```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

**2. Set your database URL**
```bash
# Create a .env file
echo 'DATABASE_URL=your_neon_connection_string' > .env
```

**3. Create schema and seed data**
```bash
psql $DATABASE_URL -f schema.sql
python seed.py                   # Seeds 200k rows in ~25 seconds
```

**4. Start the API**
```bash
uvicorn main:app --reload
# http://localhost:8000
# http://localhost:8000/docs  ← Swagger UI
```

**5. Start the frontend**
```bash
cd frontend
npm install
npm run dev
# http://localhost:5173
```

---

## API Reference

### `GET /api/products`

| Parameter | Type | Default | Description |
|---|---|---|---|
| `category` | string | — | Filter by category (optional) |
| `cursor` | string | — | Pagination token from previous response |
| `limit` | integer | 20 | Page size, max 100 |

**First page:**
```
GET /api/products?category=Electronics&limit=20
```

**Next page:**
```
GET /api/products?category=Electronics&limit=20&cursor=eyJjcmVhdGVkX2F0...
```

**Response:**
```json
{
  "data": [
    {
      "id": "802bb6d5-1c67-429e-859f-918ec712bcf6",
      "name": "ApexGo Compact Speaker",
      "category": "Electronics",
      "price": 1299.99,
      "created_at": "2026-01-15T10:22:05Z",
      "updated_at": "2026-01-15T10:22:05Z"
    }
  ],
  "next_cursor": "eyJjcmVhdGVkX2F0IjogIjIwMjYtMD...",
  "has_more": true
}
```

When `has_more` is `false`, you've reached the last page.

### `GET /api/categories`
Returns all category names for the filter dropdown.

### `GET /health`
Returns `{ "status": "ok" }` — used to verify the service is running.

---

## The Core Problem — Why Not OFFSET?

Most pagination uses `OFFSET`:
```sql
SELECT * FROM products ORDER BY created_at DESC LIMIT 20 OFFSET 1000;
```

This has two fatal problems at scale:

**1. It gets slow.** Postgres must scan and discard 1,000 rows before returning 20. At page 5,000 that's 100,000 rows thrown away on every request.

**2. It breaks when data changes.** If 10 new products are inserted while someone is on page 3, every subsequent page shifts — users see duplicates or miss products entirely.

---

## The Solution — Keyset (Cursor) Pagination

Instead of "skip N rows", we say "give me rows older than this specific product":

```sql
WHERE (created_at < :last_ts)
   OR (created_at = :last_ts AND id < :last_id)
ORDER BY created_at DESC, id DESC
LIMIT 20
```

The cursor is a **base64-encoded JSON** token containing `created_at` and `id` of the last item seen. It's opaque to the client — the server decodes it to build the WHERE clause.

**Why this is stable:** A new product inserted while browsing gets `created_at = now()`, which is newer than the cursor. It lands before page 1 in the sort order and never appears in pages already being browsed.

---

## Indexes

Two composite indexes make every page fetch an O(log n) index seek:

```sql
-- For unfiltered browsing
CREATE INDEX idx_products_created_at_id
    ON products (created_at DESC, id DESC);

-- For category-filtered browsing
CREATE INDEX idx_products_category_created_at_id
    ON products (category, created_at DESC, id DESC);
```

Without these, even keyset pagination does a full table scan. With them, Postgres seeks directly to the cursor position regardless of dataset size.

---

## Seeder — 200k Rows in 25 Seconds

```python
# Instead of 200,000 individual inserts (would take ~45 minutes on a remote DB)
# We generate all rows in memory and insert in batches of 10,000
execute_values(cursor, insert_sql, rows, page_size=10000)
# 20 round trips total vs 200,000
```

---

## What I'd Improve With More Time

- **Sign cursors** with HMAC-SHA256 so clients can't forge arbitrary positions
- **Redis caching** for the first few pages per category (Upstash free tier)
- **PgBouncer** for connection pooling in production
- **Full-text search** on product name using PostgreSQL `tsvector` + GIN index
- **Automated tests** that insert rows mid-pagination and verify no duplicates appear

---

## Deployment

Backend and frontend are deployed separately on Render's free tier.

> ⚠️ Free tier spins down after 15 minutes of inactivity. First request may take ~30 seconds to wake up. Open the app a few minutes before demoing.
