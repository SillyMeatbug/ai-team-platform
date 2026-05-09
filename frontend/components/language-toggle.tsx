'use client'

import { Languages } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useLocale } from '@/components/locale-provider'
import type { Locale } from '@/lib/i18n/messages'

const OPTIONS: { id: Locale; label: string }[] = [
  { id: 'en', label: 'EN' },
  { id: 'ru', label: 'RU' },
]

export function LanguageToggle({ className }: { className?: string }) {
  const { locale, setLocale, t } = useLocale()

  return (
    <div
      className={cn(
        'inline-flex items-center gap-1 rounded-lg border border-border bg-secondary/60 p-0.5 shadow-sm',
        className
      )}
      role="group"
      aria-label={t('common.language')}
    >
      <Languages className="ml-1 h-3.5 w-3.5 text-muted-foreground shrink-0 hidden sm:block" aria-hidden />
      {OPTIONS.map(({ id, label }) => {
        const active = locale === id
        return (
          <button
            key={id}
            type="button"
            onClick={() => setLocale(id)}
            className={cn(
              'min-w-[2rem] rounded-md px-2 py-1 text-xs font-semibold transition-colors',
              active
                ? 'gradient-accent text-white shadow-sm'
                : 'text-muted-foreground hover:text-foreground'
            )}
            aria-pressed={active}
          >
            {label}
          </button>
        )
      })}
    </div>
  )
}
