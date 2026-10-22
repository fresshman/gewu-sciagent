import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 开发时：Vite 跑在 :5173，把 /api 反向代理到本地轻代理 :3000
// 生产时：由 proxy/server.mjs 同时托管静态前端 + /api（同源，无 CORS）
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: false,
    proxy: {
      "/api": {
        target: "http://localhost:3000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
  },
});
