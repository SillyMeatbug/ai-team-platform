export type AgentRole =
  | 'analyst'
  | 'designer'
  | 'frontend'
  | 'backend'
  | 'frontend_dev'
  | 'backend_dev'
  | 'copywriter'
  | 'devops'
  | 'arbiter'
  | 'technical_analyst'
  | 'onchain_analyst'
  | 'sentiment_analyst'
  | 'risk_manager'
  | 'crypto_interpreter'
  | 'other'

export interface Agent {
  id: string
  name: string
  model: string
  role: AgentRole
  description: string
  color: string
  systemPrompt?: string
  isActive?: boolean
}

export interface ProjectFile {
  id: string
  name: string
  size: string
  sizeBytes?: number
  type: 'pdf' | 'doc' | 'image' | 'text' | 'figma' | 'other'
  category: 'brief' | 'mockup' | 'reference' | 'generated'
  uploadedAt: string
  contentType?: string
}

export interface ChatMessage {
  id: string
  agentId: string
  senderType?: 'user' | 'agent'
  content: string
  timestamp: string
  isGroupDiscussion?: boolean
  discussionId?: string
  attachmentFileIds?: string[]
  attachments?: ProjectFile[]
  error?: string | null
  /** Из GET /chat (вложенный AgentOut); не зависит от состава проекта — для UI при mock/offline данных команды */
  agentSnapshot?: Agent
}

export type DebateMode = 'auto' | 'off' | 'fast' | 'standard' | 'deep'
export type DebateStatus =
  | 'running'
  | 'agents_discussing'
  | 'synthesizing'
  | 'cancelled'
  | 'completed'
  | 'timed_out'
  | 'failed'

export interface DebateThread {
  id: string
  projectId: string
  userMessageId: string
  mode: DebateMode
  status: DebateStatus
  totalRounds: number
  currentRound: number
  startedAt: string
  finishedAt?: string
  timeoutAt?: string
  finalSummary?: string
  confidence?: string
  disagreements?: string
  finalMessageId?: string
}

export interface DebateRound {
  id: string
  threadId: string
  roundNumber: number
  status: string
  startedAt: string
  finishedAt?: string
  roundSummary?: string
}

export interface DebateTurn {
  id: string
  threadId: string
  roundId: string
  agentId: string
  turnOrder: number
  content: string
  error?: string | null
  createdAt: string
  agentSnapshot?: Agent
}

export interface DebateLog {
  thread: DebateThread
  rounds: DebateRound[]
  turns: DebateTurn[]
}

export interface Project {
  id: string
  name: string
  description: string
  isCryptoEnabled: boolean
  agents: Agent[]
  files: ProjectFile[]
  messages: ChatMessage[]
  fileCount?: number
  messageCount?: number
  createdAt: string
  updatedAt: string
}

export type ProjectTab = 'chat' | 'agents' | 'files' | 'results' | 'paper-trading'

export interface AgentResult {
  id: string
  agentId: string
  title: string
  category: 'architecture' | 'design' | 'code' | 'content'
  content: string
  createdAt: string
}

export type MarketStatus = 'live' | 'cached' | 'unavailable'

export interface MarketContext {
  status: MarketStatus
  source: string
  timestamp: string
  asset: string
  timeframe: string
  price_snapshot: {
    open: number | null
    high: number | null
    low: number | null
    close: number | null
    volume: number | null
    candles_count: number
  }
  indicators: {
    rsi_14: number | null
    macd_signal: number | null
    ema_20_50_cross: string | null
    atr: number | null
    bb_upper: number | null
    bb_lower: number | null
  }
  market_metrics: {
    funding_rate_pct: number | null
    open_interest_usd: number | null
    long_short_ratio: number | null
  }
  sentiment_brief: string
  cache_info: {
    hit: boolean
    ttl_remaining_sec: number
  }
  error_detail?: string | null
}

export interface MarketHealth {
  status: 'healthy' | 'degraded'
  sources: Record<string, boolean>
  latency_ms: Record<string, number>
  timestamp: string
}

export type PaperTradeSignal = 'long' | 'short' | 'neutral'
export type PaperTradeStatus = 'open' | 'closed' | 'stopped' | 'expired'

export interface PaperTrade {
  id: string
  projectId: string
  agentId: string
  messageId: string | null
  asset: string
  timeframe: string
  signal: PaperTradeSignal
  entryPrice: number
  stopLoss: number | null
  takeProfit: number | null
  confidence: number
  rationale: string
  signalTimestamp: string
  openedAt: string
  closedAt: string | null
  exitPrice: number | null
  pnlPct: number | null
  status: PaperTradeStatus
}
