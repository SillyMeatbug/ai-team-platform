import type { Agent } from '@/lib/types'
import { agentCardDescription } from '@/lib/i18n/agent-cards'

/**
 * Статичные карточки для проверки вёрстки без бэкенда.
 * Включение: NEXT_PUBLIC_UI_DEMO_AGENTS=true в .env.local
 * Добавление в проект через API с этими id не сработает — только UI.
 */
export const UI_DEMO_AGENTS: Agent[] = [
  {
    id: 'ui-demo-analyst',
    name: 'Business Analyst',
    model: 'meta-llama/llama-3.3-70b-instruct',
    role: 'analyst',
    color: '#3b82f6',
    description: agentCardDescription('analyst', 'en'),
  },
  {
    id: 'ui-demo-designer',
    name: 'UI/UX Designer',
    model: 'meta-llama/llama-3.3-70b-instruct',
    role: 'designer',
    color: '#8b5cf6',
    description: agentCardDescription('designer', 'en'),
  },
  {
    id: 'ui-demo-frontend',
    name: 'Frontend Dev',
    model: 'qwen/qwen-2.5-coder-32b-instruct',
    role: 'frontend_dev',
    color: '#10b981',
    description: agentCardDescription('frontend_dev', 'en'),
  },
]

function uiDemoAgentsEnabled(): boolean {
  return process.env.NEXT_PUBLIC_UI_DEMO_AGENTS === 'true'
}

/** Добавляет статические demo-карточки к ответу API при включённом флаге. */
export function mergeAgentsForUi(apiAgents: Agent[]): Agent[] {
  if (!uiDemoAgentsEnabled()) return apiAgents
  const seen = new Set(apiAgents.map((a) => a.id))
  const prefix = UI_DEMO_AGENTS.filter((d) => !seen.has(d.id))
  return [...prefix, ...apiAgents]
}
