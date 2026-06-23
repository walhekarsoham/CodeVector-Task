import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],

  // In development, proxy /api/* to the FastAPI backend so the browser
  // never needs to deal with CORS during local development.
  // In production the VITE_API_URL env var points directly at the Render URL.
  server: {
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
