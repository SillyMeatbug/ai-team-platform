'use client'

import ReactMarkdown from 'react-markdown'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { AgentBadge } from '@/components/agent-badge'
import { useLocale } from '@/components/locale-provider'
import { Download, Sparkles } from 'lucide-react'
import type { AgentResult, Agent } from '@/lib/types'

interface ResultsViewProps {
  results: AgentResult[]
  agents: Agent[]
}

const categoryKeys: Record<AgentResult['category'], string> = {
  architecture: 'results.categoryArchitecture',
  design: 'results.categoryDesign',
  code: 'results.categoryCode',
  content: 'results.categoryContent',
}

export function ResultsView({ results, agents }: ResultsViewProps) {
  const { t } = useLocale()
  const getAgent = (agentId: string) => agents.find((a) => a.id === agentId)

  const resultsByCategory = results.reduce(
    (acc, result) => {
      if (!acc[result.category]) acc[result.category] = []
      acc[result.category].push(result)
      return acc
    },
    {} as Record<AgentResult['category'], AgentResult[]>
  )

  const categories = Object.keys(categoryKeys) as AgentResult['category'][]

  if (results.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16">
        <div className="p-4 rounded-full bg-secondary/50 mb-4">
          <Sparkles className="w-8 h-8 text-muted-foreground" />
        </div>
        <h3 className="text-lg font-medium text-foreground mb-2">{t('results.emptyTitle')}</h3>
        <p className="text-sm text-muted-foreground text-center max-w-sm">
          {t('results.emptySubtitle')}
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-8">
      {categories.map((category) => {
        const categoryResults = resultsByCategory[category]
        if (!categoryResults || categoryResults.length === 0) return null

        return (
          <div key={category}>
            <h3 className="text-sm font-medium text-muted-foreground uppercase tracking-wider mb-4">
              {t(categoryKeys[category])}
            </h3>
            <div className="space-y-4">
              {categoryResults.map((result) => {
                const agent = getAgent(result.agentId)
                return (
                  <Card key={result.id} className="bg-card border-border">
                    <CardHeader className="pb-3">
                      <div className="flex items-start justify-between gap-4">
                        <div className="flex-1 min-w-0">
                          <CardTitle className="text-base font-semibold text-foreground">
                            {result.title}
                          </CardTitle>
                          <div className="flex items-center gap-2 mt-2">
                            {agent && <AgentBadge agent={agent} size="sm" />}
                            <span className="text-xs text-muted-foreground">
                              {result.createdAt}
                            </span>
                          </div>
                        </div>
                        <Button
                          variant="outline"
                          size="sm"
                          className="flex-shrink-0"
                          aria-label={t('results.downloadSr', { title: result.title })}
                        >
                          <Download className="w-4 h-4 mr-1.5" />
                          {t('results.download')}
                        </Button>
                      </div>
                    </CardHeader>
                    <CardContent>
                      <div className="prose prose-sm prose-invert max-w-none prose-p:text-foreground prose-headings:text-foreground prose-strong:text-foreground prose-li:text-foreground prose-code:text-accent">
                        <ReactMarkdown
                          components={{
                            code: ({ className, children, ...props }) => {
                              const isInline = !className
                              return isInline ? (
                                <code
                                  className="px-1 py-0.5 rounded bg-secondary font-mono text-xs"
                                  {...props}
                                >
                                  {children}
                                </code>
                              ) : (
                                <pre className="p-3 rounded-md bg-background overflow-x-auto border border-border">
                                  <code className="font-mono text-xs" {...props}>
                                    {children}
                                  </code>
                                </pre>
                              )
                            },
                          }}
                        >
                          {result.content}
                        </ReactMarkdown>
                      </div>
                    </CardContent>
                  </Card>
                )
              })}
            </div>
          </div>
        )
      })}
    </div>
  )
}
