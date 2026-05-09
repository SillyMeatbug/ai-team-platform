'use client'

import { Card } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { useLocale } from '@/components/locale-provider'
import { agentCardDescription } from '@/lib/i18n/agent-cards'
import { cn } from '@/lib/utils'
import type { Agent } from '@/lib/types'

interface AgentSelectorProps {
  availableAgents: Agent[]
  selectedAgents: string[]
  onSelect: (agentId: string) => void
}

export function AgentSelector({
  availableAgents,
  selectedAgents,
  onSelect,
}: AgentSelectorProps) {
  const { locale, t } = useLocale()
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {availableAgents.map((agent) => {
        const isSelected = selectedAgents.includes(agent.id)
        const line = agentCardDescription(agent.role, locale)
        return (
          <Card
            key={agent.id}
            onClick={() => onSelect(agent.id)}
            className={cn(
              'relative min-w-0 p-4 cursor-pointer transition-all duration-200 border',
              isSelected
                ? 'border-primary bg-primary/5 glow-accent'
                : 'border-border hover:border-primary/50 bg-card'
            )}
          >
            <div className="flex items-start gap-3">
              <div className="pt-0.5">
                <Checkbox
                  checked={isSelected}
                  onCheckedChange={() => onSelect(agent.id)}
                  className="border-border data-[state=checked]:bg-primary data-[state=checked]:border-primary"
                  aria-label={t('agentSelector.selectSr', { name: agent.name })}
                />
              </div>
              <div className="flex-1 min-w-0 overflow-hidden">
                <div className="flex items-center gap-2">
                  <span
                    className="w-3 h-3 rounded-full flex-shrink-0"
                    style={{ backgroundColor: agent.color }}
                  />
                  <h4 className="font-medium text-foreground truncate">
                    {agent.name}
                  </h4>
                  {agent.role === 'crypto_interpreter' && (
                    <span className="rounded-full border border-purple-400/40 bg-purple-500/15 px-2 py-0.5 text-[10px] text-purple-300">
                      👤 Для новичков
                    </span>
                  )}
                </div>
                <p className="mt-1 truncate text-xs font-mono leading-relaxed text-muted-foreground">
                  {agent.model}
                </p>
                <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                  {line}
                </p>
              </div>
            </div>
          </Card>
        )
      })}
    </div>
  )
}
