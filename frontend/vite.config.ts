import { defineConfig } from "vite";

export default defineConfig({
  base: "/dashboard/",
  build: {
    outDir: "../src/notehub_client/runtimes/web/static",
    emptyOutDir: true,
  },
});
