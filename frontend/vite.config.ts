import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev: Vite (:5195) serves the web app with hot reload and proxies the Agent Studio backend (:8095).
// The builder canvas lives on the engine (config engine.public_url) and is opened by full-page links.
const app = "http://127.0.0.1:8095";
export default defineConfig({
  base: "/",
  plugins: [react()],
  server: {
    port: 5195,
    strictPort: true,
    host: "0.0.0.0",   // reachable from other PCs at http://<this-pc-ip>:5195; API + engine stay on 127.0.0.1 behind the proxy
    proxy: { "/api/studio": app, "/auth": app, "/health": app },
  },
  build: { outDir: "dist", assetsDir: "static" },
});
