import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import { resolve } from "path";

// @ts-expect-error process is a nodejs global
const host = process.env.TAURI_DEV_HOST;

export default defineConfig(async () => ({
    plugins: [vue()],
    clearScreen: false,

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