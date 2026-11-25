import { renameSync, writeFileSync } from "node:fs";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

// The browser talks only to this server; /api (HTTP and WebSocket) is
// proxied to the backend container, so there is no CORS to configure.
const API_TARGET = process.env.CANVAS_API_URL ?? "http://127.0.0.1:8788";

// Local development only: the launcher's window reports its position and
// size (src/devWindow.ts); they're kept in YUZU_WINDOW_FILE, which the
// launcher (bin/yuzu-canva) sets and reads to reopen the window there.
function windowPlacement(): Plugin {
  const file = process.env.YUZU_WINDOW_FILE;
  return {
    name: "yuzu-window-placement",
    apply: "serve",
    configureServer(server) {
      if (!file) return;
      server.middlewares.use("/__yuzu/window", (req, res) => {
        if (req.method !== "POST") {
          res.statusCode = 405;
          res.end();
          return;
        }
        let body = "";
        req.on("data", (chunk) => {
          body += chunk;
          if (body.length > 1000) req.destroy();
        });
        req.on("end", () => {
          try {
            const { x, y, width, height } = JSON.parse(body);
            if (![x, y, width, height].every(Number.isInteger) || width < 200 || height < 200) {
              throw new Error("bad placement");
            }
            writeFileSync(`${file}.tmp`, JSON.stringify({ x, y, width, height }));
            renameSync(`${file}.tmp`, file);
            res.statusCode = 204;
          } catch {
            res.statusCode = 400;
          }
          res.end();
        });
      });
    },
  };
}

export default defineConfig({
  plugins: [react(), windowPlacement()],
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
