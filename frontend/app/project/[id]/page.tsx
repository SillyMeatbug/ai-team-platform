'use client'

import { useState, useCallback, useRef, useEffect, use, useMemo } from 'react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { AgentAvatar } from '@/components/agent-badge'
import { AgentSelector } from '@/components/agent-selector'
import { ChatMessage, AgentTypingRow } from '@/components/chat-message'
import { ProjectTabs } from '@/components/project-tabs'
import { ProjectFilesList } from '@/components/project-files-list'
import { FileUploadZone } from '@/components/file-upload-zone'
import { ResultsView } from '@/components/results-view'
import {
  ChatMentionTextarea,
  type ChatMentionTextareaHandle,
} from '@/components/chat-mention-textarea'
import { LanguageToggle } from '@/components/language-toggle'
import { useLocale } from '@/components/locale-provider'
import { agentCardDescription } from '@/lib/i18n/agent-cards'
import {
  addProjectAgent,
  createProjectPaperTrade,
  deleteProjectFile,
  getAllAgents,
  getDownloadUrl,
  getProject,
  getProjectAgents,
  getProjectChat,
  getProjectFiles,
  getProjectPaperTrades,
  getProjectResults,
  getDebateLog,
  getDebateThread,
  getMarketContext,
  getMarketHealth,
  cancelDebateThread,
  removeProjectAgent,
  sendProjectChat,
  streamChatMessage,
  updateProject,
  uploadProjectFile,
  deleteProject,
} from '@/lib/api'
import { canOpenTradeFromMessage, parseTradeDraftFromContent, type ParsedTradeDraft } from '@/lib/paper-trade-parser'
import { extractMentionedAgentIds } from '@/lib/mentions'
import { mergeAgentsForUi } from '@/lib/ui-demo-agents'
import type {
  ProjectTab,
  ChatMessage as ChatMessageType,
  Agent,
  Project,
  AgentResult,
  DebateLog,
  DebateMode,
  DebateStatus,
  MarketContext,
  MarketHealth,
} from '@/lib/types'
import {
  ArrowLeft,
  Send,
  Paperclip,
  AtSign,
  MessageSquare,
  Settings,
  Share2,
  Trash2,
  Plus,
  Upload,
  X,
  Loader2,
  FileText,
  RefreshCw,
} from 'lucide-react'

/** Стабильная подпись области чата: без неё каждый poll создаёт новый массив messages и вызывает лишний smooth-scroll. */
function chatScrollFingerprint(
  messages: ChatMessageType[],
  typingRows: number,
  debateLog: DebateLog | null,
  debateDetailsOpen: boolean,
): string {
  const msgSig = messages.map((m) => `${m.id}:${(m.content ?? '').length}`).join('|')
  let debateSig = ''
  if (debateLog) {
    debateSig = `${debateLog.thread.status}:${debateLog.thread.currentRound}:${debateLog.rounds.length}:${debateLog.turns.length}`
  }
  return `${msgSig}#${typingRows}#${debateSig}#${debateDetailsOpen ? '1' : '0'}`
}

const CRYPTO_ROLES = new Set<Agent['role']>([
  'technical_analyst',
  'onchain_analyst',
  'sentiment_analyst',
  'risk_manager',
  'crypto_interpreter',
])

function isCryptoAgent(agent: Agent): boolean {
  return CRYPTO_ROLES.has(agent.role)
}

export default function ProjectWorkspacePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const router = useRouter()
  const searchParams = useSearchParams()
  const { locale, t } = useLocale()

  const [project, setProject] = useState<Project>({
    id,
    name: '',
    description: '',
    isCryptoEnabled: false,
    agents: [],
    files: [],
    messages: [],
    createdAt: '',
    updatedAt: '',
  })
  const [activeTab, setActiveTab] = useState<ProjectTab>('chat')
  const [message, setMessage] = useState('')
  const [messages, setMessages] = useState<ChatMessageType[]>([])
  const [results, setResults] = useState<AgentResult[]>([])
  const [allAgents, setAllAgents] = useState<Agent[]>([])
  const [isBootstrapping, setIsBootstrapping] = useState(true)
  const [isDiscussing, setIsDiscussing] = useState(false)
  const [debateMode, setDebateMode] = useState<DebateMode>('auto')
  const [routerInsight, setRouterInsight] = useState<{
    flow: 'off' | 'sequential' | 'debate'
    reason?: string
    agentNames: string
  } | null>(null)
  const [debateStatus, setDebateStatus] = useState<DebateStatus | null>(null)
  const [debateLog, setDebateLog] = useState<DebateLog | null>(null)
  const [showDebateLog, setShowDebateLog] = useState(false)
  const [discussionCtx, setDiscussionCtx] = useState<{
    userMessageId: string
    pendingAgentIds: string[]
    startedAt: number
    debateThreadId?: string
  } | null>(null)
  const [showAgentSelector, setShowAgentSelector] = useState(false)
  const [showUploadDialog, setShowUploadDialog] = useState(false)
  const [showSettingsDialog, setShowSettingsDialog] = useState(false)
  const [showDeleteProjectDialog, setShowDeleteProjectDialog] = useState(false)
  const [isDeletingProject, setIsDeletingProject] = useState(false)
  const [isSavingSettings, setIsSavingSettings] = useState(false)
  const [cryptoModeDraft, setCryptoModeDraft] = useState(false)
  const [chatPendingFiles, setChatPendingFiles] = useState<File[]>([])
  const [isUploadingChatFiles, setIsUploadingChatFiles] = useState(false)
  const [isRoutingQuestion, setIsRoutingQuestion] = useState(false)
  const [selectedAgentNames, setSelectedAgentNames] = useState<string[]>([])
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const chatScrollViewportRef = useRef<HTMLDivElement>(null)
  /** Пользователь у нижней границы — можно автопрокручивать при новых сообщениях */
  const stickToBottomRef = useRef(true)
  const lastChatFingerprintRef = useRef('')
  /** После отправки своего сообщения всегда прокручиваем вниз */
  const forceScrollBottomRef = useRef(false)
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const discussToastRef = useRef<string | number | null>(null)
  const chatMentionRef = useRef<ChatMentionTextareaHandle>(null)
  const chatFileInputRef = useRef<HTMLInputElement>(null)
  const streamMessageByAgentRef = useRef<Record<string, string>>({})
  const streamTokenBufferRef = useRef<Record<string, string>>({})
  const streamRafRef = useRef<number | null>(null)
  const thinkingTimersRef = useRef<Record<string, ReturnType<typeof setTimeout>>>({})
  const sendLockRef = useRef(false)
  const messageRefs = useRef<Record<string, HTMLDivElement | null>>({})
  const [streamingAgentIds, setStreamingAgentIds] = useState<string[]>([])
  const [thinkingAgentIds, setThinkingAgentIds] = useState<string[]>([])
  const [streamError, setStreamError] = useState<string | null>(null)
  const [retryDraft, setRetryDraft] = useState<string | null>(null)
  const [marketContext, setMarketContext] = useState<MarketContext | null>(null)
  const [marketHealth, setMarketHealth] = useState<MarketHealth | null>(null)
  const [isRefreshingMarket, setIsRefreshingMarket] = useState(false)
  const [focusedMessageId, setFocusedMessageId] = useState<string | null>(null)
  const [portfolioMessageIds, setPortfolioMessageIds] = useState<Record<string, boolean>>({})
  const [tradeModal, setTradeModal] = useState<{
    open: boolean
    message: ChatMessageType | null
    draft: ParsedTradeDraft | null
    comment: string
  }>({ open: false, message: null, draft: null, comment: '' })

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current !== null) {
      clearInterval(pollTimerRef.current)
      pollTimerRef.current = null
    }
  }, [])

  useEffect(() => {
    return () => stopPolling()
  }, [stopPolling])

  useEffect(() => {
    return () => {
      if (streamRafRef.current !== null) cancelAnimationFrame(streamRafRef.current)
      Object.values(thinkingTimersRef.current).forEach((t) => clearTimeout(t))
      thinkingTimersRef.current = {}
    }
  }, [])

  const refreshProjectData = useCallback(async () => {
    const [projectData, projectAgents, projectFiles, projectChat, projectResults, agentsPool, paperTrades] = await Promise.all([
      getProject(id),
      getProjectAgents(id),
      getProjectFiles(id),
      getProjectChat(id),
      getProjectResults(id),
      getAllAgents(),
      getProjectPaperTrades(id),
    ])
    setProject({
      ...projectData,
      agents: projectAgents,
      files: projectFiles,
      messages: projectChat,
    })
    setCryptoModeDraft(projectData.isCryptoEnabled)
    setMessages(projectChat)
    setResults(projectResults)
    setAllAgents(mergeAgentsForUi(agentsPool))
    const linked: Record<string, boolean> = {}
    for (const m of projectChat) {
      const hasTrade = paperTrades.some((t) => t.agentId === m.agentId && (m.discussionId ? new Date(t.openedAt) >= new Date(0) : true))
      if (hasTrade) linked[m.id] = true
    }
    setPortfolioMessageIds(linked)
  }, [id])

  useEffect(() => {
    let mounted = true
    const load = async () => {
      try {
        await refreshProjectData()
      } catch (e) {
        toast.error(`${t('project.toastLoadFailed')}: ${(e as Error).message}`)
      } finally {
        if (mounted) setIsBootstrapping(false)
      }
    }
    void load()
    return () => {
      mounted = false
    }
  }, [refreshProjectData, t])

  useEffect(() => {
    const focusId = searchParams.get('focus_message_id')
    if (!focusId) return
    const el = messageRefs.current[focusId]
    if (!el) return
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    setFocusedMessageId(focusId)
    const timer = window.setTimeout(() => {
      setFocusedMessageId((prev) => (prev === focusId ? null : prev))
    }, 2000)
    return () => window.clearTimeout(timer)
  }, [messages, searchParams])

  useEffect(() => {
    const tab = searchParams.get('tab')
    if (!tab || tab === 'chat') {
      setActiveTab('chat')
      return
    }
    if (tab === 'agents' || tab === 'files' || tab === 'results') {
      setActiveTab(tab)
    }
  }, [searchParams])

  const refreshMarketBadge = useCallback(
    async (force: boolean = false) => {
      setIsRefreshingMarket(true)
      try {
        const [ctx, health] = await Promise.all([
          getMarketContext('BTC/USDT', '4H', force),
          getMarketHealth(),
        ])
        setMarketContext(ctx)
        setMarketHealth(health)
      } catch (e) {
        toast.error(`Market data error: ${(e as Error).message}`)
      } finally {
        setIsRefreshingMarket(false)
      }
    },
    []
  )

  useEffect(() => {
    void refreshMarketBadge(false)
    const id = setInterval(() => {
      void refreshMarketBadge(false)
    }, 60_000)
    return () => clearInterval(id)
  }, [refreshMarketBadge])

  const marketBadge = useMemo(() => {
    if (!marketContext) return { icon: '🔴', text: 'Unavailable' }
    if (marketContext.status === 'live') {
      const ttl = marketContext.cache_info?.ttl_remaining_sec ?? 0
      return ttl > 13 * 60
        ? { icon: '🟢', text: 'Live' }
        : { icon: '🟡', text: 'Cached' }
    }
    if (marketContext.status === 'cached') return { icon: '🟡', text: 'Cached' }
    return { icon: '🔴', text: 'Unavailable' }
  }, [marketContext])

  const visibleProjectAgents = useMemo(
    () => project.agents.filter((a) => project.isCryptoEnabled || !isCryptoAgent(a)),
    [project.agents, project.isCryptoEnabled]
  )
  const visibleAllAgents = useMemo(
    () => allAgents.filter((a) => project.isCryptoEnabled || !isCryptoAgent(a)),
    [allAgents, project.isCryptoEnabled]
  )

  const typingAgents = useMemo(() => {
    if (!discussionCtx || !isDiscussing) return []
    const repliedIds = new Set(
      messages
        .filter((m) => m.senderType === 'agent' && m.discussionId === discussionCtx.userMessageId)
        .map((m) => m.agentId)
    )
    return discussionCtx.pendingAgentIds
      .filter((pid) => !repliedIds.has(pid))
      .map((pid) => visibleProjectAgents.find((a) => a.id === pid))
      .filter(Boolean) as Agent[]
  }, [discussionCtx, isDiscussing, messages, visibleProjectAgents])

  const handleChatScroll = useCallback(() => {
    const root = chatScrollViewportRef.current
    if (!root) return
    const thresholdPx = 120
    const distanceFromBottom = root.scrollHeight - root.scrollTop - root.clientHeight
    stickToBottomRef.current = distanceFromBottom <= thresholdPx
  }, [])

  useEffect(() => {
    const fp = chatScrollFingerprint(
      messages,
      typingAgents.length,
      debateLog,
      showDebateLog,
    )
    const forced = forceScrollBottomRef.current
    if (!forced && fp === lastChatFingerprintRef.current) return
    forceScrollBottomRef.current = false
    lastChatFingerprintRef.current = fp

    if (!stickToBottomRef.current && !forced) return

    const instant = isDiscussing || isUploadingChatFiles
    requestAnimationFrame(() => {
      messagesEndRef.current?.scrollIntoView({
        behavior: instant ? 'auto' : 'smooth',
        block: 'end',
      })
    })
  }, [
    messages,
    typingAgents.length,
    debateLog,
    showDebateLog,
    isDiscussing,
    isUploadingChatFiles,
  ])

  const contextNoteByMessageId = useMemo(() => {
    const byId = new Map<string, string>()
    const lastAgentByParent = new Map<string, string>()
    for (const msg of messages) {
      if (msg.senderType !== 'agent' || !msg.discussionId || msg.agentId === 'user') continue
      const prevAgent = lastAgentByParent.get(msg.discussionId)
      if (prevAgent && prevAgent !== msg.agentId) {
        const prevName = visibleProjectAgents.find((a) => a.id === prevAgent)?.name
        if (prevName) {
          byId.set(msg.id, `${t('project.chatSequentialSupplements')} ${prevName}`)
        }
      }
      lastAgentByParent.set(msg.discussionId, msg.agentId)
    }
    return byId
  }, [messages, visibleProjectAgents, t])

  const debateStatusText = useMemo(() => {
    if (!debateStatus) return null
    if (debateStatus === 'agents_discussing' || debateStatus === 'running') {
      const cur = debateLog?.thread.currentRound ?? 1
      const total =
        debateLog?.thread.totalRounds ??
        (debateMode === 'auto'
          ? 5
          : debateMode === 'deep'
            ? 5
            : debateMode === 'standard'
              ? 4
              : debateMode === 'fast'
                ? 3
                : 1)
      return t('project.debateStatusRound', { cur, total })
    }
    if (debateStatus === 'synthesizing') return t('project.debateStatusSynthesizing')
    if (debateStatus === 'cancelled') return t('project.debateStatusCancelled')
    if (debateStatus === 'timed_out') return t('project.debateStatusTimedOut')
    if (debateStatus === 'failed') return t('project.debateStatusFailed')
    if (debateStatus === 'completed') return t('project.debateStatusCompleted')
    return null
  }, [debateLog, debateMode, debateStatus, t])

  const canCancelDebate =
    !!discussionCtx?.debateThreadId &&
    (debateStatus === 'running' ||
      debateStatus === 'agents_discussing' ||
      debateStatus === 'synthesizing')
  const isChatBusy = isDiscussing || isUploadingChatFiles

  const formatPendingFileSize = useCallback((bytes: number) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }, [])

  const fileKey = useCallback((file: File) => `${file.name}:${file.size}:${file.lastModified}`, [])

  const handlePickChatFiles = useCallback((picked: FileList | null) => {
    if (!picked || picked.length === 0) return
    const incoming = Array.from(picked)
    setChatPendingFiles((prev) => {
      const map = new Map(prev.map((f) => [fileKey(f), f]))
      for (const f of incoming) map.set(fileKey(f), f)
      return Array.from(map.values())
    })
  }, [fileKey])

  const handleRemoveChatPendingFile = useCallback((target: File) => {
    const key = fileKey(target)
    setChatPendingFiles((prev) => prev.filter((f) => fileKey(f) !== key))
  }, [fileKey])

  const flushStreamBuffer = useCallback(() => {
    const batches = streamTokenBufferRef.current
    streamTokenBufferRef.current = {}
    streamRafRef.current = null
    const entries = Object.entries(batches)
    if (entries.length === 0) return
    setMessages((prev) => {
      let next = [...prev]
      for (const [agentId, chunk] of entries) {
        const msgId = streamMessageByAgentRef.current[agentId]
        if (!msgId) continue
        const idx = next.findIndex((m) => m.id === msgId)
        if (idx < 0) continue
        next[idx] = { ...next[idx], content: `${next[idx].content || ''}${chunk}` }
      }
      return next
    })
  }, [])

  const handleSendMessage = useCallback(async () => {
    if (!message.trim()) return
    if (sendLockRef.current) return
    sendLockRef.current = true

    const outgoing = message.trim()
    const mentioned_agent_ids = extractMentionedAgentIds(outgoing, visibleProjectAgents)
    const willSmartRoute =
      (debateMode === 'off' || debateMode === 'auto') && mentioned_agent_ids.length === 0
    setIsRoutingQuestion(willSmartRoute)
    setSelectedAgentNames([])
    setRouterInsight(null)
    setStreamError(null)
    setRetryDraft(null)

    let uploadedFileIds: string[] = []
    if (chatPendingFiles.length > 0) {
      setIsUploadingChatFiles(true)
      try {
        const uploaded = await Promise.all(
          chatPendingFiles.map((file) => uploadProjectFile(id, file, 'reference'))
        )
        uploadedFileIds = uploaded.map((f) => f.id)
        if (uploaded.length > 0) {
          setProject((prev) => ({ ...prev, files: [...uploaded, ...prev.files] }))
        }
        setChatPendingFiles([])
        if (chatFileInputRef.current) {
          chatFileInputRef.current.value = ''
        }
      } catch (e) {
        toast.error(`${t('project.toastUploadFail')}: ${(e as Error).message}`)
        return
      } finally {
        setIsUploadingChatFiles(false)
      }
    }

    const optimisticId = `local-${Date.now()}`
    const optimisticUserMessage: ChatMessageType = {
      id: optimisticId,
      agentId: 'user',
      senderType: 'user',
      content: outgoing,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    }

    stickToBottomRef.current = true
    forceScrollBottomRef.current = true
    setMessages((prev) => [...prev, optimisticUserMessage])
    setMessage('')
    setIsDiscussing(true)
    stopPolling()

    const loadingToast = toast.loading(
      debateMode === 'auto' ? t('project.routerAnalyzing') : t('project.toastDiscussing')
    )
    discussToastRef.current = loadingToast

    try {
      if (typeof ReadableStream !== 'undefined') {
        let streamAccepted = false
        let acceptedDebateThreadId: string | undefined
        let streamUserMessageId: string | null = null
        let streamComplete = false

        const streamResult = await streamChatMessage(
          id,
          {
            content: outgoing,
            mentioned_agent_ids,
            debate_mode: debateMode,
            locale,
            file_ids: uploadedFileIds,
          },
          (evt) => {
            if (evt.type === 'accepted') {
              streamAccepted = true
              streamUserMessageId = evt.user_message.id
              acceptedDebateThreadId = evt.debate_thread_id
              setMessages((prev) => prev.map((m) => (m.id === optimisticId ? evt.user_message : m)))
              setDiscussionCtx({
                userMessageId: evt.user_message.id,
                pendingAgentIds: evt.pending_agent_ids,
                startedAt: Date.now(),
                debateThreadId: evt.debate_thread_id,
              })
              setDebateStatus(evt.debate_thread_id ? 'running' : null)
              setDebateLog(null)
              setShowDebateLog(false)
              setStreamingAgentIds([])
              setThinkingAgentIds([])
              streamMessageByAgentRef.current = {}
              for (const aid of evt.pending_agent_ids) {
                const timer = setTimeout(() => {
                  setThinkingAgentIds((prev) => (prev.includes(aid) ? prev : [...prev, aid]))
                }, 5000)
                thinkingTimersRef.current[aid] = timer
              }
              return
            }
            if (evt.type === 'streaming_disabled') {
              setDebateStatus('agents_discussing')
              return
            }
            if (evt.type === 'round_start') {
              setDebateStatus('agents_discussing')
              return
            }
            if (evt.type === 'token') {
              const aid = evt.agent_id
              const timer = thinkingTimersRef.current[aid]
              if (timer) {
                clearTimeout(timer)
                delete thinkingTimersRef.current[aid]
              }
              setThinkingAgentIds((prev) => prev.filter((x) => x !== aid))
              setStreamingAgentIds((prev) => (prev.includes(aid) ? prev : [...prev, aid]))
              if (!streamMessageByAgentRef.current[aid] && streamUserMessageId) {
                const msgId = `stream-${streamUserMessageId}-${aid}`
                streamMessageByAgentRef.current[aid] = msgId
                const ts = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                setMessages((prev) => [
                  ...prev,
                  {
                    id: msgId,
                    agentId: aid,
                    senderType: 'agent',
                    content: '',
                    timestamp: ts,
                    isGroupDiscussion: true,
                    discussionId: streamUserMessageId ?? undefined,
                  },
                ])
              }
              streamTokenBufferRef.current[aid] = `${streamTokenBufferRef.current[aid] ?? ''}${evt.content}`
              if (streamRafRef.current === null) {
                streamRafRef.current = requestAnimationFrame(flushStreamBuffer)
              }
              return
            }
            if (evt.type === 'agent_done') {
              const aid = evt.agent_id
              const timer = thinkingTimersRef.current[aid]
              if (timer) {
                clearTimeout(timer)
                delete thinkingTimersRef.current[aid]
              }
              setThinkingAgentIds((prev) => prev.filter((x) => x !== aid))
              setStreamingAgentIds((prev) => prev.filter((x) => x !== aid))
              if (evt.error) {
                const msgId = streamMessageByAgentRef.current[aid]
                if (msgId) {
                  setMessages((prev) =>
                    prev.map((m) => (m.id === msgId ? { ...m, error: evt.error ?? null } : m))
                  )
                }
              }
              return
            }
            if (evt.type === 'error') {
              setStreamError(evt.detail)
              return
            }
            if (evt.type === 'complete') {
              streamComplete = true
            }
          }
        )

        if (!streamResult.streamingEnabled) {
          const accepted =
            streamResult.accepted ??
            (await sendProjectChat(id, {
              content: outgoing,
              mentioned_agent_ids,
              debate_mode: debateMode,
              locale,
              file_ids: uploadedFileIds,
            }))
          setMessages((prev) => prev.map((m) => (m.id === optimisticId ? accepted.user_message : m)))
          if (accepted.selected_agents?.length) {
            const names = accepted.selected_agents
              .map((aid) => visibleProjectAgents.find((a) => a.id === aid)?.name)
              .filter(Boolean) as string[]
            setSelectedAgentNames(names)
          }
          if (accepted.router_flow && accepted.selected_agents?.length) {
            const agentNames = accepted.selected_agents
              .map((aid) => visibleProjectAgents.find((a) => a.id === aid)?.name)
              .filter(Boolean) as string[]
            setRouterInsight({
              flow: accepted.router_flow,
              reason: accepted.router_reason,
              agentNames: agentNames.join(', '),
            })
          } else {
            setRouterInsight(null)
          }
          setIsRoutingQuestion(false)

          const userMessageId = accepted.user_message.id
          const pendingIds = [...accepted.pending_agent_ids]
          const startedAt = Date.now()
          setDiscussionCtx({
            userMessageId,
            pendingAgentIds: pendingIds,
            startedAt,
            debateThreadId: accepted.debate_thread_id,
          })
          setDebateStatus(accepted.debate_thread_id ? 'running' : null)
          setDebateLog(null)
          setShowDebateLog(false)

          async function pollOnce(): Promise<boolean> {
            try {
              const chat = await getProjectChat(id)
              setMessages(chat)
              setProject((p) => ({ ...p, messages: chat }))

              if (accepted.debate_thread_id) {
                const thread = await getDebateThread(id, accepted.debate_thread_id)
                setDebateStatus(thread.status)
                const done =
                  thread.status === 'completed' ||
                  thread.status === 'cancelled' ||
                  thread.status === 'timed_out' ||
                  thread.status === 'failed'
                if (done) {
                  const log = await getDebateLog(id, accepted.debate_thread_id)
                  setDebateLog(log)
                  stopPolling()
                  setIsDiscussing(false)
                  setDiscussionCtx(null)
                  toast.dismiss(loadingToast)
                  discussToastRef.current = null
                  setIsRoutingQuestion(false)
                  return true
                }
                return false
              }

              const repliedIds = new Set(
                chat
                  .filter((m) => m.senderType === 'agent' && m.discussionId === userMessageId)
                  .map((m) => m.agentId)
              )
              const allDone = pendingIds.every((pid) => repliedIds.has(pid))
              const timedOut = Date.now() - startedAt > 30_000
              if (allDone || timedOut) {
                stopPolling()
                setIsDiscussing(false)
                setDiscussionCtx(null)
                toast.dismiss(loadingToast)
                discussToastRef.current = null
                setIsRoutingQuestion(false)
                return true
              }
              return false
            } catch (e) {
              stopPolling()
              setIsDiscussing(false)
              setDiscussionCtx(null)
              toast.dismiss(loadingToast)
              discussToastRef.current = null
              toast.error(`${t('project.toastChatSyncFailed')}: ${(e as Error).message}`)
              setIsRoutingQuestion(false)
              return true
            }
          }

          const finishedImmediately = await pollOnce()
          if (!finishedImmediately) {
            pollTimerRef.current = setInterval(() => {
              void pollOnce().then((done) => {
                if (done) stopPolling()
              })
            }, 2000)
          }
          return
        }

        if (streamRafRef.current !== null) {
          cancelAnimationFrame(streamRafRef.current)
          streamRafRef.current = null
        }
        flushStreamBuffer()
        Object.values(thinkingTimersRef.current).forEach((t) => clearTimeout(t))
        thinkingTimersRef.current = {}
        setThinkingAgentIds([])
        setStreamingAgentIds([])
        if (streamAccepted && streamComplete) {
          const [chat, projectResults] = await Promise.all([getProjectChat(id), getProjectResults(id)])
          setMessages(chat)
          setProject((p) => ({ ...p, messages: chat }))
          setResults(projectResults)
          if (acceptedDebateThreadId) {
            const [thread, log] = await Promise.all([
              getDebateThread(id, acceptedDebateThreadId),
              getDebateLog(id, acceptedDebateThreadId),
            ])
            setDebateStatus(thread.status)
            setDebateLog(log)
          }
          setIsDiscussing(false)
          setDiscussionCtx(null)
          toast.dismiss(loadingToast)
          discussToastRef.current = null
          setIsRoutingQuestion(false)
          return
        }

        // stream path не завершился корректно — откат к polling ниже
        setStreamError(t('project.toastChatSyncFailed'))
      }

      const accepted = await sendProjectChat(id, {
        content: outgoing,
        mentioned_agent_ids,
        debate_mode: debateMode,
        locale,
        file_ids: uploadedFileIds,
      })

      setMessages((prev) => prev.map((m) => (m.id === optimisticId ? accepted.user_message : m)))
      if (accepted.selected_agents?.length) {
        const names = accepted.selected_agents
          .map((id) => visibleProjectAgents.find((a) => a.id === id)?.name)
          .filter(Boolean) as string[]
        setSelectedAgentNames(names)
      }
      if (accepted.router_flow && accepted.selected_agents?.length) {
        const agentNames = accepted.selected_agents
          .map((id) => visibleProjectAgents.find((a) => a.id === id)?.name)
          .filter(Boolean) as string[]
        setRouterInsight({
          flow: accepted.router_flow,
          reason: accepted.router_reason,
          agentNames: agentNames.join(', '),
        })
      } else {
        setRouterInsight(null)
      }
      setIsRoutingQuestion(false)

      const userMessageId = accepted.user_message.id
      const pendingIds = [...accepted.pending_agent_ids]
      const startedAt = Date.now()
      setDiscussionCtx({
        userMessageId,
        pendingAgentIds: pendingIds,
        startedAt,
        debateThreadId: accepted.debate_thread_id,
      })
      setDebateStatus(accepted.debate_thread_id ? 'running' : null)
      setDebateLog(null)
      setShowDebateLog(false)

      async function pollOnce(): Promise<boolean> {
        try {
          const chat = await getProjectChat(id)
          setMessages(chat)
          setProject((p) => ({ ...p, messages: chat }))

          if (accepted.debate_thread_id) {
            const thread = await getDebateThread(id, accepted.debate_thread_id)
            setDebateStatus(thread.status)
            const done =
              thread.status === 'completed' ||
              thread.status === 'cancelled' ||
              thread.status === 'timed_out' ||
              thread.status === 'failed'
            if (done) {
              const log = await getDebateLog(id, accepted.debate_thread_id)
              setDebateLog(log)
              stopPolling()
              setIsDiscussing(false)
              setDiscussionCtx(null)
              toast.dismiss(loadingToast)
              discussToastRef.current = null
              if (thread.status === 'timed_out') {
                toast.error(t('project.toastDiscussTimeout'))
              } else if (thread.status === 'cancelled') {
                toast.success(t('project.toastDebateCancelled'))
              }
              setIsRoutingQuestion(false)
              return true
            }
            return false
          }

          const repliedIds = new Set(
            chat
              .filter((m) => m.senderType === 'agent' && m.discussionId === userMessageId)
              .map((m) => m.agentId)
          )
          const allDone = pendingIds.every((pid) => repliedIds.has(pid))
          const timedOut = Date.now() - startedAt > 30_000

          if (allDone || timedOut) {
            stopPolling()
            setIsDiscussing(false)
            setDiscussionCtx(null)
            toast.dismiss(loadingToast)
            discussToastRef.current = null
            if (timedOut && !allDone) {
              toast.error(t('project.toastDiscussTimeout'))
            }
            setIsRoutingQuestion(false)
            return true
          }
          return false
        } catch (e) {
          stopPolling()
          setIsDiscussing(false)
          setDiscussionCtx(null)
          toast.dismiss(loadingToast)
          discussToastRef.current = null
          toast.error(`${t('project.toastChatSyncFailed')}: ${(e as Error).message}`)
          setIsRoutingQuestion(false)
          return true
        }
      }

      const finishedImmediately = await pollOnce()
      if (!finishedImmediately) {
        pollTimerRef.current = setInterval(() => {
          void pollOnce().then((done) => {
            if (done) stopPolling()
          })
        }, 2000)
      }
    } catch (e) {
      toast.dismiss(loadingToast)
      discussToastRef.current = null
      toast.error(`${t('project.toastSendFailed')}: ${(e as Error).message}`)
      setStreamError((e as Error).message)
      setRetryDraft(outgoing)
      setMessages((prev) => prev.filter((m) => m.id !== optimisticId))
      setIsDiscussing(false)
      setDiscussionCtx(null)
      setIsRoutingQuestion(false)
    } finally {
      sendLockRef.current = false
    }
  }, [chatPendingFiles, debateMode, id, locale, message, visibleProjectAgents, stopPolling, t])

  const handleAddAgent = useCallback(
    async (agentId: string) => {
      try {
        await addProjectAgent(id, agentId)
        await refreshProjectData()
      } catch (e) {
        toast.error(`${t('project.toastAddAgentFailed')}: ${(e as Error).message}`)
      }
    },
    [id, refreshProjectData, t]
  )

  const handleRemoveAgent = useCallback(
    async (agentId: string) => {
      try {
        await removeProjectAgent(id, agentId)
        await refreshProjectData()
      } catch (e) {
        toast.error(`${t('project.toastRemoveAgentFailed')}: ${(e as Error).message}`)
      }
    },
    [id, refreshProjectData, t]
  )

  const handleUploadFiles = useCallback(
    async (files: File[]) => {
      try {
        for (const file of files) {
          await uploadProjectFile(id, file, 'reference')
        }
        await refreshProjectData()
        setShowUploadDialog(false)
        toast.success(t('project.toastUploadOk'))
      } catch (e) {
        toast.error(`${t('project.toastUploadFail')}: ${(e as Error).message}`)
      }
    },
    [id, refreshProjectData, t]
  )

  const handleDeleteFile = useCallback(
    async (fileId: string) => {
      try {
        await deleteProjectFile(id, fileId)
        await refreshProjectData()
      } catch (e) {
        toast.error(`${t('project.toastDeleteFail')}: ${(e as Error).message}`)
      }
    },
    [id, refreshProjectData, t]
  )

  const handleConfirmDeleteProject = useCallback(async () => {
    setIsDeletingProject(true)
    try {
      stopPolling()
      await deleteProject(id)
      setShowDeleteProjectDialog(false)
      toast.success(t('project.toastProjectDeleted'))
      router.push('/')
    } catch (e) {
      toast.error(`${t('project.toastProjectDeleteFailed')}: ${(e as Error).message}`)
    } finally {
      setIsDeletingProject(false)
    }
  }, [id, router, stopPolling, t])

  const handleSaveProjectSettings = useCallback(async () => {
    setIsSavingSettings(true)
    try {
      const wasEnabled = project.isCryptoEnabled
      await updateProject(id, { is_crypto_enabled: cryptoModeDraft })
      await refreshProjectData()
      setShowSettingsDialog(false)
      if (wasEnabled && !cryptoModeDraft) {
        toast.message(
          'Крипто-агенты будут скрыты, но останутся в проекте. Включите режим снова, чтобы их увидеть.'
        )
      } else {
        toast.success('Настройки проекта обновлены')
      }
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setIsSavingSettings(false)
    }
  }, [cryptoModeDraft, id, project.isCryptoEnabled, refreshProjectData])

  const handleCancelDebate = useCallback(async () => {
    const threadId = discussionCtx?.debateThreadId
    if (!threadId) return
    try {
      await cancelDebateThread(id, threadId)
      const [chat, thread, log] = await Promise.all([
        getProjectChat(id),
        getDebateThread(id, threadId),
        getDebateLog(id, threadId),
      ])
      setMessages(chat)
      setProject((p) => ({ ...p, messages: chat }))
      setDebateStatus(thread.status)
      setDebateLog(log)
      setIsDiscussing(false)
      setDiscussionCtx(null)
      stopPolling()
      if (discussToastRef.current !== null) {
        toast.dismiss(discussToastRef.current)
        discussToastRef.current = null
      }
      toast.success(t('project.toastDebateCancelled'))
    } catch (e) {
      toast.error(`${t('project.toastDebateCancelFailed')}: ${(e as Error).message}`)
    }
  }, [discussionCtx?.debateThreadId, id, stopPolling, t])

  const getAgent = useCallback(
    (agentId: string) => visibleProjectAgents.find((a) => a.id === agentId),
    [visibleProjectAgents]
  )

  const availableToAdd = visibleAllAgents.filter((a) => !project.agents.some((pa) => pa.id === a.id))
  const availableProductToAdd = availableToAdd.filter((a) => !isCryptoAgent(a))
  const availableCryptoToAdd = availableToAdd.filter((a) => isCryptoAgent(a))

  const handleOpenTradeFromMessage = useCallback((msg: ChatMessageType) => {
    const draft = parseTradeDraftFromContent(msg.content)
    if (!draft) {
      toast.error('Не удалось распарсить сигнал сделки')
      return
    }
    setTradeModal({ open: true, message: msg, draft, comment: '' })
  }, [])

  const handleConfirmTrade = useCallback(async () => {
    if (!tradeModal.message || !tradeModal.draft) return
    const d = tradeModal.draft
    const payload = {
      agent_id: tradeModal.message.agentId,
      message_id: tradeModal.message.id,
      asset: d.asset,
      timeframe: d.timeframe,
      signal: d.signal,
      entry_price: d.entryPrice,
      stop_loss: d.stopLoss,
      take_profit: d.takeProfit,
      confidence: d.confidence,
      signal_timestamp: d.signalTimestamp ?? new Date().toISOString(),
      rationale: `${tradeModal.message.content}\n\nКомментарий: ${tradeModal.comment || '-'}`,
    }
    try {
      await createProjectPaperTrade(id, payload)
      setPortfolioMessageIds((prev) => ({ ...prev, [tradeModal.message!.id]: true }))
      setTradeModal({ open: false, message: null, draft: null, comment: '' })
      toast.success('Сделка открыта')
    } catch (e) {
      toast.error((e as Error).message)
    }
  }, [id, tradeModal])

  return (
    <div className="h-screen flex flex-col bg-background">
      <header className="border-b border-border flex-shrink-0">
        <div className="mx-auto max-w-6xl w-full px-4 py-3 sm:px-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <Button variant="ghost" size="icon" className="text-muted-foreground hover:text-foreground" asChild>
                <Link href="/">
                  <ArrowLeft className="w-5 h-5" />
                  <span className="sr-only">{t('project.backSr')}</span>
                </Link>
              </Button>
              <div>
                {isBootstrapping ? (
                  <Skeleton className="h-6 w-48 mb-2" />
                ) : (
                  <h1 className="font-semibold text-lg text-foreground">{project.name}</h1>
                )}
                <div className="flex items-center gap-2 mt-1">
                  {isBootstrapping ? (
                    <div className="flex gap-1">
                      <Skeleton className="h-6 w-6 rounded-full" />
                      <Skeleton className="h-6 w-6 rounded-full" />
                    </div>
                  ) : (
                    <>
                      <div className="flex -space-x-1.5">
                        {visibleProjectAgents.slice(0, 4).map((agent) => (
                          <AgentAvatar key={agent.id} agent={agent} size="sm" />
                        ))}
                      </div>
                      {visibleProjectAgents.length > 4 && (
                        <span className="text-xs text-muted-foreground">
                          {t('project.moreAvatars', { n: visibleProjectAgents.length - 4 })}
                        </span>
                      )}
                    </>
                  )}
                </div>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <div className="hidden md:flex items-center gap-2 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground">
                <span>{marketBadge.icon}</span>
                <span>{marketBadge.text}</span>
                {marketHealth && (
                  <span className={marketHealth.status === 'healthy' ? 'text-green-400' : 'text-amber-400'}>
                    {marketHealth.status}
                  </span>
                )}
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  className="h-6 w-6"
                  onClick={() => void refreshMarketBadge(true)}
                  disabled={isRefreshingMarket}
                  aria-label="Обновить данные"
                >
                  <RefreshCw className={`h-3.5 w-3.5 ${isRefreshingMarket ? 'animate-spin' : ''}`} />
                </Button>
              </div>
              <LanguageToggle />
              <Button variant="outline" size="sm" className="hidden sm:flex border-border text-foreground">
                <Share2 className="w-4 h-4 mr-2" />
                {t('common.share')}
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="hidden sm:flex border-border text-foreground"
                onClick={() => {
                  setCryptoModeDraft(project.isCryptoEnabled)
                  setShowSettingsDialog(true)
                }}
              >
                <Settings className="w-4 h-4 mr-2" />
                {t('common.settings')}
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                className="text-muted-foreground hover:text-destructive"
                onClick={() => setShowDeleteProjectDialog(true)}
                aria-haspopup="dialog"
              >
                <Trash2 className="w-5 h-5" />
                <span className="sr-only">{t('common.archive')}</span>
              </Button>
            </div>
          </div>
        </div>
        <ProjectTabs
          activeTab={activeTab}
          onChange={setActiveTab}
          projectId={id}
          isCryptoEnabled={project.isCryptoEnabled}
        />
      </header>

      <main className="flex-1 min-h-0 overflow-hidden flex flex-col">
        {activeTab === 'chat' && (
          <div className="flex-1 min-h-0 flex flex-col">
            <div
              ref={chatScrollViewportRef}
              className="flex-1 min-h-0 overflow-y-auto"
              onScroll={handleChatScroll}
            >
              <div className="mx-auto max-w-6xl w-full px-4 py-4 sm:px-6 space-y-4">
              {isBootstrapping ? (
                <div className="space-y-4">
                  <Skeleton className="h-16 w-full max-w-xl rounded-lg ml-auto" />
                  <Skeleton className="h-24 w-full max-w-xl rounded-lg" />
                  <Skeleton className="h-20 w-full max-w-xl rounded-lg" />
                </div>
              ) : messages.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full text-center">
                  <div className="p-4 rounded-full bg-secondary/50 mb-4">
                    <MessageSquare className="w-8 h-8 text-muted-foreground" />
                  </div>
                  <h3 className="text-lg font-medium text-foreground mb-2">{t('project.chatEmptyTitle')}</h3>
                  <p className="text-sm text-muted-foreground max-w-sm">{t('project.chatEmptySubtitle')}</p>
                </div>
              ) : (
                <>
                  {messages.map((msg) => (
                    <div
                      key={msg.id}
                      ref={(el) => {
                        messageRefs.current[msg.id] = el
                      }}
                      className={focusedMessageId === msg.id ? 'rounded-xl ring-2 ring-purple-400/70 animate-pulse' : ''}
                    >
                      <ChatMessage
                        message={msg}
                        agent={msg.agentId !== 'user' ? getAgent(msg.agentId) : undefined}
                        contextNote={contextNoteByMessageId.get(msg.id)}
                        isStreaming={msg.senderType === 'agent' && streamingAgentIds.includes(msg.agentId)}
                        canOpenTrade={canOpenTradeFromMessage(msg, msg.agentId !== 'user' ? getAgent(msg.agentId) : undefined)}
                        inPortfolio={Boolean(portfolioMessageIds[msg.id])}
                        onOpenTrade={handleOpenTradeFromMessage}
                      />
                    </div>
                  ))}
                  {isDiscussing &&
                    typingAgents.map((agent) => (
                      <div key={agent.id}>
                        <AgentTypingRow agent={agent} />
                        {thinkingAgentIds.includes(agent.id) && (
                          <div className="ml-11 text-xs text-muted-foreground">{t('chat.thinking')}</div>
                        )}
                      </div>
                    ))}
                  {debateLog && (
                    <div className="rounded-lg border border-border bg-card p-3">
                      <div className="flex items-center justify-between gap-2">
                        <div className="text-sm font-medium text-foreground">{t('project.debateHelpTitle')}</div>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="text-xs"
                          onClick={() => setShowDebateLog((v) => !v)}
                        >
                          {showDebateLog ? t('project.debateHideDetails') : t('project.debateShowDetails')}
                        </Button>
                      </div>
                      <p className="mt-2 text-xs text-muted-foreground">
                        {t('project.debateMeta', {
                          mode: debateLog.thread.mode,
                          rounds: debateLog.thread.totalRounds,
                          status: debateLog.thread.status,
                        })}
                      </p>
                      {showDebateLog && (
                        <div className="mt-3 space-y-3">
                          {debateLog.rounds.map((round) => {
                            const roundTurns = debateLog.turns.filter((t) => t.roundId === round.id)
                            return (
                              <div key={round.id} className="rounded-md border border-border/60 p-2">
                                <div className="text-xs font-medium text-foreground">
                                  {t('project.debateRoundLabel', {
                                    round: round.roundNumber,
                                    status: round.status,
                                  })}
                                </div>
                                <div className="mt-2 space-y-2">
                                  {roundTurns.map((turn) => (
                                    <div key={turn.id} className="text-xs text-muted-foreground">
                                      <span className="text-foreground">{turn.agentSnapshot?.name ?? turn.agentId}:</span>{' '}
                                      {turn.error ? `Ошибка: ${turn.error}` : turn.content}
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )
                          })}
                        </div>
                      )}
                    </div>
                  )}
                </>
              )}
              <div ref={messagesEndRef} />
              </div>
            </div>

            <div className="border-t border-border flex-shrink-0">
              <div className="mx-auto max-w-6xl w-full px-4 py-4 sm:px-6">
              <div className="mb-2 flex items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground">{t('project.debateModeLabel')}</span>
                  <select
                    value={debateMode}
                    onChange={(e) => setDebateMode(e.target.value as DebateMode)}
                    disabled={isDiscussing}
                    className="h-8 rounded-md border border-border bg-secondary px-2 text-xs text-foreground"
                  >
                    <option value="off">{t('project.debateModeOff')}</option>
                    <option value="auto">{`🤖 ${t('project.debateModeAuto')}`}</option>
                    <option value="fast">{t('project.debateModeFast')}</option>
                    <option value="standard">{t('project.debateModeStandard')}</option>
                    <option value="deep">{t('project.debateModeDeep')}</option>
                  </select>
                </div>
                <div className="flex items-center gap-2">
                  {debateStatusText && (
                    <span className="text-xs text-primary">{debateStatusText}</span>
                  )}
                  {canCancelDebate && (
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      className="h-8 border-destructive/40 text-destructive hover:bg-destructive/10"
                      onClick={() => void handleCancelDebate()}
                    >
                      {t('project.debateCancelButton')}
                    </Button>
                  )}
                </div>
              </div>
              {(isRoutingQuestion || selectedAgentNames.length > 0) && (
                <div className="mb-2 text-xs text-muted-foreground">
                  {isRoutingQuestion
                    ? debateMode === 'auto'
                      ? t('project.routerAnalyzing')
                      : t('project.chatRoutingAnalyzing')
                    : t('project.chatSelectedAgents', { names: selectedAgentNames.join(', ') })}
                </div>
              )}
              {routerInsight && !isRoutingQuestion && (
                <div className="mb-2 space-y-1">
                  <div
                    className="text-xs text-foreground"
                    title={
                      routerInsight.reason
                        ? `${t('project.routerReasonTitle')}: ${routerInsight.reason}`
                        : undefined
                    }
                  >
                    {t('project.routerChose', {
                      flow:
                        routerInsight.flow === 'off'
                          ? t('project.routerFlowOff')
                          : routerInsight.flow === 'sequential'
                            ? t('project.routerFlowSequential')
                            : t('project.routerFlowDebate'),
                      agents: routerInsight.agentNames,
                    })}
                  </div>
                  {routerInsight.reason ? (
                    <p className="text-[11px] leading-snug text-muted-foreground">
                      {routerInsight.reason}
                    </p>
                  ) : null}
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-muted-foreground">
                    <span>{t('project.routerUseManual')}</span>
                    {(['off', 'fast', 'standard', 'deep'] as const).map((m) => (
                      <button
                        key={m}
                        type="button"
                        className="underline decoration-muted-foreground/60 underline-offset-2 hover:text-foreground"
                        onClick={() => setDebateMode(m)}
                      >
                        {m === 'off'
                          ? t('project.debateModeOff')
                          : m === 'fast'
                            ? t('project.debateModeFast')
                            : m === 'standard'
                              ? t('project.debateModeStandard')
                              : t('project.debateModeDeep')}
                      </button>
                    ))}
                  </div>
                </div>
              )}
              <div className="flex gap-2">
                <div className="flex-1 relative">
                  <ChatMentionTextarea
                    ref={chatMentionRef}
                    value={message}
                    onChange={setMessage}
                    agents={visibleProjectAgents}
                    disabled={isChatBusy}
                    placeholder={t('project.chatPlaceholder')}
                    textareaClassName="bg-secondary border-border focus:border-primary resize-none pr-24 min-h-[44px] disabled:opacity-60"
                    onSubmit={() => void handleSendMessage()}
                    labels={{
                      listLabel: t('project.mentionListLabel'),
                      noMatches: t('project.mentionNoMatches'),
                    }}
                  />
                  <input
                    ref={chatFileInputRef}
                    type="file"
                    multiple
                    className="hidden"
                    onChange={(e) => handlePickChatFiles(e.target.files)}
                  />
                  <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      className={`relative h-8 w-8 hover:text-foreground ${
                        chatPendingFiles.length > 0
                          ? 'text-primary bg-primary/10'
                          : 'text-muted-foreground'
                      }`}
                      type="button"
                      onClick={() => chatFileInputRef.current?.click()}
                      disabled={isChatBusy}
                      aria-label={t('project.attachSr')}
                    >
                      <Paperclip className="w-4 h-4" />
                      {chatPendingFiles.length > 0 && (
                        <span className="absolute -top-1 -right-1 min-w-[16px] h-4 px-1 rounded-full bg-primary text-[10px] leading-4 text-primary-foreground">
                          {t('project.chatAttachCount', { count: chatPendingFiles.length })}
                        </span>
                      )}
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-muted-foreground hover:text-foreground"
                      type="button"
                      disabled={isChatBusy}
                      aria-label={t('project.mentionSr')}
                      onClick={() => chatMentionRef.current?.insertAtSign()}
                    >
                      <AtSign className="w-4 h-4" />
                    </Button>
                  </div>
                  {chatPendingFiles.length > 0 && (
                    <div className="mt-2 rounded-md border border-border/70 bg-secondary/50 p-2 transition-all duration-200 ease-out">
                      <div className="mb-1 text-xs text-muted-foreground">{t('project.chatFilesSelected')}</div>
                      <div className="flex flex-wrap gap-2">
                        {chatPendingFiles.map((file) => (
                          <div
                            key={`${file.name}:${file.size}:${file.lastModified}`}
                            className="inline-flex max-w-full items-center gap-2 rounded-md border border-border/60 bg-background/70 px-2 py-1 text-xs text-foreground"
                          >
                            <FileText className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                            <span className="truncate max-w-[180px]" title={file.name}>
                              {file.name}
                            </span>
                            <span className="text-muted-foreground">{formatPendingFileSize(file.size)}</span>
                            <Button
                              type="button"
                              variant="ghost"
                              size="icon"
                              className="h-5 w-5 text-muted-foreground hover:text-destructive"
                              onClick={() => handleRemoveChatPendingFile(file)}
                              disabled={isChatBusy}
                              aria-label={t('project.chatRemoveFileSr', { name: file.name })}
                            >
                              <X className="h-3 w-3" />
                            </Button>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
                <Button
                  onClick={() => void handleSendMessage()}
                  disabled={!message.trim() || isChatBusy}
                  className="gradient-accent text-white border-0 hover:opacity-90 disabled:opacity-50 min-w-[44px]"
                  aria-label={t('project.sendSr')}
                >
                  {isChatBusy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Send className="w-4 h-4" />}
                </Button>
              </div>
              {isUploadingChatFiles && (
                <div className="mt-2 text-xs text-muted-foreground">{t('project.chatUploadingFiles')}</div>
              )}
              {streamError && (
                <div className="mt-2 flex items-center gap-2 text-xs text-amber-300">
                  <span>{streamError}</span>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-7"
                    onClick={() => {
                      if (retryDraft) {
                        setMessage(retryDraft)
                        setStreamError(null)
                      }
                    }}
                  >
                    Повторить
                  </Button>
                </div>
              )}
              </div>
            </div>
          </div>
        )}

        {activeTab === 'agents' && (
          <div className="flex-1 min-h-0 overflow-y-auto">
          <div className="mx-auto max-w-6xl w-full px-4 py-4 sm:px-6">
            <div className="flex items-center justify-between mb-6">
              <div>
                <h3 className="text-lg font-semibold text-foreground">{t('project.teamTitle')}</h3>
                <p className="text-sm text-muted-foreground">
                  {visibleProjectAgents.length === 1
                    ? t('project.teamCount_one', { count: visibleProjectAgents.length })
                    : t('project.teamCount_other', { count: visibleProjectAgents.length })}
                </p>
              </div>
              <Dialog open={showAgentSelector} onOpenChange={setShowAgentSelector}>
                <DialogTrigger asChild>
                  <Button className="gradient-accent text-white border-0 hover:opacity-90">
                    <Plus className="w-4 h-4 mr-2" />
                    {t('project.addAgent')}
                  </Button>
                </DialogTrigger>
                <DialogContent className="border-border bg-card w-full max-w-3xl md:max-w-4xl lg:max-w-5xl mx-auto max-h-[85vh] overflow-y-auto overflow-x-hidden box-border px-5 sm:px-6">
                  <DialogHeader>
                    <DialogTitle>{t('project.addAgentDialogTitle')}</DialogTitle>
                  </DialogHeader>
                  <div className="space-y-4 pr-2 min-w-0">
                    <div>
                      <h3 className="mb-2 text-sm font-medium text-foreground">Product Team</h3>
                      <AgentSelector
                        availableAgents={availableProductToAdd}
                        selectedAgents={[]}
                        onSelect={(agentId) => {
                          void handleAddAgent(agentId)
                          setShowAgentSelector(false)
                        }}
                      />
                    </div>
                    {project.isCryptoEnabled && (
                      <div>
                        <h3 className="mb-2 text-sm font-medium text-foreground">Crypto Trading Team</h3>
                        <AgentSelector
                          availableAgents={availableCryptoToAdd}
                          selectedAgents={[]}
                          onSelect={(agentId) => {
                            void handleAddAgent(agentId)
                            setShowAgentSelector(false)
                          }}
                        />
                      </div>
                    )}
                  </div>
                </DialogContent>
              </Dialog>
            </div>

            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {visibleProjectAgents.map((agent) => (
                <Card key={agent.id} className="p-4 bg-card border-border">
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-3">
                      <AgentAvatar agent={agent} size="lg" />
                      <div>
                        <div className="flex items-center gap-2">
                          <h4 className="font-medium text-foreground">{agent.name}</h4>
                          {agent.role === 'crypto_interpreter' && (
                            <span className="rounded-full border border-purple-400/40 bg-purple-500/15 px-2 py-0.5 text-[10px] text-purple-300">
                              👤 Для новичков
                            </span>
                          )}
                        </div>
                        <p className="text-xs font-mono text-muted-foreground">{agent.model}</p>
                      </div>
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 text-muted-foreground hover:text-destructive"
                      onClick={() => void handleRemoveAgent(agent.id)}
                      aria-label={t('project.removeAgentSr', { name: agent.name })}
                    >
                      <X className="w-4 h-4" />
                    </Button>
                  </div>
                  <p className="text-sm text-muted-foreground mt-3">
                    {agentCardDescription(agent.role, locale)}
                  </p>
                  <div className="flex items-center gap-2 mt-4 pt-3 border-t border-border/50">
                    <span className="w-2 h-2 rounded-full bg-green-500" />
                    <span className="text-xs text-muted-foreground">{t('common.active')}</span>
                  </div>
                </Card>
              ))}
            </div>
          </div>
          </div>
        )}

        {activeTab === 'files' && (
          <div className="flex-1 min-h-0 overflow-y-auto">
          <div className="mx-auto max-w-6xl w-full px-4 py-4 sm:px-6">
            <div className="flex items-center justify-between mb-6">
              <div>
                <h3 className="text-lg font-semibold text-foreground">{t('project.filesTitle')}</h3>
                <p className="text-sm text-muted-foreground">
                  {project.files.length === 1
                    ? t('project.filesCount_one', { count: project.files.length })
                    : t('project.filesCount_other', { count: project.files.length })}
                </p>
              </div>
              <Dialog open={showUploadDialog} onOpenChange={setShowUploadDialog}>
                <DialogTrigger asChild>
                  <Button className="gradient-accent text-white border-0 hover:opacity-90">
                    <Upload className="w-4 h-4 mr-2" />
                    {t('project.uploadFiles')}
                  </Button>
                </DialogTrigger>
                <DialogContent className="bg-card border-border">
                  <DialogHeader>
                    <DialogTitle>{t('project.uploadDialogTitle')}</DialogTitle>
                  </DialogHeader>
                  <FileUploadZone onUpload={(files) => void handleUploadFiles(files)} />
                </DialogContent>
              </Dialog>
            </div>

            <ProjectFilesList
              files={project.files}
              onDelete={(fileId) => void handleDeleteFile(fileId)}
              onDownload={(fileId) => {
                window.open(getDownloadUrl(fileId), '_blank', 'noopener,noreferrer')
              }}
            />
          </div>
          </div>
        )}

        {activeTab === 'results' && (
          <div className="flex-1 min-h-0 overflow-y-auto">
          <div className="mx-auto max-w-6xl w-full px-4 py-4 sm:px-6">
            <div className="mb-6">
              <h3 className="text-lg font-semibold text-foreground">{t('project.resultsTitle')}</h3>
              <p className="text-sm text-muted-foreground">{t('project.resultsSubtitle')}</p>
            </div>

            <ResultsView results={results} agents={visibleProjectAgents} />
          </div>
          </div>
        )}
      </main>

      <Dialog
        open={tradeModal.open}
        onOpenChange={(open) =>
          setTradeModal((prev) => (open ? prev : { open: false, message: null, draft: null, comment: '' }))
        }
      >
        <DialogContent className="bg-card border-border">
          <DialogHeader>
            <DialogTitle>Открыть бумажную сделку</DialogTitle>
            <DialogDescription>Проверьте распознанные поля из сигнала агента</DialogDescription>
          </DialogHeader>
          {tradeModal.draft && (
            <div className="space-y-2 text-sm">
              <div>Актив: <b>{tradeModal.draft.asset}</b></div>
              <div>Таймфрейм: <b>{tradeModal.draft.timeframe}</b></div>
              <div>Сигнал: <b>{tradeModal.draft.signal}</b></div>
              <div>Вход: <b>{tradeModal.draft.entryPrice ?? '—'}</b></div>
              <div>SL: <b>{tradeModal.draft.stopLoss ?? '—'}</b></div>
              <div>TP: <b>{tradeModal.draft.takeProfit ?? '—'}</b></div>
              <textarea
                value={tradeModal.comment}
                onChange={(e) => setTradeModal((prev) => ({ ...prev, comment: e.target.value }))}
                className="w-full min-h-20 rounded-md border border-border bg-secondary px-2 py-2"
                placeholder="Комментарий пользователя"
              />
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setTradeModal({ open: false, message: null, draft: null, comment: '' })}>Отмена</Button>
            <Button onClick={() => void handleConfirmTrade()}>Подтвердить</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={showSettingsDialog}
        onOpenChange={(open) => {
          if (!open && isSavingSettings) return
          setShowSettingsDialog(open)
        }}
      >
        <DialogContent className="border-border bg-card sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Настройки проекта</DialogTitle>
            <DialogDescription>
              Включите крипто-режим, чтобы видеть крипто-агентов и вкладку Paper Trading.
            </DialogDescription>
          </DialogHeader>
          <div className="rounded-lg border border-border p-3">
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-sm font-medium text-foreground">Crypto Trading Mode</div>
                <div className="text-xs text-muted-foreground">
                  Включить крипто-агентов (Technical, On-chain, Sentiment, Risk) и вкладку Paper Trading
                </div>
              </div>
              <Switch checked={cryptoModeDraft} onCheckedChange={setCryptoModeDraft} />
            </div>
            {project.isCryptoEnabled && !cryptoModeDraft && (
              <p className="mt-3 rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-1.5 text-xs text-amber-200">
                Крипто-агенты будут скрыты, но останутся в проекте. Включите режим снова, чтобы их увидеть.
              </p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowSettingsDialog(false)} disabled={isSavingSettings}>
              Отмена
            </Button>
            <Button onClick={() => void handleSaveProjectSettings()} disabled={isSavingSettings}>
              {isSavingSettings ? 'Сохранение...' : 'Сохранить'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={showDeleteProjectDialog}
        onOpenChange={(open) => {
          if (!open && isDeletingProject) return
          setShowDeleteProjectDialog(open)
        }}
      >
        <DialogContent
          showCloseButton={!isDeletingProject}
          className="border-border bg-card sm:max-w-md shadow-xl shadow-black/30 ring-1 ring-primary/15"
        >
          <DialogHeader className="text-center sm:text-center gap-3">
            <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-destructive/15 ring-1 ring-destructive/25">
              <Trash2 className="h-6 w-6 text-destructive" aria-hidden />
            </div>
            <DialogTitle className="text-xl font-semibold tracking-tight text-foreground">
              {t('project.deleteDialogTitle')}
            </DialogTitle>
            <DialogDescription className="text-base leading-relaxed text-muted-foreground px-1">
              {t('project.deleteDialogDescription')}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="flex w-full flex-row justify-between gap-2 pt-2 sm:flex-row sm:justify-between">
            <Button
              type="button"
              variant="outline"
              className="border-border min-w-[100px]"
              disabled={isDeletingProject}
              onClick={() => setShowDeleteProjectDialog(false)}
            >
              {t('project.deleteDialogCancel')}
            </Button>
            <Button
              type="button"
              variant="destructive"
              className="min-w-[120px]"
              disabled={isDeletingProject}
              aria-busy={isDeletingProject}
              onClick={() => void handleConfirmDeleteProject()}
            >
              {isDeletingProject ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin shrink-0" aria-hidden />
                  {t('project.deleteDialogWorking')}
                </>
              ) : (
                t('project.deleteDialogConfirm')
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
