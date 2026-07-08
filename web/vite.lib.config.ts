// Library build of the design system for the Claude Design sync (plan.md §9, Phase D).
// Emits a single ESM bundle + one CSS file to dist-lib/, with React left external.
// This is what design-sync's converter points `--entry` at.

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import dts from "vite-plugin-dts";

export default defineConfig({
  plugins: [
    react(),
    dts({
      // Include the type modules the components reference (api/types, app/preferences)
      // so the emitted component .d.ts have resolvable prop contracts.
      include: [
        "src/design-system/**/*.ts",
        "src/design-system/**/*.tsx",
        "src/api/types.ts",
        "src/app/preferences.ts",
      ],
      insertTypesEntry: true,
    }),
  ],
  build: {
    outDir: "dist-lib",
    emptyOutDir: true,
    cssCodeSplit: false,
    sourcemap: false,
    lib: {
      entry: "src/design-system/index.ts",
      formats: ["es"],
      fileName: () => "foryou-ds.js",
    },
    rollupOptions: {
      external: ["react", "react-dom", "react/jsx-runtime"],
    },
  },
});
