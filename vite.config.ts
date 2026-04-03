import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { resolve } from "path";

// @ts-expect-error process is a nodejs global
const host = process.env.TAURI_DEV_HOST;

export default defineConfig(async () => ({
    plugins: [vue()],
    clearScreen: false,

    // ── 预构建优化 ─────────────────────────────────────────────────
    // 显式列出重量级依赖，让 Vite 在首次启动时即完成 CJS→ESM 转换并缓存，
    // 后续启动直接复用缓存，跳过依赖扫描阶段。
    // pixi.js + pixi-live2d-display 是项目中体积最大的两个包，预构建收益最显著。
    optimizeDeps: {
        include: [
            "pixi.js",
            "pixi-live2d-display/cubism4",
            "vue",
            "@tauri-apps/api/event",
            "@tauri-apps/api/core",
            "@tauri-apps/api/window",
        ],
    },

    build: {
        rollupOptions: {
            input: {
                main:     resolve(__dirname, "index.html"),
                settings: resolve(__dirname, "settings.html"),
                history:  resolve(__dirname, "history.html"),
            },
        },
    },

    server: {
        port: 17420,
        strictPort: true,
        host: host || false,
        hmr: host ? { protocol: "ws", host, port: 17421 } : undefined,
        watch: { ignored: ["**/src-tauri/**"] },
    },
}));