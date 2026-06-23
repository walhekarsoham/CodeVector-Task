import { useState, useEffect, useCallback, useRef } from 'react'
import { fetchCategories, fetchProducts } from './api'

// ── CategoryFilter ────────────────────────────────────────────────────────────
// A controlled <select> that lists every available category.
// Selecting "All Categories" (value="") removes the filter.

function CategoryFilter({ categories, value, onChange }) {
  return (
    <div className="toolbar">
      <span className="filter-label">Filter by:</span>
      <select
        className="category-select"
        value={value}
        onChange={e => onChange(e.target.value)}
        aria-label="Filter products by category"
      >
        <option value="">All Categories</option>
        {categories.map(cat => (
          <option key={cat} value={cat}>{cat}</option>
        ))}
      </select>
    </div>
  )
}

// ── ProductRow ────────────────────────────────────────────────────────────────
// Renders one product as a <tr>. Formatting is identical to the old card —
// same Intl helpers, same classes for price/category colouring.

function ProductRow({ product }) {
  const price = new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(product.price)

  const date = new Intl.DateTimeFormat('en-IN', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  }).format(new Date(product.created_at))

  return (
    <tr>
      <td className="col-name product-name">{product.name}</td>
      <td className="col-category">
        <span className="product-category">{product.category}</span>
      </td>
      <td className="col-price product-price">{price}</td>
      <td className="col-date product-date">{date}</td>
    </tr>
  )
}

// ── App ───────────────────────────────────────────────────────────────────────

export default function App() {
  const [categories, setCategories] = useState([])
  const [category,   setCategory]   = useState('')          // active filter
  const [products,   setProducts]   = useState([])          // accumulated pages
  const [cursor,     setCursor]      = useState(null)        // next-page token
  const [hasMore,    setHasMore]     = useState(true)
  const [loading,    setLoading]     = useState(false)
  const [error,      setError]       = useState(null)

  // Ref to the current AbortController so we can cancel stale requests.
  // This prevents a slow response for category "Electronics" from
  // overwriting state after the user has already switched to "Books".
  const abortRef = useRef(null)

  // ── Load category list once on mount ───────────────────────────────────
  useEffect(() => {
    fetchCategories()
      .then(setCategories)
      .catch(e => setError(e.message))
  }, [])

  // ── Core fetch function ────────────────────────────────────────────────
  // Takes cat and cur as explicit params instead of reading from state so
  // the caller always controls exactly which page is being fetched without
  // needing to wait for a setState flush.
  const loadProducts = useCallback(async (cat, cur) => {
    // Cancel any previous in-flight fetch.
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setLoading(true)
    setError(null)

    try {
      const result = await fetchProducts({
        category: cat,
        cursor:   cur,
        signal:   controller.signal,
      })

      setProducts(prev =>
        // cur === null  → fresh load (category changed or first visit): replace list.
        // cur !== null  → Load More: append to existing list.
        cur ? [...prev, ...result.data] : result.data
      )
      setCursor(result.next_cursor)
      setHasMore(result.has_more)
    } catch (e) {
      // Ignore intentional cancellation; surface real errors.
      if (e.name !== 'AbortError') setError(e.message)
    } finally {
      // Only clear the spinner if this request was not superseded.
      if (!controller.signal.aborted) setLoading(false)
    }
  }, []) // stable — all inputs arrive as params, state setters are stable refs

  // ── Reset and reload whenever category changes (including initial mount) ─
  useEffect(() => {
    setProducts([])
    setCursor(null)
    setHasMore(true)
    loadProducts(category, null)
  }, [category, loadProducts])

  // ── Load More handler ──────────────────────────────────────────────────
  // Uses the cursor from the last successful response. Because loadProducts
  // takes cur as a param (not from state), this always uses the latest value
  // even though React may batch state updates.
  const handleLoadMore = () => loadProducts(category, cursor)

  // ── Render ─────────────────────────────────────────────────────────────
  return (
    <div className="app">
      <header className="app-header">
        <div className="header-top">
          <h1>Product Browser</h1>
          {products.length > 0 && (
            <span className="badge-count">
              {products.length.toLocaleString('en-IN')} loaded
            </span>
          )}
        </div>

        <CategoryFilter
          categories={categories}
          value={category}
          onChange={setCategory}
        />
      </header>

      <main>
        {error && (
          <div className="error-banner" role="alert">
            {error}
          </div>
        )}

        <div className="table-wrapper">
          <table className="product-table">
            <thead>
              <tr>
                <th className="col-name">Name</th>
                <th className="col-category">Category</th>
                <th className="col-price">Price</th>
                <th className="col-date">Created</th>
              </tr>
            </thead>
            <tbody>
              {products.length === 0 && !loading && (
                <tr>
                  <td colSpan={4} className="empty-state">No products found.</td>
                </tr>
              )}
              {products.map(p => (
                <ProductRow key={p.id} product={p} />
              ))}
            </tbody>
          </table>
        </div>

        <div className="footer-actions">
          {loading && (
            <div className="loading-row" aria-live="polite" aria-label="Loading">
              <div className="spinner" aria-hidden="true" />
              Loading…
            </div>
          )}

          {!loading && hasMore && products.length > 0 && (
            <button
              className="btn-load-more"
              onClick={handleLoadMore}
              aria-label="Load next page of products"
            >
              Load More
            </button>
          )}

          {!loading && !hasMore && products.length > 0 && (
            <p className="no-more">All products loaded</p>
          )}
        </div>
      </main>
    </div>
  )
}
