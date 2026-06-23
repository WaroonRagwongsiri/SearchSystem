/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone", // ponytail: lets the Docker image run `node server.js` without node_modules
};

export default nextConfig;
