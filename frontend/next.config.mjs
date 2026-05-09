/** @type {import('next').NextConfig} */
const nextConfig = {
  /** Убирает круглую кнопку «N» (индикатор dev-инструментов) в углу экрана */
  devIndicators: false,
  output: 'standalone',
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
}

export default nextConfig
