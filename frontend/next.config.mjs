/** Контроль NEXT_PUBLIC_* при сборке Docker — см. frontend/Dockerfile (RUN перед npm run build). */

/** @type {import('next').NextConfig} */
const nextConfig = {
  /** Убирает круглую кнопку «N» (индикатор dev-инструментов) в углу экрана */
  devIndicators: false,
  /** Стабильный резолв пакетов в dev/prod (полезно для sonner и др. при Turbopack/webpack). */
  transpilePackages: ['sonner'],
  output: 'standalone',
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  },
}

export default nextConfig
