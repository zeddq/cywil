/** @type {import('next').NextConfig} */
const nextConfig = {
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/:path*',
      },
    ]
  },
  // Disable the default Next.js compression in favor of HTTPS compression
  compress: false,
  // Allow self-signed certificates in development
  experimental: {
    serverActions: {
      allowedOrigins: ['https://localhost:3443'],
    },
  },
  productionBrowserSourceMaps: true,
  // Enable standalone output for Docker
  output: 'standalone',
}

module.exports = nextConfig
