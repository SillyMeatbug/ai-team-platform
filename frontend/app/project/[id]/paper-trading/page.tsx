'use client'

import { use, useCallback, useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { ArrowLeft, RefreshCw, Download, Link2, Inbox } from 'lucide-react'
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Tooltip as UiTooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { ProjectTabs } from '@/components/project-tabs'
import {
  closeProjectPaperTrade,
  getProject,
  getProjectAgents,
  getProjectPaperTrades,
  reconcileProjectPaperTrades,
} from '@/lib/api'
import type { Agent, PaperTrade, PaperTradeStatus } from '@/lib/types'

const PAGE_SIZE = 50

function fmtPct(v: number | null) {
  if (v === null) return '—'
  const sign = v > 0 ? '+' : ''
  return `${sign}${v.toFixed(2)}%`
}

export default function PaperTradingPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const router = useRouter()
  const [loading, setLoading] = useState(true)
  const [projectName, setProjectName] = useState('')
  const [isCryptoEnabled, setIsCryptoEnabled] = useState(false)
  const [agents, setAgents] = useState<Agent[]>([])
  const [trades, setTrades] = useState<PaperTrade[]>([])
  const [status, setStatus] = useState<'all' | PaperTradeStatus>('all')
  const [asset, setAsset] = useState('all')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [page, setPage] = useState(1)
  const [isReconciling, setIsReconciling] = useState(false)
  const [metricHintOpen, setMetricHintOpen] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [project, team, rows] = await Promise.all([
        getProject(id),
        getProjectAgents(id),
        getProjectPaperTrades(id),
      ])
      setProjectName(project.name)
      setIsCryptoEnabled(project.isCryptoEnabled)
      if (!project.isCryptoEnabled) {
        router.replace(`/project/${id}`)
        return
      }
      setAgents(team)
      setTrades(rows)
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setLoading(false)
    }
  }, [id, router])

  useEffect(() => {
    void load()
  }, [load])

  const assets = useMemo(() => Array.from(new Set(trades.map((x) => x.asset))), [trades])

  const filtered = useMemo(() => {
    return trades.filter((tr) => {
      if (status !== 'all' && tr.status !== status) return false
      if (asset !== 'all' && tr.asset !== asset) return false
      if (from && new Date(tr.openedAt) < new Date(from)) return false
      if (to && new Date(tr.openedAt) > new Date(`${to}T23:59:59`)) return false
      return true
    })
  }, [asset, from, status, to, trades])

  const paged = useMemo(() => {
    const start = (page - 1) * PAGE_SIZE
    return filtered.slice(start, start + PAGE_SIZE)
  }, [filtered, page])
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))

  const metrics = useMemo(() => {
    const closed = filtered.filter((x) => x.status !== 'open' && x.pnlPct !== null)
    const profitable = closed.filter((x) => (x.pnlPct ?? 0) > 0)
    const winRate = closed.length ? (profitable.length / closed.length) * 100 : 0
    const totalPnl = closed.reduce((acc, x) => acc + (x.pnlPct ?? 0), 0)
    const rrValues = filtered
      .map((x) => {
        if (x.stopLoss === null || x.takeProfit === null) return null
        const risk = Math.abs(x.entryPrice - x.stopLoss)
        const reward = Math.abs(x.takeProfit - x.entryPrice)
        if (risk === 0) return null
        return reward / risk
      })
      .filter((x): x is number => x !== null)
    const avgRR = rrValues.length ? rrValues.reduce((a, b) => a + b, 0) / rrValues.length : 0

    let peak = 0
    let equity = 0
    let maxDd = 0
    for (const x of closed.sort((a, b) => +new Date(a.closedAt || a.openedAt) - +new Date(b.closedAt || b.openedAt))) {
      equity += x.pnlPct ?? 0
      peak = Math.max(peak, equity)
      maxDd = Math.max(maxDd, peak - equity)
    }
    return { winRate, totalPnl, avgRR, maxDd }
  }, [filtered])

  const statusOptions: Array<'all' | PaperTradeStatus> = ['all', 'open', 'closed', 'stopped', 'expired']

  const pnlSeries = useMemo(() => {
    let cumulative = 0
    return filtered
      .filter((x) => x.closedAt && x.pnlPct !== null)
      .sort((a, b) => +new Date(a.closedAt || '') - +new Date(b.closedAt || ''))
      .map((x) => {
        cumulative += x.pnlPct ?? 0
        return {
          ts: new Date(x.closedAt || '').toLocaleDateString(),
          cumPnl: Number(cumulative.toFixed(2)),
          asset: x.asset,
          pnl: x.pnlPct ?? 0,
        }
      })
  }, [filtered])

  const onReconcile = useCallback(async () => {
    setIsReconciling(true)
    try {
      const res = await reconcileProjectPaperTrades(id)
      toast.success(`Проверено ${res.updated} сделок`)
      await load()
    } catch (e) {
      toast.error((e as Error).message)
    } finally {
      setIsReconciling(false)
    }
  }, [id, load])

  const onExportCsv = useCallback(() => {
    const headers = ['signal_timestamp', 'opened_at', 'asset', 'timeframe', 'signal', 'entry_price', 'exit_price', 'pnl_pct', 'status']
    const rows = filtered.map((x) => [
      x.signalTimestamp,
      x.openedAt,
      x.asset,
      x.timeframe,
      x.signal,
      String(x.entryPrice),
      x.exitPrice === null ? '' : String(x.exitPrice),
      x.pnlPct === null ? '' : String(x.pnlPct),
      x.status,
    ])
    const csv = [headers, ...rows].map((r) => r.join(',')).join('\n')
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `paper-trades-${id}.csv`
    a.click()
    URL.revokeObjectURL(url)
  }, [filtered, id])

  const closeManually = useCallback(async (trade: PaperTrade) => {
    const raw = window.prompt('Цена закрытия (exit price):')
    if (!raw) return
    const exitPrice = Number(raw.replace(',', '.'))
    if (!Number.isFinite(exitPrice) || exitPrice <= 0) {
      toast.error('Некорректная цена')
      return
    }
    try {
      await closeProjectPaperTrade(id, trade.id, exitPrice)
      toast.success('Сделка закрыта')
      await load()
    } catch (e) {
      toast.error((e as Error).message)
    }
  }, [id, load])

  return (
    <div className="min-h-screen bg-background">
      <header className="border-b border-border">
        <div className="mx-auto max-w-6xl px-4 py-3 sm:px-6 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Button variant="ghost" size="icon" asChild>
              <Link href={`/project/${id}`}>
                <ArrowLeft className="h-4 w-4" />
              </Link>
            </Button>
            {loading ? <Skeleton className="h-6 w-48" /> : <h1 className="text-lg font-semibold">{projectName}</h1>}
          </div>
        </div>
        <ProjectTabs
          activeTab="paper-trading"
          onChange={() => undefined}
          projectId={id}
          isCryptoEnabled={isCryptoEnabled}
        />
      </header>

      <main className="mx-auto max-w-6xl px-4 py-4 sm:px-6 space-y-4">
        <Card className="rounded-xl border border-white/10 bg-white/5 p-3">
          <div className="flex items-center justify-end gap-2">
            <Button variant="outline" size="sm" onClick={() => void onReconcile()} disabled={isReconciling}>
              <RefreshCw className={`h-4 w-4 mr-2 ${isReconciling ? 'animate-spin' : ''}`} /> Reconcile
            </Button>
            <Button variant="outline" size="sm" onClick={onExportCsv}>
              <Download className="h-4 w-4 mr-2" /> CSV
            </Button>
          </div>
        </Card>

        <TooltipProvider delayDuration={300}>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {[
              { key: 'win', label: 'Win Rate', value: `${metrics.winRate.toFixed(2)}%`, formula: 'profit_trades / closed_trades * 100', cls: 'text-foreground' },
              { key: 'rr', label: 'Avg R:R', value: metrics.avgRR.toFixed(2), formula: 'avg(|TP-Entry| / |Entry-SL|)', cls: 'text-foreground' },
              { key: 'pnl', label: 'Total PnL', value: fmtPct(metrics.totalPnl), formula: 'sum(pnl_pct) over closed trades', cls: metrics.totalPnl >= 0 ? 'text-emerald-300' : 'text-red-300' },
              { key: 'dd', label: 'Max Drawdown', value: `${metrics.maxDd.toFixed(2)}%`, formula: 'max(peak_equity - current_equity)', cls: 'text-amber-300' },
            ].map((m) => (
              <UiTooltip key={m.key}>
                <TooltipTrigger asChild>
                  <Card
                    className="rounded-xl border border-white/10 bg-white/5 p-4 cursor-default"
                    onClick={() => setMetricHintOpen((prev) => (prev === m.key ? null : m.key))}
                  >
                    <div className="text-xs text-muted-foreground">{m.label}</div>
                    <div className={`mt-1 text-2xl font-semibold tracking-tight ${m.cls}`}>{m.value}</div>
                    {metricHintOpen === m.key && (
                      <div className="mt-2 rounded-md border border-white/10 bg-black/30 px-2 py-1 text-[11px] font-mono text-muted-foreground sm:hidden">
                        {m.formula}
                      </div>
                    )}
                  </Card>
                </TooltipTrigger>
                <TooltipContent className="border border-white/10 bg-[#141414] text-xs text-slate-200">
                  <span className="font-mono">{m.formula}</span>
                </TooltipContent>
              </UiTooltip>
            ))}
          </div>
        </TooltipProvider>

        <Card className="rounded-xl border border-white/10 bg-white/5 p-4">
          <div className="mb-2 text-sm font-medium">PnL over time</div>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={pnlSeries}>
                <CartesianGrid strokeDasharray="3 3" stroke="#333" />
                <XAxis dataKey="ts" />
                <YAxis />
                <Tooltip
                  contentStyle={{ background: '#121212', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 12 }}
                  labelStyle={{ color: '#a3a3a3' }}
                  itemStyle={{ color: '#e5e5e5', fontFamily: 'JetBrains Mono, monospace' }}
                  formatter={(v, n) => [String(v), n === 'cumPnl' ? 'Cum PnL %' : 'PnL %']}
                  labelFormatter={(_, payload) => `Asset: ${payload?.[0]?.payload?.asset ?? ''}`}
                />
                <Area dataKey="cumPnl" stroke="#22c55e" fill="#22c55e33" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </Card>

        <Card className="rounded-xl border border-white/10 bg-white/5 p-4">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            {statusOptions.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => setStatus(s)}
                className={`rounded-full px-3 py-1 text-xs transition-colors ${
                  status === s ? 'bg-purple-500/20 text-purple-300 border border-purple-400/30' : 'bg-white/5 text-muted-foreground border border-white/10 hover:bg-white/10'
                }`}
              >
                {s}
              </button>
            ))}
            <div className="h-5 w-px bg-white/10 mx-1" />
            <button
              type="button"
              onClick={() => setAsset('all')}
              className={`rounded-full px-3 py-1 text-xs transition-colors ${
                asset === 'all' ? 'bg-purple-500/20 text-purple-300 border border-purple-400/30' : 'bg-white/5 text-muted-foreground border border-white/10'
              }`}
            >
              all assets
            </button>
            {assets.map((a) => (
              <button
                key={a}
                type="button"
                onClick={() => setAsset(a)}
                className={`rounded-full px-3 py-1 text-xs transition-colors ${
                  asset === a ? 'bg-purple-500/20 text-purple-300 border border-purple-400/30' : 'bg-white/5 text-muted-foreground border border-white/10'
                }`}
              >
                {a}
              </button>
            ))}
            <div className="ml-auto flex items-center gap-2">
              <input className="h-8 rounded-md border border-white/10 bg-black/20 px-2 text-xs" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
              <input className="h-8 rounded-md border border-white/10 bg-black/20 px-2 text-xs" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
            </div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted-foreground border-b border-white/10">
                  <th className="sticky left-0 bg-background/95 py-2 pr-3">🕐 Сигнал</th><th className="py-2 pr-3">⏰ Вход</th><th className="py-2 pr-3">Актив</th><th className="py-2 pr-3">Направление</th><th className="py-2 pr-3">Вход/Выход/PnL</th><th className="py-2 pr-3">Статус</th><th className="py-2 pr-3">Связь</th><th />
                </tr>
              </thead>
              <tbody>
                {paged.map((tr) => {
                  const agentName = agents.find((a) => a.id === tr.agentId)?.name ?? tr.agentId
                  return (
                    <tr key={tr.id} className="border-b border-white/10 hover:bg-white/5 animate-in fade-in slide-in-from-bottom-2 duration-300">
                      <td className="sticky left-0 bg-background/95 py-2 pr-3 whitespace-nowrap">{new Date(tr.signalTimestamp).toLocaleString()}</td>
                      <td className="py-2 pr-3 whitespace-nowrap">{new Date(tr.openedAt).toLocaleString()}</td>
                      <td className="py-2 pr-3 whitespace-nowrap">{tr.asset} · {tr.timeframe}<div className="text-xs text-muted-foreground">{agentName}</div></td>
                      <td className="py-2 pr-3 whitespace-nowrap">{tr.signal === 'long' ? '🟢 Long' : tr.signal === 'short' ? '🔴 Short' : '⚪ Neutral'}</td>
                      <td className="py-2 pr-3 whitespace-nowrap">{tr.entryPrice} / {tr.exitPrice ?? '—'} / <span className={(tr.pnlPct ?? 0) >= 0 ? 'text-emerald-400' : 'text-red-400'}>{fmtPct(tr.pnlPct)}</span></td>
                      <td className="py-2 pr-3">
                        <span className={`rounded-full px-2.5 py-1 text-xs ${
                          tr.status === 'open'
                            ? 'bg-yellow-500/20 text-yellow-300'
                            : tr.status === 'closed'
                              ? 'bg-emerald-500/20 text-emerald-300'
                              : tr.status === 'stopped'
                                ? 'bg-red-500/20 text-red-300'
                                : 'bg-slate-500/20 text-slate-300'
                        }`}
                        >
                          {tr.status}
                        </span>
                      </td>
                      <td className="py-2 pr-3">
                        {tr.messageId ? (
                          <Button size="sm" variant="ghost" className="h-7 px-2 text-xs" asChild>
                            <Link href={`/project/${id}?focus_message_id=${encodeURIComponent(tr.messageId)}`}>
                              <Link2 className="h-3.5 w-3.5 mr-1" /> Сообщение
                            </Link>
                          </Button>
                        ) : <span className="text-xs text-muted-foreground">—</span>}
                      </td>
                      <td className="py-2 pr-3">{tr.status === 'open' ? <Button size="sm" variant="outline" onClick={() => void closeManually(tr)}>Закрыть вручную</Button> : null}</td>
                    </tr>
                  )
                })}
                {!loading && filtered.length === 0 && (
                  <tr>
                    <td colSpan={8} className="py-10 text-center text-muted-foreground">
                      <div className="flex flex-col items-center gap-2">
                        <Inbox className="h-6 w-6" />
                        <div>Отправьте запрос крипто-агенту, чтобы открыть первую сделку</div>
                      </div>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="mt-3 flex items-center justify-end gap-2">
              <Button size="sm" variant="outline" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Prev</Button>
              <span className="text-xs text-muted-foreground">{page}/{totalPages}</span>
              <Button size="sm" variant="outline" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>Next</Button>
            </div>
          )}
        </Card>
      </main>
    </div>
  )
}
