import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5200,
    host: '0.0.0.0',   // expose to local network so iPhone on same WiFi can connect
    proxy: {
      '/api': 'http://127.0.0.1:8000',
      '/ws':  { target: 'ws://127.0.0.1:8000', ws: true },
    },
  },
})
