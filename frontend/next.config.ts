import type { NextConfig } from "next";

const config: NextConfig = {
  devIndicators: false,
  distDir: process.env.KWIKVOICE_NEXT_DIST_DIR || ".next",
};

export default config;
