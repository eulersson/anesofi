/** @type {import('next').NextConfig} */
const nextConfig = {
  // Next.js can automatically create a standalone folder that copies only the necessary
  // files for a production deployment including select files in node_modules. This will
  // create a folder at .next/standalone which can then be deployed on its own without
  // installing node_modules. Additionally, a minimal server.js file is also output
  // which can be used instead of next start. This minimal server does not copy the
  // public or .next/static folders by default as these should ideally be handled by a
  // CDN instead, although these folders can be copied to the standalone/public and
  // standalone/.next/static folders manually, after which server.js file will serve
  // these automatically.
  //
  //   https://nextjs.org/docs/app/api-reference/next-config-js/output
  //
  // output: "standalone"
};

export default nextConfig;
