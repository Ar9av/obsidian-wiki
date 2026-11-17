import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The bundle is committed into the Python package so `pip install` users need no Node.
// `npm run dev` proxies the API to a running `obsidian-wiki ui --no-open`.
export default defineConfig({
  plugins: [react()],
  base: '/ui/',
  build: { outDir: '../obsidian_wiki/webui', emptyOutDir: true, chunkSizeWarningLimit: 2000 },
  server: { proxy: { '/v1': 'http://127.0.0.1:3114' } },
})
