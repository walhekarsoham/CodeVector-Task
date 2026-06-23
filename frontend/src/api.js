/**
 * api.js — all HTTP calls to the FastAPI backend.
 *
 * VITE_API_URL is injected at build time by Vite. In development the Vite
 * proxy (vite.config.js) forwards /api/* to localhost:8000, so the BASE_URL
 * falls back to an empty string and the proxy handles the rest. In
 * production it is set to the full Render service URL.
 */

const BASE_URL = import.meta.env.VITE_API_URL ?? ''

/**
 * Fetch every distinct category stored in the products table.
 * @returns {Promise<string[]>}
 */
export async function fetchCategories() {
  const res = await fetch(`${BASE_URL}/api/categories`)
  if (!res.ok) throw new Error(`Could not load categories (HTTP ${res.status})`)
  const { categories } = await res.json()
  return categories
}

/**
 * Fetch a page of products.
 *
 * @param {object}      opts
 * @param {string}      [opts.category='']   Exact category name to filter by.
 * @param {string|null} [opts.cursor=null]   Opaque cursor token from a previous response.
 * @param {number}      [opts.limit=20]      Page size (1–100).
 * @param {AbortSignal} [opts.signal]        Optional AbortController signal.
 *
 * @returns {Promise<{ data: object[], next_cursor: string|null, has_more: boolean }>}
 */
export async function fetchProducts({
  category = '',
  cursor   = null,
  limit    = 20,
  signal,
} = {}) {
  const params = new URLSearchParams({ limit: String(limit) })
  if (category) params.set('category', category)
  if (cursor)   params.set('cursor', cursor)

  const res = await fetch(`${BASE_URL}/api/products?${params}`, { signal })
  if (!res.ok) throw new Error(`Could not load products (HTTP ${res.status})`)
  return res.json()
}
