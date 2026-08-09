import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

function localSecretGuard() {
  const forbidden = ["local_api_token", "x-boss-local-token", "api_key"];
  return {
    name: "local-secret-guard",
    closeBundle() {
      const files: string[] = [];
      const visit = (directory: string) => {
        for (const name of readdirSync(directory)) {
          const path = join(directory, name);
          if (statSync(path).isDirectory()) visit(path);
          else files.push(path);
        }
      };
      visit("dist");
      const leaked = files.find((path) => {
        const content = readFileSync(path, "utf8").toLowerCase();
        return forbidden.some((term) => content.includes(term));
      });
      if (leaked) throw new Error(`Sensitive configuration name found in frontend build: ${leaked}`);
    },
  };
}

export default defineConfig({
  plugins: [react(), localSecretGuard()],
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
  },
});
