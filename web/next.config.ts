import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Minimal self-contained server for the Cloud Run container image.
  output: "standalone",
};

export default nextConfig;
