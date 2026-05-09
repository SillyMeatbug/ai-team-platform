'use client'

import { useLocale } from '@/components/locale-provider'
import { agentCardDescription } from '@/lib/i18n/agent-cards'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import type { Agent } from '@/lib/types'

interface AgentBadgeProps {
  agent: Agent
  size?: 'sm' | 'md' | 'lg'
  showModel?: boolean
}

export function AgentBadge({ agent, size = 'md', showModel = false }: AgentBadgeProps) {
  const { locale } = useLocale()
  const blurb = agentCardDescription(agent.role, locale)

  const sizeClasses = {
    sm: 'h-6 px-2 text-xs gap-1',
    md: 'h-7 px-2.5 text-sm gap-1.5',
    lg: 'h-8 px-3 text-sm gap-2',
  }

  const dotSizes = {
    sm: 'w-1.5 h-1.5',
    md: 'w-2 h-2',
    lg: 'w-2.5 h-2.5',
  }

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div
            className={`inline-flex items-center rounded-full bg-secondary/80 border border-border/50 ${sizeClasses[size]}`}
          >
            <span
              className={`rounded-full ${dotSizes[size]}`}
              style={{ backgroundColor: agent.color }}
            />
            <span className="font-medium text-foreground">{agent.name}</span>
            {showModel && (
              <span className="font-mono text-muted-foreground text-xs">
                {agent.model}
              </span>
            )}
          </div>
        </TooltipTrigger>
        <TooltipContent side="top" className="border-border bg-card text-foreground">
          <div className="flex flex-col gap-1">
            <span className="font-medium text-white">{agent.name}</span>
            <span className="font-mono text-xs text-muted-foreground">{agent.model}</span>
            <span className="text-xs text-muted-foreground">{blurb}</span>
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}

interface AgentAvatarProps {
  agent: Agent
  size?: 'sm' | 'md' | 'lg'
}

export function AgentAvatar({ agent, size = 'md' }: AgentAvatarProps) {
  const sizeClasses = {
    sm: 'w-6 h-6 text-[10px]',
    md: 'w-8 h-8 text-xs',
    lg: 'w-10 h-10 text-sm',
  }

  const initials = agent.name
    .split(' ')
    .map((w) => w[0])
    .join('')
    .toUpperCase()
    .slice(0, 2)

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div
            className={`flex items-center justify-center rounded-full font-semibold text-white ${sizeClasses[size]}`}
            style={{ backgroundColor: agent.color }}
          >
            {initials}
          </div>
        </TooltipTrigger>
        <TooltipContent side="top" className="border-border bg-card text-foreground">
          <div className="flex flex-col gap-0.5">
            <span className="font-medium text-white">{agent.name}</span>
            <span className="font-mono text-xs text-muted-foreground">{agent.model}</span>
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}
