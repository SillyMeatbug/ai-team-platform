import type { Metadata, Viewport } from 'next'
import { Inter, JetBrains_Mono } from 'next/font/google'
import { Analytics } from '@vercel/analytics/next'
import { LocaleProvider } from '@/components/locale-provider'
import { Toaster } from '@/components/ui/sonner'
import './globals.css'

const inter = Inter({ 
  subsets: ["latin"],
  variable: '--font-inter',
})

const jetbrainsMono = JetBrains_Mono({ 
  subsets: ["latin"],
  variable: '--font-jetbrains-mono',
})

export const metadata: Metadata = {
  title: 'AI Team Platform',
  description: 'Create projects, select AI agents, and collaborate via group chat',
  generator: 'v0.app',
  icons: {
    icon: [{ url: '/icon_favicon.png', type: 'image/png' }],
    apple: '/icon_favicon.png',
  },
}

export const viewport: Viewport = {
  themeColor: '#0a0e17',
  colorScheme: 'dark',
}

/** Публичный URL бэкенда для браузера: на Railway берётся из env во время запроса (не только из bake сборки). */
function publicApiUrlForClient(): string {
  return (
    process.env.BACKEND_PUBLIC_URL?.trim() ||
    process.env.NEXT_PUBLIC_API_URL?.trim() ||
    process.env.NEXT_PUBLIC_API_BASE_URL?.trim() ||
    ''
  )
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  const apiPublicUrl = publicApiUrlForClient()

  return (
    <html
      lang="en"
      suppressHydrationWarning
      data-api-public-url={apiPublicUrl}
      className={`${inter.variable} ${jetbrainsMono.variable} dark bg-background`}
    >
      <body className="font-sans antialiased min-h-screen">
        <LocaleProvider>
          {children}
          <Toaster />
        </LocaleProvider>
        {process.env.NODE_ENV === 'production' && process.env.VERCEL === '1' ? (
          <Analytics />
        ) : null}
      </body>
    </html>
  )
}
