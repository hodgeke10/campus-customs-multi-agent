import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The board calls the FastAPI backend directly at http://localhost:8000
// (see API_BASE in src/api.ts). The backend allows this origin via CORS.
// Ports 5173-5177 are used by the lecture apps in this workspace, so Vite is
// pinned to 5178; `strictPort` makes a clash fail loudly instead of silently
// moving to a port the backend has not been told about.
export default defineConfig({
  plugins: [react()],
  server: { port: 5178, strictPort: true },
})
