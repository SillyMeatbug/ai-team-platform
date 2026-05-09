'use client'

import { cn } from '@/lib/utils'
import { useLocale } from '@/components/locale-provider'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { MessageSquare, Users, FolderOpen, Sparkles, LineChart } from 'lucide-react'
import type { ProjectTab } from '@/lib/types'

interface ProjectTabsProps {
  activeTab: ProjectTab
  onChange: (tab: ProjectTab) => void
  projectId?: string
  isCryptoEnabled?: boolean
}

const tabs: { id: ProjectTab; labelKey: string; icon: React.ElementType }[] = [
  { id: 'chat', labelKey: 'tabs.chat', icon: MessageSquare },
  { id: 'agents', labelKey: 'tabs.agents', icon: Users },
  { id: 'files', labelKey: 'tabs.files', icon: FolderOpen },
  { id: 'results', labelKey: 'tabs.results', icon: Sparkles },
  { id: 'paper-trading', labelKey: 'tabs.paperTrading', icon: LineChart },
]

export function ProjectTabs({ activeTab, onChange, projectId, isCryptoEnabled = false }: ProjectTabsProps) {
  const { t } = useLocale()
  const pathname = usePathname()
  const routeByTab: Record<ProjectTab, string> = {
    chat: `/project/${projectId ?? ''}`,
    agents: `/project/${projectId ?? ''}?tab=agents`,
    files: `/project/${projectId ?? ''}?tab=files`,
    results: `/project/${projectId ?? ''}?tab=results`,
    'paper-trading': `/project/${projectId ?? ''}/paper-trading`,
  }

  return (
    <div className="border-b border-border">
      <div className="mx-auto max-w-6xl px-4 sm:px-6">
        <nav className="flex gap-1 overflow-x-auto" aria-label={t('tabs.tabsSr')}>
        {tabs.filter((tab) => tab.id !== 'paper-trading' || isCryptoEnabled).map((tab) => {
          const Icon = tab.icon
          const isActive = activeTab === tab.id
          const isPaper = tab.id === 'paper-trading'
          const href = projectId ? routeByTab[tab.id] : undefined
          const isPaperPath = isPaper && pathname?.endsWith('/paper-trading')
          const active = isPaperPath || isActive
          const content = (
            <>
              <Icon className="w-4 h-4" />
              <span>{t(tab.labelKey)}</span>
              {active && (
                <span className="absolute bottom-0 left-0 right-0 h-0.5 gradient-accent rounded-full" />
              )}
            </>
          )
          if (href) {
            return (
              <Link
                key={tab.id}
                href={href}
                className={cn(
                  'relative flex items-center gap-2 px-4 py-3 text-sm font-medium transition-colors whitespace-nowrap',
                  active ? 'text-primary' : 'text-muted-foreground hover:text-foreground'
                )}
                aria-current={active ? 'page' : undefined}
              >
                {content}
              </Link>
            )
          }
          return (
            <button
              key={tab.id}
              type="button"
              onClick={() => onChange(tab.id)}
              className={cn(
                'relative flex items-center gap-2 px-4 py-3 text-sm font-medium transition-colors whitespace-nowrap',
                active ? 'text-primary' : 'text-muted-foreground hover:text-foreground'
              )}
              aria-current={active ? 'page' : undefined}
            >
              {content}
            </button>
          )
        })}
        </nav>
      </div>
    </div>
  )
}
