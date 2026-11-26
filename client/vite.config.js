import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// Where the dev server forwards /api requests. Set the base URL (protocol, host and port) with
// the API_URL environment variable, or API_URL=... in client/.env.local:
//
//   API_URL=http://127.0.0.1:5001 npm run dev        (the default)
//   API_URL=https://ratings.example.org npm run dev  (a deployed server)
//
// The browser still talks only to the Vite dev server (same origin), so cookies keep working.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const target = (env.API_URL || 'http://127.0.0.1:5001').replace(/\/+$/, '')
  return {
    plugins: [react()],
    server: {
      proxy: {
        // changeOrigin: send the target's own Host header (needed for a remote server).
        '/api': { target, changeOrigin: true },
      },
    },
  }
})
