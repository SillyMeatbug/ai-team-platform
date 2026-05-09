'use client'

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import {
  LOCALE_STORAGE_KEY,
  applyParams,
  localeFromNavigator,
  translate,
  type Locale,
} from '@/lib/i18n/messages'

type LocaleContextValue = {
  locale: Locale
  setLocale: (locale: Locale) => void
  t: (key: string, params?: Record<string, string | number>) => string
}

const LocaleContext = createContext<LocaleContextValue | null>(null)

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>('en')

  useEffect(() => {
    if (typeof window === 'undefined') return
    const stored = window.localStorage.getItem(LOCALE_STORAGE_KEY) as Locale | null
    const resolved: Locale =
      stored === 'en' || stored === 'ru' ? stored : localeFromNavigator()
    setLocaleState(resolved)
    document.documentElement.lang = resolved === 'ru' ? 'ru' : 'en'
  }, [])

  const setLocale = useCallback((next: Locale) => {
    setLocaleState(next)
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(LOCALE_STORAGE_KEY, next)
      document.documentElement.lang = next === 'ru' ? 'ru' : 'en'
    }
  }, [])

  const t = useCallback(
    (key: string, params?: Record<string, string | number>) => {
      return applyParams(translate(locale, key), params)
    },
    [locale]
  )

  const value = useMemo(() => ({ locale, setLocale, t }), [locale, setLocale, t])

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>
}

export function useLocale(): LocaleContextValue {
  const ctx = useContext(LocaleContext)
  if (!ctx) {
    throw new Error('useLocale must be used within LocaleProvider')
  }
  return ctx
}
