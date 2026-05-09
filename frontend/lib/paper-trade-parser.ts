import type { Agent, ChatMessage } from '@/lib/types'

export type ParsedTradeDraft = {
  signal: 'long' | 'short' | 'neutral'
  confidence: number
  entryPrice: number | null
  stopLoss: number | null
  takeProfit: number | null
  asset: string
  timeframe: string
  signalTimestamp: string | null
}

const CRYPTO_ROLES = new Set([
  'technical_analyst',
  'onchain_analyst',
  'sentiment_analyst',
  'risk_manager',
])

function parseNumber(raw?: string): number | null {
  if (!raw) return null
  const cleaned = raw.replace(/[, ]/g, '')
  const n = Number(cleaned)
  return Number.isFinite(n) ? n : null
}

export function parseTradeDraftFromContent(content: string): ParsedTradeDraft | null {
  const low = content.toLowerCase()
  const signal: ParsedTradeDraft['signal'] =
    low.includes('бычий') ? 'long' : low.includes('медвеж') ? 'short' : low.includes('нейтрал') ? 'neutral' : 'neutral'

  const confidence = Number((content.match(/Уверенность:\s*([0-9]{1,3})%/i)?.[1] ?? '0'))
  const entry =
    parseNumber(content.match(/(?:Вход|Entry)\s*[:\-]\s*([0-9][0-9., ]*)/i)?.[1]) ??
    parseNumber(content.match(/close[:\s]+([0-9][0-9., ]*)/i)?.[1])
  const stopLoss = parseNumber(content.match(/Стоп-лосс:\s*([0-9][0-9., ]*)/i)?.[1])
  const takeProfit = parseNumber(content.match(/Тейк-профит:\s*([0-9][0-9., ]*)/i)?.[1])
  const timeframe = content.match(/Таймфрейм(?: анализа)?:\s*([A-Za-z0-9/]+)/i)?.[1] ?? '4H'
  const signalTimestamp = content.match(/Сигнал сгенерирован:\s*([0-9\-:\s]+UTC)/i)?.[1]?.trim() ?? null
  const asset = content.match(/\b([A-Z]{2,6}\/[A-Z]{2,6})\b/)?.[1] ?? 'BTC/USDT'

  if (!content.match(/(Бычий|Медвежий|Нейтральный)/i)) return null
  if (entry === null || stopLoss === null || takeProfit === null) return null

  return {
    signal,
    confidence: Math.max(0, Math.min(100, confidence || 0)),
    entryPrice: entry,
    stopLoss,
    takeProfit,
    asset,
    timeframe,
    signalTimestamp,
  }
}

export function canOpenTradeFromMessage(message: ChatMessage, agent?: Agent): boolean {
  if (message.senderType !== 'agent') return false
  const role = agent?.role ?? message.agentSnapshot?.role
  const isCryptoByRole = role ? CRYPTO_ROLES.has(role) : false
  const isCryptoByName = /technical analyst|on-chain analyst|sentiment analyst|risk manager/i.test(
    agent?.name ?? message.agentSnapshot?.name ?? ''
  )
  if (!isCryptoByRole && !isCryptoByName) return false
  return parseTradeDraftFromContent(message.content) !== null
}
