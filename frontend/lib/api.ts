import { agentCardDescription } from '@/lib/i18n/agent-cards'
import type {
  Agent,
  AgentResult,
  ChatMessage,
  DebateLog,
  DebateMode,
  DebateRound,
  DebateThread,
  DebateTurn,
  MarketContext,
  MarketHealth,
  PaperTrade,
  Project,
  ProjectFile,
} from '@/lib/types'

/** По умолчанию 127.0.0.1: на Windows `localhost` часто уходит в IPv6 (::1), а uvicorn слушает IPv4 — запрос «висит». */
export function getApiBaseUrl(): string {
  if (typeof window !== 'undefined') {
    const fromDom = document.documentElement
      .getAttribute('data-api-public-url')
      ?.trim()
    if (fromDom) return fromDom.replace(/\/$/, '')
  }
  const raw =
    process.env.BACKEND_PUBLIC_URL?.trim() ||
    process.env.NEXT_PUBLIC_API_URL?.trim() ||
    process.env.NEXT_PUBLIC_API_BASE_URL?.trim() ||
    ''
  const base = raw || 'http://127.0.0.1:8000'
  return base.replace(/\/$/, '')
}

type RequestOptions = {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE'
  body?: unknown
  headers?: Record<string, string>
  signal?: AbortSignal
}

const API_FETCH_TIMEOUT_MS = 15_000

async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const controller = new AbortController()
  let didTimeout = false
  const timeoutId = setTimeout(() => {
    didTimeout = true
    controller.abort()
  }, API_FETCH_TIMEOUT_MS)

  const outerSignal = options.signal
  const onOuterAbort = () => controller.abort()
  if (outerSignal) {
    if (outerSignal.aborted) controller.abort()
    else outerSignal.addEventListener('abort', onOuterAbort)
  }

  let res: Response
  try {
    res = await fetch(`${getApiBaseUrl()}${path}`, {
      method: options.method ?? 'GET',
      headers: {
        'Content-Type': 'application/json',
        ...(options.headers ?? {}),
      },
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: controller.signal,
    })
  } catch (e) {
    const name =
      e instanceof DOMException ? e.name : e instanceof Error ? e.name : ''
    if (name === 'AbortError') {
      if (didTimeout) {
        throw new Error(
          `Нет ответа от API (${getApiBaseUrl()}) за ${API_FETCH_TIMEOUT_MS / 1000} с. Запустите бэкенд (127.0.0.1:8000): uvicorn main:app --host 127.0.0.1 --port 8000`
        )
      }
      throw e
    }
    throw e
  } finally {
    clearTimeout(timeoutId)
    if (outerSignal) outerSignal.removeEventListener('abort', onOuterAbort)
  }

  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const json = await res.json()
      detail = json?.detail ?? detail
    } catch {
      // ignore json parse
    }
    throw new Error(detail)
  }

  if (res.status === 204) {
    return undefined as T
  }
  return (await res.json()) as T
}

type ApiProject = {
  id: string
  name: string
  description: string | null
  created_at: string
  updated_at: string
  is_active: boolean
  is_crypto_enabled: boolean
  file_count?: number
  message_count?: number
}

type ApiAgent = {
  id: string
  name: string
  model: string
  role: string
  system_prompt: string
  color: string
  is_active: boolean
}

type ApiProjectAgent = {
  project_id: string
  agent_id: string
  joined_at: string
  is_active: boolean
  agent: ApiAgent
}

type ApiProjectFile = {
  id: string
  project_id: string
  filename: string
  file_size: number
  content_type: string
  uploaded_at: string
  category: ProjectFile['category']
}

type ApiChatMessage = {
  id: string
  project_id: string
  sender_type: 'user' | 'agent'
  sender_id: string | null
  content: string
  timestamp: string
  is_discussion: boolean
  parent_message_id: string | null
  error?: string | null
  attachment_file_ids?: string[] | null
  attachments?: ApiProjectFile[] | null
  agent?: ApiAgent | null
}

type ApiDebateThread = {
  id: string
  project_id: string
  user_message_id: string
  mode: DebateMode
  status: 'running' | 'agents_discussing' | 'synthesizing' | 'cancelled' | 'completed' | 'timed_out' | 'failed'
  total_rounds: number
  current_round: number
  started_at: string
  finished_at: string | null
  timeout_at: string | null
  final_summary: string | null
  confidence: string | null
  disagreements: string | null
  final_message_id: string | null
}

type ApiDebateRound = {
  id: string
  thread_id: string
  round_number: number
  status: string
  started_at: string
  finished_at: string | null
  round_summary: string | null
}

type ApiDebateTurn = {
  id: string
  thread_id: string
  round_id: string
  agent_id: string
  turn_order: number
  content: string
  error: string | null
  created_at: string
  agent?: ApiAgent | null
}

type ApiResult = {
  id: string
  project_id: string
  agent_id: string
  category: AgentResult['category'] | 'other'
  title: string
  content: string
  created_at: string
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function mapRole(role: string): Agent['role'] {
  if (
    role === 'analyst' ||
    role === 'designer' ||
    role === 'frontend' ||
    role === 'backend' ||
    role === 'frontend_dev' ||
    role === 'backend_dev' ||
    role === 'copywriter' ||
    role === 'devops' ||
    role === 'arbiter' ||
    role === 'technical_analyst' ||
    role === 'onchain_analyst' ||
    role === 'sentiment_analyst' ||
    role === 'risk_manager' ||
    role === 'crypto_interpreter'
  ) {
    return role
  }
  return 'other'
}

type ApiPaperTrade = {
  id: string
  project_id: string
  agent_id: string
  message_id: string | null
  asset: string
  timeframe: string
  signal: 'long' | 'short' | 'neutral'
  entry_price: number
  stop_loss: number | null
  take_profit: number | null
  confidence: number
  rationale: string
  signal_timestamp: string
  opened_at: string
  closed_at: string | null
  exit_price: number | null
  pnl_pct: number | null
  status: 'open' | 'closed' | 'stopped' | 'expired'
}

function mapAgent(api: ApiAgent): Agent {
  const role = mapRole(api.role)
  return {
    id: api.id,
    name: api.name,
    model: api.model,
    role,
    color: api.color,
    description: agentCardDescription(role, 'en'),
    systemPrompt: api.system_prompt,
    isActive: api.is_active,
  }
}

function inferFileType(file: ApiProjectFile): ProjectFile['type'] {
  const ext = file.filename.split('.').pop()?.toLowerCase() ?? ''
  if (['png', 'jpg', 'jpeg', 'gif', 'webp'].includes(ext)) return 'image'
  if (ext === 'pdf') return 'pdf'
  if (['doc', 'docx'].includes(ext)) return 'doc'
  if (ext === 'fig') return 'figma'
  if (['txt', 'md', 'csv', 'json'].includes(ext)) return 'text'
  return 'other'
}

function mapFile(api: ApiProjectFile): ProjectFile {
  return {
    id: api.id,
    name: api.filename,
    size: formatBytes(api.file_size),
    sizeBytes: api.file_size,
    type: inferFileType(api),
    category: api.category,
    uploadedAt: new Date(api.uploaded_at).toLocaleString(),
    contentType: api.content_type,
  }
}

function mapProject(api: ApiProject): Project {
  return {
    id: api.id,
    name: api.name,
    description: api.description ?? '',
    isCryptoEnabled: Boolean(api.is_crypto_enabled),
    agents: [],
    files: [],
    messages: [],
    fileCount: api.file_count ?? 0,
    messageCount: api.message_count ?? 0,
    createdAt: api.created_at,
    updatedAt: api.updated_at,
  }
}

function mapChatMessage(api: ApiChatMessage): ChatMessage {
  return {
    id: api.id,
    agentId: api.sender_type === 'user' ? 'user' : (api.sender_id ?? 'unknown-agent'),
    senderType: api.sender_type,
    content: api.content,
    timestamp: new Date(api.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    isGroupDiscussion: api.is_discussion,
    discussionId: api.parent_message_id ?? undefined,
    attachmentFileIds: api.attachment_file_ids ?? [],
    attachments: (api.attachments ?? []).map(mapFile),
    error: api.error ?? null,
    agentSnapshot: api.agent ? mapAgent(api.agent) : undefined,
  }
}

function mapDebateThread(api: ApiDebateThread): DebateThread {
  return {
    id: api.id,
    projectId: api.project_id,
    userMessageId: api.user_message_id,
    mode: api.mode,
    status: api.status,
    totalRounds: api.total_rounds,
    currentRound: api.current_round,
    startedAt: api.started_at,
    finishedAt: api.finished_at ?? undefined,
    timeoutAt: api.timeout_at ?? undefined,
    finalSummary: api.final_summary ?? undefined,
    confidence: api.confidence ?? undefined,
    disagreements: api.disagreements ?? undefined,
    finalMessageId: api.final_message_id ?? undefined,
  }
}

function mapDebateRound(api: ApiDebateRound): DebateRound {
  return {
    id: api.id,
    threadId: api.thread_id,
    roundNumber: api.round_number,
    status: api.status,
    startedAt: api.started_at,
    finishedAt: api.finished_at ?? undefined,
    roundSummary: api.round_summary ?? undefined,
  }
}

function mapDebateTurn(api: ApiDebateTurn): DebateTurn {
  return {
    id: api.id,
    threadId: api.thread_id,
    roundId: api.round_id,
    agentId: api.agent_id,
    messageId: api.message_id,
    turnOrder: api.turn_order,
    content: api.content,
    error: api.error ?? null,
    createdAt: api.created_at,
    agentSnapshot: api.agent ? mapAgent(api.agent) : undefined,
  }
}

function mapResult(api: ApiResult): AgentResult {
  return {
    id: api.id,
    agentId: api.agent_id,
    category: api.category === 'other' ? 'content' : api.category,
    title: api.title,
    content: api.content,
    createdAt: new Date(api.created_at).toLocaleString(),
  }
}

function mapPaperTrade(api: ApiPaperTrade): PaperTrade {
  return {
    id: api.id,
    projectId: api.project_id,
    agentId: api.agent_id,
    asset: api.asset,
    timeframe: api.timeframe,
    signal: api.signal,
    entryPrice: api.entry_price,
    stopLoss: api.stop_loss,
    takeProfit: api.take_profit,
    confidence: api.confidence,
    rationale: api.rationale,
    signalTimestamp: api.signal_timestamp,
    openedAt: api.opened_at,
    closedAt: api.closed_at,
    exitPrice: api.exit_price,
    pnlPct: api.pnl_pct,
    status: api.status,
  }
}

export async function getProjects(signal?: AbortSignal): Promise<Project[]> {
  const data = await apiFetch<ApiProject[]>('/v1/projects', { signal })
  return data.map(mapProject)
}

export async function createProject(payload: {
  name: string
  description?: string
  is_crypto_enabled?: boolean
}): Promise<Project> {
  const data = await apiFetch<ApiProject>('/v1/projects', {
    method: 'POST',
    body: payload,
  })
  return mapProject(data)
}

export async function updateProject(
  projectId: string,
  payload: { name?: string; description?: string; is_active?: boolean; is_crypto_enabled?: boolean }
): Promise<Project> {
  const data = await apiFetch<ApiProject>(`/v1/projects/${projectId}`, {
    method: 'PUT',
    body: payload,
  })
  return mapProject(data)
}

export async function getProject(projectId: string): Promise<Project> {
  const data = await apiFetch<ApiProject>(`/v1/projects/${projectId}`)
  return mapProject(data)
}

export async function deleteProject(projectId: string): Promise<void> {
  await apiFetch<void>(`/v1/projects/${projectId}`, { method: 'DELETE' })
}

export async function getAllAgents(): Promise<Agent[]> {
  const data = await apiFetch<ApiAgent[]>('/v1/agents')
  return data.map(mapAgent)
}

export async function getProjectAgents(projectId: string): Promise<Agent[]> {
  const data = await apiFetch<ApiProjectAgent[]>(`/v1/projects/${projectId}/agents`)
  return data.map((item) => mapAgent(item.agent))
}

export async function addProjectAgent(projectId: string, agentId: string): Promise<void> {
  await apiFetch(`/v1/projects/${projectId}/agents`, {
    method: 'POST',
    body: { agent_id: agentId },
  })
}

export async function removeProjectAgent(projectId: string, agentId: string): Promise<void> {
  await apiFetch(`/v1/projects/${projectId}/agents/${agentId}`, { method: 'DELETE' })
}

export async function getProjectFiles(projectId: string): Promise<ProjectFile[]> {
  const data = await apiFetch<ApiProjectFile[]>(`/v1/projects/${projectId}/files`)
  return data.map(mapFile)
}

export async function uploadProjectFile(projectId: string, file: File, category: ProjectFile['category'] = 'brief'): Promise<ProjectFile> {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('category', category)

  const res = await fetch(`${getApiBaseUrl()}/v1/projects/${projectId}/files`, {
    method: 'POST',
    body: formData,
  })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const json = await res.json()
      detail = json?.detail ?? detail
    } catch {
      // ignore
    }
    throw new Error(detail)
  }
  const data = (await res.json()) as ApiProjectFile
  return mapFile(data)
}

export async function deleteProjectFile(projectId: string, fileId: string): Promise<void> {
  await apiFetch(`/v1/projects/${projectId}/files/${fileId}`, { method: 'DELETE' })
}

export function getDownloadUrl(fileId: string): string {
  return `${getApiBaseUrl()}/v1/files/${fileId}/download`
}

export async function getProjectChat(projectId: string): Promise<ChatMessage[]> {
  const data = await apiFetch<ApiChatMessage[]>(`/v1/projects/${projectId}/chat`)
  return data.map(mapChatMessage)
}

export type ChatAcceptedPayload = {
  user_message: ChatMessage
  pending_agent_ids: string[]
  selected_agents?: string[]
  response_order?: string[]
  is_discussion: boolean
  debate_mode: DebateMode
  debate_thread_id?: string
  router_reason?: string
  router_flow?: 'off' | 'sequential' | 'debate'
  streaming_enabled?: boolean
}

function mapAcceptedPayload(data: {
  user_message: ApiChatMessage
  pending_agent_ids: string[]
  selected_agents?: string[] | null
  response_order?: string[] | null
  is_discussion: boolean
  debate_mode: DebateMode
  debate_thread_id?: string | null
  router_reason?: string | null
  router_flow?: 'off' | 'sequential' | 'debate' | null
  streaming_enabled?: boolean | null
}): ChatAcceptedPayload {
  return {
    user_message: mapChatMessage(data.user_message),
    pending_agent_ids: data.pending_agent_ids,
    selected_agents: data.selected_agents ?? undefined,
    response_order: data.response_order ?? undefined,
    is_discussion: data.is_discussion,
    debate_mode: data.debate_mode,
    debate_thread_id: data.debate_thread_id ?? undefined,
    router_reason: data.router_reason ?? undefined,
    router_flow: data.router_flow ?? undefined,
    streaming_enabled: data.streaming_enabled ?? undefined,
  }
}

export async function sendProjectChat(
  projectId: string,
  payload: { content: string; mentioned_agent_ids?: string[]; debate_mode?: DebateMode; locale?: 'en' | 'ru'; file_ids?: string[] }
): Promise<ChatAcceptedPayload> {
  const body: Record<string, unknown> = { content: payload.content }
  if (payload.mentioned_agent_ids?.length) {
    body.mentioned_agent_ids = payload.mentioned_agent_ids
  }
  if (payload.debate_mode) {
    body.debate_mode = payload.debate_mode
  }
  if (payload.locale) {
    body.locale = payload.locale
  }
  if (payload.file_ids?.length) {
    body.file_ids = payload.file_ids
  }

  const data = await apiFetch<{
    user_message: ApiChatMessage
    pending_agent_ids: string[]
    selected_agents?: string[] | null
    response_order?: string[] | null
    is_discussion: boolean
    debate_mode: DebateMode
    debate_thread_id?: string | null
    router_reason?: string | null
    router_flow?: 'off' | 'sequential' | 'debate' | null
  }>(`/v1/projects/${projectId}/chat`, {
    method: 'POST',
    body,
  })

  return mapAcceptedPayload(data)
}

export type StreamChatEvent =
  | ({ type: 'accepted' } & ChatAcceptedPayload)
  | { type: 'streaming_disabled'; reason?: string }
  | { type: 'round_start'; round: number; total_rounds: number }
  | { type: 'token'; agent_id: string; content: string }
  | { type: 'agent_done'; agent_id: string; error?: string | null }
  | { type: 'error'; detail: string }
  | { type: 'complete' }

export type StreamChatResult =
  | { streamingEnabled: true }
  | { streamingEnabled: false; accepted?: ChatAcceptedPayload; reason?: string }

export async function streamChatMessage(
  projectId: string,
  payload: { content: string; mentioned_agent_ids?: string[]; debate_mode?: DebateMode; locale?: 'en' | 'ru'; file_ids?: string[] },
  onEvent: (event: StreamChatEvent) => void
): Promise<StreamChatResult> {
  if (typeof ReadableStream === 'undefined') {
    throw new Error('SSE not supported by browser')
  }
  const body: Record<string, unknown> = { content: payload.content }
  if (payload.mentioned_agent_ids?.length) body.mentioned_agent_ids = payload.mentioned_agent_ids
  if (payload.debate_mode) body.debate_mode = payload.debate_mode
  if (payload.locale) body.locale = payload.locale
  if (payload.file_ids?.length) body.file_ids = payload.file_ids

  const res = await fetch(`${getApiBaseUrl()}/v1/projects/${projectId}/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    throw new Error(`stream failed: ${res.status} ${res.statusText}`)
  }
  const contentType = res.headers.get('content-type') || ''
  if (contentType.includes('application/json')) {
    const data = (await res.json()) as {
      user_message: ApiChatMessage
      pending_agent_ids: string[]
      selected_agents?: string[] | null
      response_order?: string[] | null
      is_discussion: boolean
      debate_mode: DebateMode
      debate_thread_id?: string | null
      router_reason?: string | null
      router_flow?: 'off' | 'sequential' | 'debate' | null
      streaming_enabled?: boolean | null
    }
    return { streamingEnabled: false, accepted: mapAcceptedPayload(data) }
  }
  if (!res.body) {
    throw new Error('stream failed: empty body')
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let streamingDisabled = false
  let streamingDisabledReason: string | undefined
  let acceptedFromStream: ChatAcceptedPayload | undefined

  const emitSseEventBlock = (rawBlock: string) => {
    const line = rawBlock
      .split('\n')
      .find((l) => l.trimStart().startsWith('data:'))
    if (!line) return
    const data = line.replace(/^\s*data:\s?/, '').trim()
    if (!data) return
    try {
      const parsed = JSON.parse(data) as Record<string, unknown>
      if (parsed.type === 'accepted' && parsed.user_message && typeof parsed.user_message === 'object') {
        const accepted = mapAcceptedPayload(parsed as never)
        acceptedFromStream = accepted
        onEvent({ type: 'accepted', ...accepted })
      } else if (parsed.type === 'streaming_disabled') {
        streamingDisabled = true
        streamingDisabledReason = typeof parsed.reason === 'string' ? parsed.reason : undefined
        onEvent({ type: 'streaming_disabled', reason: streamingDisabledReason })
      } else if (parsed.type === 'token' && typeof parsed.agent_id === 'string' && typeof parsed.content === 'string') {
        onEvent({ type: 'token', agent_id: parsed.agent_id, content: parsed.content })
      } else if (parsed.type === 'agent_done' && typeof parsed.agent_id === 'string') {
        onEvent({
          type: 'agent_done',
          agent_id: parsed.agent_id,
          error: typeof parsed.error === 'string' ? parsed.error : null,
        })
      } else if (parsed.type === 'round_start' && typeof parsed.round === 'number' && typeof parsed.total_rounds === 'number') {
        onEvent({ type: 'round_start', round: parsed.round, total_rounds: parsed.total_rounds })
      } else if (parsed.type === 'error' && typeof parsed.detail === 'string') {
        onEvent({ type: 'error', detail: parsed.detail })
      } else if (parsed.type === 'complete') {
        onEvent({ type: 'complete' })
      }
    } catch {
      // ignore bad event frame
    }
  }

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    buffer = buffer.replace(/\r\n/g, '\n')
    const chunks = buffer.split('\n\n')
    buffer = chunks.pop() ?? ''
    for (const chunk of chunks) {
      if (!chunk.trim()) continue
      emitSseEventBlock(chunk)
    }
  }

  buffer = buffer.replace(/\r\n/g, '\n')
  for (const chunk of buffer.split('\n\n')) {
    if (!chunk.trim()) continue
    emitSseEventBlock(chunk)
  }
  if (streamingDisabled) {
    return {
      streamingEnabled: false,
      reason: streamingDisabledReason,
      accepted: acceptedFromStream,
    }
  }
  return { streamingEnabled: true }
}

export async function getDebateThread(projectId: string, threadId: string): Promise<DebateThread> {
  const data = await apiFetch<ApiDebateThread>(`/v1/projects/${projectId}/debates/${threadId}`)
  return mapDebateThread(data)
}

export async function getDebateLog(projectId: string, threadId: string): Promise<DebateLog> {
  const data = await apiFetch<{
    thread: ApiDebateThread
    rounds: ApiDebateRound[]
    turns: ApiDebateTurn[]
  }>(`/v1/projects/${projectId}/debates/${threadId}/log`)
  return {
    thread: mapDebateThread(data.thread),
    rounds: data.rounds.map(mapDebateRound),
    turns: data.turns.map(mapDebateTurn),
  }
}

export async function cancelDebateThread(projectId: string, threadId: string): Promise<DebateThread> {
  const data = await apiFetch<ApiDebateThread>(`/v1/projects/${projectId}/debates/${threadId}/cancel`, {
    method: 'POST',
  })
  return mapDebateThread(data)
}

export async function getProjectResults(projectId: string): Promise<AgentResult[]> {
  const data = await apiFetch<ApiResult[]>(`/v1/projects/${projectId}/results`)
  return data.map(mapResult)
}

export async function getMarketContext(
  asset: string = 'BTC/USDT',
  timeframe: string = '4H',
  refresh: boolean = false
): Promise<MarketContext> {
  const qs = new URLSearchParams({
    asset,
    timeframe,
    refresh: refresh ? 'true' : 'false',
  })
  return await apiFetch<MarketContext>(`/v1/market/context?${qs.toString()}`)
}

export async function getMarketHealth(): Promise<MarketHealth> {
  return await apiFetch<MarketHealth>('/v1/market/health')
}

export async function getProjectPaperTrades(
  projectId: string,
  status?: 'open' | 'closed' | 'stopped' | 'expired'
): Promise<PaperTrade[]> {
  const qs = status ? `?status=${encodeURIComponent(status)}` : ''
  const data = await apiFetch<ApiPaperTrade[]>(`/v1/projects/${projectId}/paper-trades${qs}`)
  return data.map(mapPaperTrade)
}

export async function reconcileProjectPaperTrades(
  projectId: string,
  payload?: { asset?: string; timeframe?: string }
): Promise<{ updated: number }> {
  const qs = new URLSearchParams()
  if (payload?.asset) qs.set('asset', payload.asset)
  if (payload?.timeframe) qs.set('timeframe', payload.timeframe)
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return await apiFetch<{ updated: number }>(`/v1/projects/${projectId}/paper-trades/reconcile${suffix}`, {
    method: 'POST',
  })
}

export async function createProjectPaperTrade(
  projectId: string,
  payload: {
    agent_id: string
    message_id?: string
    asset: string
    timeframe: string
    signal: 'long' | 'short' | 'neutral'
    entry_price: number
    stop_loss?: number | null
    take_profit?: number | null
    confidence?: number
    rationale?: string
    signal_timestamp: string
  }
): Promise<PaperTrade> {
  const data = await apiFetch<ApiPaperTrade>(`/v1/projects/${projectId}/paper-trades`, {
    method: 'POST',
    body: payload,
  })
  return mapPaperTrade(data)
}

export async function closeProjectPaperTrade(
  projectId: string,
  tradeId: string,
  exitPrice: number
): Promise<PaperTrade> {
  const data = await apiFetch<ApiPaperTrade>(`/v1/projects/${projectId}/paper-trades/${tradeId}/close`, {
    method: 'POST',
    body: { exit_price: exitPrice },
  })
  return mapPaperTrade(data)
}
