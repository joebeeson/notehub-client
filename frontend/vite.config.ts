import { defineConfig } from "vite";

export default defineConfig({
  base: "/dashboard/",
  build: {
    manifest: "asset-manifest.json",
    outDir: "../src/notehub_client/runtimes/web/static",
    emptyOutDir: true,
  },
});
