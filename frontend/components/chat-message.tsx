'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useLocale } from '@/components/locale-provider'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import rehypeRaw from 'rehype-raw'
import rehypeSanitize, { defaultSchema } from 'rehype-sanitize'
import { AgentAvatar, AgentBadge } from '@/components/agent-badge'
import { FileText, Image, File, Copy, ChevronDown, ChevronUp, X } from 'lucide-react'
import { cn } from '@/lib/utils'
import { getDownloadUrl } from '@/lib/api'
import type { ChatMessage as ChatMessageType, Agent, ProjectFile } from '@/lib/types'

interface ChatMessageProps {
  message: ChatMessageType
  agent?: Agent
  contextNote?: string
  isStreaming?: boolean
  canOpenTrade?: boolean
  inPortfolio?: boolean
  onOpenTrade?: (message: ChatMessageType) => void
}

const agentMarkdownComponents = {
  p: ({ children }: { children?: React.ReactNode }) => (
    <p className="mb-2 whitespace-pre-wrap break-words last:mb-0">{children}</p>
  ),
  ul: ({ children }: { children?: React.ReactNode }) => (
    <ul className="mb-2 list-disc space-y-1 pl-5 last:mb-0">{children}</ul>
  ),
  ol: ({ children }: { children?: React.ReactNode }) => (
    <ol className="mb-2 list-decimal space-y-1 pl-5 last:mb-0">{children}</ol>
  ),
  li: ({ children }: { children?: React.ReactNode }) => <li className="leading-relaxed">{children}</li>,
  strong: ({ children }: { children?: React.ReactNode }) => (
    <strong className="font-semibold text-foreground">{children}</strong>
  ),
  code: ({ className, children, ...props }: React.ComponentProps<'code'> & { children?: React.ReactNode }) => {
    const isInline = !className
    return isInline ? (
      <code className="px-1 py-0.5 rounded bg-background/50 font-mono text-xs" {...props}>
        {children}
      </code>
    ) : (
      <pre className="p-3 rounded-md bg-background/80 overflow-x-auto">
        <code className="font-mono text-xs" {...props}>
          {children}
        </code>
      </pre>
    )
  },
}

const safeSchema = {
  ...defaultSchema,
  tagNames: ['p', 'strong', 'em', 'ul', 'ol', 'li', 'a', 'img', 'pre', 'code', 'blockquote', 'hr', 'br', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'],
  attributes: {
    ...defaultSchema.attributes,
    a: [...(defaultSchema.attributes?.a ?? []), 'href', 'title', 'target', 'rel'],
    img: [...(defaultSchema.attributes?.img ?? []), 'src', 'alt', 'title', 'loading'],
    code: [...(defaultSchema.attributes?.code ?? []), 'className'],
    pre: [...(defaultSchema.attributes?.pre ?? []), 'className'],
  },
  protocols: {
    ...defaultSchema.protocols,
    href: ['http', 'https', 'mailto'],
    src: ['http', 'https', 'data'],
  },
}

let highlighterPromise: Promise<any> | null = null

async function getHighlighter() {
  if (!highlighterPromise) {
    highlighterPromise = (async () => {
      const [{ default: hljs }, { default: js }, { default: ts }, { default: py }, { default: sql }, { default: bash }, { default: json }, { default: css }, { default: xml }] = await Promise.all([
        import('highlight.js/lib/core'),
        import('highlight.js/lib/languages/javascript'),
        import('highlight.js/lib/languages/typescript'),
        import('highlight.js/lib/languages/python'),
        import('highlight.js/lib/languages/sql'),
        import('highlight.js/lib/languages/bash'),
        import('highlight.js/lib/languages/json'),
        import('highlight.js/lib/languages/css'),
        import('highlight.js/lib/languages/xml'),
      ])
      hljs.registerLanguage('javascript', js)
      hljs.registerLanguage('js', js)
      hljs.registerLanguage('typescript', ts)
      hljs.registerLanguage('ts', ts)
      hljs.registerLanguage('python', py)
      hljs.registerLanguage('py', py)
      hljs.registerLanguage('sql', sql)
      hljs.registerLanguage('bash', bash)
      hljs.registerLanguage('sh', bash)
      hljs.registerLanguage('json', json)
      hljs.registerLanguage('css', css)
      hljs.registerLanguage('html', xml)
      return hljs
    })()
  }
  return highlighterPromise
}

let mermaidPromise: Promise<any> | null = null

async function getMermaid() {
  if (!mermaidPromise) {
    mermaidPromise = (async () => {
      const mod = await import('mermaid')
      const mermaid = mod.default
      mermaid.initialize({
        startOnLoad: false,
        securityLevel: 'strict',
        theme: 'default',
        suppressErrorRendering: true,
      })
      return mermaid
    })()
  }
  return mermaidPromise
}

function CodeBlock({ code, language, t }: { code: string; language: string; t: (k: string, p?: Record<string, string | number>) => string }) {
  const [html, setHtml] = useState('')
  const [copied, setCopied] = useState(false)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let active = true
    setLoading(true)
    void (async () => {
      try {
        const hljs = await getHighlighter()
        const lang = language.toLowerCase()
        const rendered = hljs.getLanguage(lang)
          ? hljs.highlight(code, { language: lang }).value
          : hljs.highlightAuto(code).value
        if (active) setHtml(rendered)
      } catch {
        if (active) setHtml(code.replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' }[c] as string)))
      } finally {
        if (active) setLoading(false)
      }
    })()
    return () => {
      active = false
    }
  }, [code, language])

  const onCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      setTimeout(() => setCopied(false), 1200)
    } catch {
      // ignore
    }
  }, [code])

  return (
    <div className="my-3 overflow-hidden rounded-md border border-border/70 bg-[#0f172a]">
      <div className="flex items-center justify-between border-b border-border/70 bg-[#111827] px-3 py-1.5 text-[11px]">
        <span className="font-mono uppercase tracking-wide text-slate-300">{language || 'text'}</span>
        <button
          type="button"
          onClick={onCopy}
          className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-slate-200 hover:bg-white/10"
        >
          <Copy className="h-3 w-3" />
          {copied ? t('chat.codeCopied') : t('chat.codeCopy')}
        </button>
      </div>
      <pre className="overflow-x-auto p-3 text-xs leading-5">
        {loading ? (
          <code className="text-slate-400">{t('chat.codeLoading')}</code>
        ) : (
          <code
            className="hljs !bg-transparent text-slate-100"
            dangerouslySetInnerHTML={{ __html: html }}
          />
        )}
      </pre>
    </div>
  )
}

function MermaidBlock({ chart, t }: { chart: string; t: (k: string, p?: Record<string, string | number>) => string }) {
  const [svg, setSvg] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState(true)

  useEffect(() => {
    let active = true
    setLoading(true)
    setError(null)
    void (async () => {
      try {
        const mermaid = await getMermaid()
        const id = `mmd-${Math.random().toString(36).slice(2)}`
        const { svg } = await mermaid.render(id, chart)
        if (active) setSvg(svg)
      } catch {
        if (active) setError(t('chat.mermaidError'))
      } finally {
        if (active) setLoading(false)
      }
    })()
    return () => {
      active = false
    }
  }, [chart, t])

  return (
    <div className="my-3 rounded-md border border-border/70 bg-background/50">
      <div className="flex items-center justify-between border-b border-border/70 px-3 py-2 text-xs text-muted-foreground">
        <span className="font-mono">Mermaid</span>
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="inline-flex items-center gap-1 rounded px-2 py-0.5 hover:bg-secondary"
        >
          {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          {expanded ? t('chat.collapse') : t('chat.expand')}
        </button>
      </div>
      {expanded && (
        <div className="p-3">
          {loading && <div className="h-24 animate-pulse rounded bg-secondary/60" />}
          {!loading && error && <div className="text-xs text-amber-300">{error}</div>}
          {!loading && !error && (
            <div className="overflow-x-auto rounded border border-border/60 bg-slate-50 p-2">
              <div dangerouslySetInnerHTML={{ __html: svg }} />
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function MarkdownImage({
  src,
  alt,
  onPreview,
  t,
}: {
  src?: string
  alt?: string
  onPreview: (src: string, alt?: string) => void
  t: (k: string, p?: Record<string, string | number>) => string
}) {
  const [broken, setBroken] = useState(false)
  if (!src || broken) {
    return <div className="my-2 rounded border border-border/60 bg-secondary/40 p-2 text-xs text-muted-foreground">{t('chat.imageUnavailable')}</div>
  }
  return (
    <button type="button" onClick={() => onPreview(src, alt)} className="my-2 block w-full text-left">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img
        src={src}
        alt={alt || 'image'}
        loading="lazy"
        onError={() => setBroken(true)}
        className="max-h-[420px] w-auto max-w-full rounded border border-border/60 object-contain"
      />
    </button>
  )
}

function parseDebateSection(content: string, start: string, nextMarkers: string[]): string {
  const startIdx = content.indexOf(start)
  if (startIdx < 0) return ''
  const from = startIdx + start.length
  const tail = content.slice(from)
  let end = tail.length
  for (const marker of nextMarkers) {
    const idx = tail.indexOf(marker)
    if (idx >= 0 && idx < end) end = idx
  }
  return tail.slice(0, end).trim()
}

function formatDebateBullets(text: string): string[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line) => (line.startsWith('-') ? line.slice(1).trim() : line))
}

function DebateSummaryBlock({ content }: { content: string }) {
  const { t } = useLocale()
  const consensus = parseDebateSection(content, '✅ Итог / Консенсус:', [
    '🧩 Ключевые аргументы:',
    '⚠️ Открытые вопросы / Разногласия:',
    '📈 Уровень уверенности:',
    '🔍',
    '🧩 Key arguments:',
    '⚠️ Open questions / disagreements:',
    '📈 Confidence level:',
  ]) || parseDebateSection(content, '✅ Consensus:', [
    '🧩 Key arguments:',
    '⚠️ Open questions / disagreements:',
    '📈 Confidence level:',
    '🔍',
    '🧩 Ключевые аргументы:',
    '⚠️ Открытые вопросы / Разногласия:',
    '📈 Уровень уверенности:',
  ])
  const argumentsText = parseDebateSection(content, '🧩 Ключевые аргументы:', [
    '⚠️ Открытые вопросы / Разногласия:',
    '📈 Уровень уверенности:',
    '🔍',
    '⚠️ Open questions / disagreements:',
    '📈 Confidence level:',
  ]) || parseDebateSection(content, '🧩 Key arguments:', [
    '⚠️ Open questions / disagreements:',
    '📈 Confidence level:',
    '🔍',
    '⚠️ Открытые вопросы / Разногласия:',
    '📈 Уровень уверенности:',
  ])
  const disagreements = parseDebateSection(content, '⚠️ Открытые вопросы / Разногласия:', [
    '📈 Уровень уверенности:',
    '🔍',
    '📈 Confidence level:',
  ]) || parseDebateSection(content, '⚠️ Open questions / disagreements:', [
    '📈 Confidence level:',
    '🔍',
    '📈 Уровень уверенности:',
  ])
  const confidence = parseDebateSection(content, '📈 Уровень уверенности:', ['🔍']) ||
    parseDebateSection(content, '📈 Confidence level:', ['🔍'])
  const bullets = formatDebateBullets(argumentsText)
  const disagreementBullets = formatDebateBullets(disagreements)

  return (
    <div className="space-y-3 text-sm leading-relaxed">
      {consensus && (
        <div className="rounded-md border border-emerald-500/25 bg-emerald-500/10 p-3">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-emerald-300">{t('chat.debateSummaryConsensus')}</p>
          <p className="whitespace-pre-wrap break-words text-foreground">{consensus}</p>
        </div>
      )}

      {bullets.length > 0 && (
        <div className="rounded-md border border-primary/20 bg-primary/5 p-3">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-primary">{t('chat.debateSummaryKeyArguments')}</p>
          <ul className="list-disc space-y-1 pl-5 text-foreground">
            {bullets.map((item, idx) => (
              <li key={`${idx}-${item.slice(0, 24)}`}>{item}</li>
            ))}
          </ul>
        </div>
      )}

      {disagreementBullets.length > 0 && (
        <div className="rounded-md border border-amber-400/25 bg-amber-400/10 p-3">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-amber-200">
            {t('chat.debateSummaryOpenQuestions')}
          </p>
          <ul className="list-disc space-y-1 pl-5 text-foreground">
            {disagreementBullets.map((item, idx) => (
              <li key={`${idx}-${item.slice(0, 24)}`}>{item}</li>
            ))}
          </ul>
        </div>
      )}

      {confidence && (
        <div className="rounded-md border border-border/70 bg-background/30 px-3 py-2">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">{t('chat.debateSummaryConfidence')}: </span>
          <span className="text-sm font-medium text-foreground">{confidence}</span>
        </div>
      )}
    </div>
  )
}

function MessageBody({
  content,
  isUser,
  onPreviewImage,
}: {
  content: string
  isUser: boolean
  onPreviewImage: (src: string, alt?: string) => void
}) {
  const { t } = useLocale()
  const isDebateSummaryRu =
    content.includes('✅ Итог / Консенсус:') &&
    content.includes('🧩 Ключевые аргументы:') &&
    content.includes('📈 Уровень уверенности:')
  const isDebateSummaryEn =
    content.includes('✅ Consensus:') &&
    content.includes('🧩 Key arguments:') &&
    content.includes('📈 Confidence level:')
  const isDebateSummary = isDebateSummaryRu || isDebateSummaryEn

  if (!isUser) {
    if (isDebateSummary) {
      return <DebateSummaryBlock content={content} />
    }
    return (
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw, [rehypeSanitize, safeSchema]]}
        components={{
          ...agentMarkdownComponents,
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer" className="text-primary underline underline-offset-2">
              {children}
            </a>
          ),
          img: ({ src, alt }) => (
            <MarkdownImage src={src} alt={alt} onPreview={onPreviewImage} t={t} />
          ),
          code: ({ className, children, ...props }) => {
            const raw = String(children ?? '').replace(/\n$/, '')
            const lang = className?.replace('language-', '') ?? ''
            const isInline = !className && !raw.includes('\n')
            if (isInline) {
              return (
                <code className="rounded bg-background/60 px-1 py-0.5 font-mono text-xs" {...props}>
                  {children}
                </code>
              )
            }
            if (lang.toLowerCase() === 'mermaid') {
              return <MermaidBlock chart={raw} t={t} />
            }
            return <CodeBlock code={raw} language={lang} t={t} />
          },
        }}
      >
        {content}
      </ReactMarkdown>
    )
  }

  const segments = content.split(/(@[A-Za-z][A-Za-z0-9_\-]*)/g)
  return (
    <>
      {segments.map((seg, i) => {
        if (/^@[A-Za-z][A-Za-z0-9_\-]*$/.test(seg)) {
          return (
            <span key={i} className="text-blue-400 font-medium">
              {seg}
            </span>
          )
        }
        if (!seg) return null
        return (
          <span key={i} className="whitespace-pre-wrap break-words">
            {seg}
          </span>
        )
      })}
    </>
  )
}

export function ChatMessage({
  message,
  agent,
  contextNote,
  isStreaming = false,
  canOpenTrade = false,
  inPortfolio = false,
  onOpenTrade,
}: ChatMessageProps) {
  const { t } = useLocale()
  const isUser = message.agentId === 'user'
  const displayAgent = !isUser ? agent ?? message.agentSnapshot : undefined
  const isInterpreter = displayAgent?.role === 'crypto_interpreter'
  const hasEmptyAgentReply = !isUser && !message.content?.trim()

  const normalizedContent = (message.content || '').trim()
  const isCancelledText =
    normalizedContent === 'Дискуссия отменена пользователем.' ||
    normalizedContent === 'Discussion was cancelled by the user.'
  const renderedContent = isCancelledText ? t('chat.debateCancelledByUser') : message.content
  const [previewImage, setPreviewImage] = useState<{ src: string; alt?: string } | null>(null)

  const fileIcon = (type: ProjectFile['type']) => {
    switch (type) {
      case 'image':
        return <Image className="w-3.5 h-3.5" />
      case 'pdf':
      case 'doc':
        return <FileText className="w-3.5 h-3.5" />
      default:
        return <File className="w-3.5 h-3.5" />
    }
  }

  return (
    <div
      className={cn(
        'flex gap-3',
        isUser ? 'flex-row-reverse' : 'flex-row'
      )}
    >
      <div
        className={cn(
          'max-w-[85%] md:max-w-[75%]',
          isUser ? 'items-end' : 'items-start'
        )}
      >
        {/* Header */}
        <div
          className={cn(
            'flex items-center gap-2 mb-1.5',
            isUser ? 'flex-row-reverse' : 'flex-row'
          )}
        >
          {isUser ? (
            <span className="text-sm font-medium text-foreground">{t('chat.you')}</span>
          ) : displayAgent ? (
            <AgentBadge agent={displayAgent} size="sm" />
          ) : (
            <span className="text-sm font-medium text-muted-foreground">{t('chat.agentFallback')}</span>
          )}
          <span className="text-xs text-muted-foreground">{message.timestamp}</span>
          {message.isGroupDiscussion && (
            <span className="text-xs px-1.5 py-0.5 rounded bg-primary/20 text-primary font-medium">
              {t('chat.discussion')}
            </span>
          )}
        </div>
        {contextNote && !isUser && (
          <div className="mb-1 text-[11px] text-primary/80">{contextNote}</div>
        )}

        {/* Message bubble */}
        <div
          className={cn(
            'rounded-lg p-3',
            isUser
              ? 'bg-primary text-primary-foreground'
              : isInterpreter
              ? 'bg-purple-500/10 border border-purple-400/35'
              : message.isGroupDiscussion
              ? 'bg-secondary/80 border border-primary/20'
              : 'bg-secondary border border-border/50'
          )}
        >
          <div
            className={cn(
              'prose prose-sm max-w-none',
              isUser
                ? 'prose-invert'
                : 'prose-invert prose-p:text-foreground prose-headings:text-foreground prose-strong:text-foreground prose-li:text-foreground prose-code:text-accent'
            )}
          >
            {hasEmptyAgentReply ? (
              <p className="m-0 whitespace-pre-wrap break-words text-sm text-amber-200">
                {message.error
                  ? t('chat.emptyReplyWithError', { error: message.error })
                  : t('chat.emptyReplyNoContent')}
              </p>
            ) : (
              <>
                <MessageBody
                  content={renderedContent}
                  isUser={isUser}
                  onPreviewImage={(src, alt) => setPreviewImage({ src, alt })}
                />
                {!isUser && isStreaming && (
                  <span className="ml-1 inline-block animate-pulse text-primary align-baseline">|</span>
                )}
              </>
            )}
          </div>

          {/* Attachments */}
          {message.attachments && message.attachments.length > 0 && (
            <div className="mt-3 pt-3 border-t border-border/30 space-y-1.5">
              {message.attachments.map((file) => (
                <button
                  type="button"
                  key={file.id}
                  className="flex w-full items-center gap-2 rounded border border-border/60 bg-background/35 px-2 py-1 text-left text-xs text-muted-foreground transition-colors hover:border-primary/40 hover:bg-background/60"
                  onClick={() => window.open(getDownloadUrl(file.id), '_blank', 'noopener,noreferrer')}
                >
                  {fileIcon(file.type)}
                  <span className="truncate">{file.name}</span>
                  <span className="ml-auto font-mono text-[11px] text-muted-foreground/70">{file.size}</span>
                </button>
              ))}
            </div>
          )}
          {!isUser && canOpenTrade && (
            <div className="mt-3 border-t border-border/30 pt-3">
              <button
                type="button"
                disabled={inPortfolio}
                onClick={() => onOpenTrade?.(message)}
                className={cn(
                  'rounded-md px-3 py-1.5 text-xs font-medium transition-colors',
                  inPortfolio
                    ? 'bg-emerald-500/20 text-emerald-300'
                    : 'bg-primary/20 text-primary hover:bg-primary/30'
                )}
              >
                {inPortfolio ? '✅ В портфеле' : '📝 Открыть сделку'}
              </button>
            </div>
          )}
        </div>
      </div>
      {previewImage && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 p-4">
          <button
            type="button"
            className="absolute right-4 top-4 rounded bg-black/50 p-2 text-white hover:bg-black/70"
            onClick={() => setPreviewImage(null)}
            aria-label={t('chat.closePreview')}
          >
            <X className="h-4 w-4" />
          </button>
          <div className="max-h-full max-w-[95vw] overflow-auto rounded-lg border border-border/60 bg-background p-3">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={previewImage.src}
              alt={previewImage.alt || 'image'}
              className="max-h-[80vh] max-w-[90vw] object-contain"
            />
            <div className="mt-3 flex justify-end">
              <a
                href={previewImage.src}
                download
                target="_blank"
                rel="noopener noreferrer"
                className="rounded border border-border/60 px-2 py-1 text-xs text-foreground hover:bg-secondary"
              >
                {t('chat.downloadImage')}
              </a>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export function AgentTypingRow({ agent }: { agent: Agent }) {
  const { t } = useLocale()
  return (
    <div className="flex gap-3 items-start py-1">
      <div className="relative shrink-0">
        <span className="absolute inset-0 rounded-full bg-primary/30 animate-pulse scale-110" aria-hidden />
        <AgentAvatar agent={agent} size="sm" />
      </div>
      <div className="min-w-0 pt-1">
        <p className="text-sm text-muted-foreground">
          {t('chat.typing', { name: agent.name })}
        </p>
      </div>
    </div>
  )
}

interface ThinkingIndicatorProps {
  agent: Agent
}

export function ThinkingIndicator({ agent }: ThinkingIndicatorProps) {
  const { t } = useLocale()
  return (
    <div className="flex gap-3">
      <div className="max-w-[75%]">
        <div className="flex items-center gap-2 mb-1.5">
          <AgentBadge agent={agent} size="sm" />
        </div>
        <div className="rounded-lg p-3 bg-secondary border border-border/50">
          <div className="flex items-center gap-2">
            <div className="flex gap-1">
              <span className="w-2 h-2 rounded-full bg-primary/60 animate-bounce" style={{ animationDelay: '0ms' }} />
              <span className="w-2 h-2 rounded-full bg-primary/60 animate-bounce" style={{ animationDelay: '150ms' }} />
              <span className="w-2 h-2 rounded-full bg-primary/60 animate-bounce" style={{ animationDelay: '300ms' }} />
            </div>
            <span className="text-sm text-muted-foreground">{t('chat.thinking')}</span>
          </div>
        </div>
      </div>
    </div>
  )
}
