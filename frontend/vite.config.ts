import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The browser talks only to this server; /api (HTTP and WebSocket) is
// proxied to the backend container, so there is no CORS to configure.
const API_TARGET = process.env.CANVAS_API_URL ?? "http://127.0.0.1:8788";

export default defineConfig({
  plugins: [react()],
  // A local app: one bundle is fine (the warning's 500 kB default is for sites).
  build: { chunkSizeWarningLimit: 1000 },
  server: {
    host: "127.0.0.1",
    port: 5180,
    strictPort: true,
    proxy: {
      "/api": { target: API_TARGET, ws: true, changeOrigin: false },
    },
  },
});
