import type { AgentRole } from '@/lib/types'
import type { Locale } from '@/lib/i18n/messages'
import { translate } from '@/lib/i18n/messages'

/** Короткая подпись роли для карточек и тултипов (зависит от локали UI). */
export function agentCardDescription(role: AgentRole, locale: Locale): string {
  const key = `agentCards.${role}`
  const line = translate(locale, key)
  if (line !== key) return line
  return translate(locale, 'agentCards.fallback')
}
