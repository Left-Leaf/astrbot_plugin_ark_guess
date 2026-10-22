import { defineConfig } from "vitest/config";

export default defineConfig({
  base: "/astrbot_plugin_ark_guess/",
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  test: {
    environment: "node",
  },
});
