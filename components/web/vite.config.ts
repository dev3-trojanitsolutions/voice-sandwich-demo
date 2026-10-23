import { resolve } from "node:path";
import { svelte } from "@sveltejs/vite-plugin-svelte";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [svelte(), tailwindcss()],
  build: {
    // The order page at /, the desk at /desk/, and the login and logout pages
    rollupOptions: {
      input: {
        order: resolve(__dirname, "index.html"),
        desk: resolve(__dirname, "desk/index.html"),
        login: resolve(__dirname, "login/index.html"),
        logout: resolve(__dirname, "logout/index.html"),
      },
    },
  },
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/ws": {
        target: "ws://localhost:8000",
        ws: true,
      },
    },
  },
});
