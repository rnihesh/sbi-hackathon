import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emit a self-contained server bundle (.next/standalone/server.js) so the
  // production Docker image ships only the files it needs to run.
  output: "standalone",
  // TLS is terminated by the reverse proxy in front of the container.
  poweredByHeader: false,
};

export default nextConfig;
