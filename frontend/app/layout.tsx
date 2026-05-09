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

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${inter.variable} ${jetbrainsMono.variable} dark bg-background`}
    >
      <body className="font-sans antialiased min-h-screen">
        <LocaleProvider>
          {children}
          <Toaster />
        </LocaleProvider>
        {process.env.NODE_ENV === 'production' && <Analytics />}
      </body>
    </html>
  )
}
