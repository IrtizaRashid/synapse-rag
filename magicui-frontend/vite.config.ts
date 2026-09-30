import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: resolve(__dirname, "../static/magicui"),
    emptyOutDir: true,
    lib: {
      entry: resolve(__dirname, "src/main.tsx"),
      formats: ["es"],
      fileName: () => "magicui.js",
    },
    cssCodeSplit: false,
    rollupOptions: {
      output: { assetFileNames: (asset) => asset.name?.endsWith(".css") ? "magicui.css" : "[name][extname]" },
    },
  },
});
