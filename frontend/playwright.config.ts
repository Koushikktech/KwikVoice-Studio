import { defineConfig, devices } from "@playwright/test";

const frontend = "http://127.0.0.1:3001";
const backend = "http://127.0.0.1:8001";

export default defineConfig({
  testDir: "./tests",
  workers: 1,
  timeout: 30000,
  use: {
    ...devices["Desktop Chrome"],
    channel: process.env.KWIKVOICE_BROWSER_CHANNEL || undefined,
    baseURL: frontend,
  },
  webServer: [
    {
      command: "uv run uvicorn chaoslab.main:app --host 127.0.0.1 --port 8001",
      cwd: "../backend",
      url: backend + "/api/health",
      env: { GEMINI_API_KEY: "", WORKBENCH_ORIGINS: frontend },
    },
    {
      command: "npm run dev -- --hostname 127.0.0.1 --port 3001",
      url: frontend,
      env: { NEXT_PUBLIC_API_URL: backend, KWIKVOICE_NEXT_DIST_DIR: ".next-test" },
    },
  ],
});
