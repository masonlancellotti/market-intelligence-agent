import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Dev proxies /api and /feed.xml to the meridiand daemon (port 8788).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5273,
    proxy: {
      "/api": { target: "http://localhost:8788", changeOrigin: true, ws: true },
      "/feed.xml": "http://localhost:8788",
      "/og": "http://localhost:8788",
    },
  },
  build: { outDir: "dist", sourcemap: false, chunkSizeWarningLimit: 1200 },
});
