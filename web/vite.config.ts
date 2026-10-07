// @lovable.dev/vite-tanstack-config already includes the following — do NOT add them manually
// or the app will break with duplicate plugins:
//   - TanStack devtools (dev-only, first), tanstackStart, viteReact, tailwindcss, tsConfigPaths,
//     nitro (build-only using cloudflare as a default target), VITE_* env injection, @ path alias,
//     React/TanStack dedupe, error logger plugins, and sandbox detection (port/host/strictPort).
// You can pass additional config via defineConfig({ vite: { ... }, etc... }) if needed.
import { defineConfig } from "@lovable.dev/vite-tanstack-config";

export default defineConfig({
  // Fully client-rendered SPA: no SSR, no server functions/routes. The build
  // emits a static client folder with index.html at its root (Capacitor-ready).
  tanstackStart: {
    spa: { enabled: true, prerender: { outputPath: "/index.html" } },
    prerender: { enabled: true, autoStaticPathsDiscovery: false },
  },
});
