'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import Image from 'next/image'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { useLocale } from '@/components/locale-provider'
import { AgentAvatar } from '@/components/agent-badge'
import { FileText, MessageSquare, ChevronRight, Trash2 } from 'lucide-react'
import type { Project } from '@/lib/types'
import cryptoIcon from '@/components/ui/free-icon-crypto-8912327.png'

interface ProjectCardProps {
  project: Project
  onQuickDelete?: (project: Project) => void
  deleting?: boolean
}

export function ProjectCard({ project, onQuickDelete, deleting = false }: ProjectCardProps) {
  const { t } = useLocale()
  const [nowTick, setNowTick] = useState(() => Date.now())
  const lastActivity = formatRelativeTime(project.updatedAt, t, nowTick)
  const messageCount = project.messageCount ?? project.messages.length
  const fileCount = project.fileCount ?? project.files.length

  useEffect(() => {
    const id = window.setInterval(() => setNowTick(Date.now()), 60_000)
    return () => window.clearInterval(id)
  }, [])

  return (
    <Link href={`/project/${project.id}`}>
      <Card className="group bg-card border-border hover:border-primary/50 hover:glow-accent transition-all duration-200 cursor-pointer h-full">
        <CardHeader className="pb-3">
          <div className="flex items-start justify-between">
            <div className="flex-1 min-w-0">
              <h3 className="font-semibold text-foreground group-hover:text-primary transition-colors truncate">
                {project.name}
              </h3>
              {project.isCryptoEnabled && (
                <div className="mt-1 inline-flex items-center gap-1 rounded-full border border-purple-400/30 bg-purple-500/10 px-2 py-0.5">
                  <Image src={cryptoIcon} alt="Crypto project" width={12} height={12} />
                  <span className="text-[10px] text-purple-300">Crypto</span>
                </div>
              )}
              <p className="text-sm text-muted-foreground mt-1 line-clamp-2">
                {project.description}
              </p>
            </div>
            <div className="ml-2 flex items-center gap-1">
              {onQuickDelete ? (
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 text-muted-foreground hover:text-destructive"
                  aria-label={t('project.deleteDialogTitle')}
                  disabled={deleting}
                  onClick={(e) => {
                    e.preventDefault()
                    e.stopPropagation()
                    onQuickDelete(project)
                  }}
                >
                  <Trash2 className="w-4 h-4" />
                </Button>
              ) : null}
              <ChevronRight className="w-5 h-5 text-muted-foreground group-hover:text-primary transition-colors flex-shrink-0" />
            </div>
          </div>
        </CardHeader>
        <CardContent className="pt-0">
          <div className="flex items-center justify-between">
            <div className="flex -space-x-2">
              {project.agents.slice(0, 4).map((agent) => (
                <AgentAvatar key={agent.id} agent={agent} size="sm" />
              ))}
              {project.agents.length > 4 && (
                <div className="w-6 h-6 rounded-full bg-secondary border-2 border-card flex items-center justify-center text-[10px] text-muted-foreground font-medium">
                  +{project.agents.length - 4}
                </div>
              )}
            </div>
            <div className="flex items-center gap-3 text-xs text-muted-foreground">
              <span className="flex items-center gap-1">
                <FileText className="w-3.5 h-3.5" />
                {fileCount}
              </span>
              <span className="flex items-center gap-1">
                <MessageSquare className="w-3.5 h-3.5" />
                {messageCount}
              </span>
            </div>
          </div>
          <div className="mt-3 pt-3 border-t border-border/50">
            <span className="text-xs text-muted-foreground">
              {lastActivity} · {t('projectCard.messageCount', { count: messageCount })}
            </span>
          </div>
        </CardContent>
      </Card>
    </Link>
  )
}

function formatRelativeTime(
  dateString: string,
  t: (key: string, params?: Record<string, string | number>) => string,
  nowMs: number
): string {
  const normalized =
    /(?:Z|[+\-]\d{2}:\d{2})$/.test(dateString) ? dateString : `${dateString}Z`
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) return t('time.justNow')
  const diffMs = nowMs - date.getTime()
  const diffHours = Math.floor(diffMs / (1000 * 60 * 60))
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24))

  if (diffHours < 1) return t('time.justNow')
  if (diffHours < 24) return t('time.hoursAgo', { n: diffHours })
  if (diffDays < 7) return t('time.daysAgo', { n: diffDays })
  return date.toLocaleDateString(t('time.dateLocale'))
}
