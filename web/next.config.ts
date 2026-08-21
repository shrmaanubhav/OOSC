import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // "standalone" traces the minimal set of files a production server
  // needs (no full node_modules) -- keeps the Docker runtime image small.
  // Has no effect on `next dev`, so the existing non-Docker `npm run dev`
  // workflow (README/run.sh) is unaffected.
  output: "standalone",
};

export default nextConfig;
