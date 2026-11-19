import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": path.resolve(import.meta.dirname, "./src") } },
  // En Docker sobre Windows los eventos del sistema de archivos no cruzan el volumen: polling.
  server: { host: "0.0.0.0", port: 5173, watch: { usePolling: process.env.VITE_POLLING === "true", interval: 300 } },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
