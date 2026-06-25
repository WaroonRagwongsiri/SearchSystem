/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone", // ponytail: lets the Docker image run `node server.js` without node_modules
  // Browser calls same-origin /api/*; the Next server (on the docker network) proxies to the backend.
  // Correct routing for a client-rendered app: the browser can't resolve the `backend` service name,
  // so it hits the Next server (same origin) which can. Backend must be reachable as http://backend:8000.
  async rewrites() {
    return [{ source: "/api/:path*", destination: "http://backend:8000/:path*" }];
  },
};

export default nextConfig;
