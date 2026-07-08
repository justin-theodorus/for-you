import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev server is reachable from the host at :5173. `usePolling` keeps hot-reload working
// across the Docker bind mount (inotify events don't cross the boundary reliably).
export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    watch: { usePolling: true },
  },
});
