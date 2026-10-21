/** @type {import('next').NextConfig} */
export default {
  reactStrictMode: true,
  // lets the tunnel demo build to its own directory without clobbering a running `next dev`
  distDir: process.env.NEXT_DIST_DIR || ".next",
};
