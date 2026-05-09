'use client'

import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from 'react'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import type { Agent } from '@/lib/types'

function normToken(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, '')
}

/** Фрагмент @query непрерывный до каретки (без пробелов / перевода строки). */
export function getActiveMention(text: string, caret: number): { start: number; query: string } | null {
  const before = text.slice(0, caret)
  const at = before.lastIndexOf('@')
  if (at === -1) return null
  const afterAt = before.slice(at + 1)
  if (/\s/.test(afterAt)) return null
  return { start: at, query: afterAt }
}

function filterProjectAgents(agents: Agent[], query: string): Agent[] {
  const sorted = [...agents].sort((a, b) => a.name.localeCompare(b.name))
  const raw = query.trim()
  if (!raw) return sorted
  const ql = raw.toLowerCase()
  const qn = normToken(raw)
  return sorted.filter((a) => {
    const name = a.name.toLowerCase()
    const nname = normToken(a.name)
    const nrole = normToken(a.role)
    return (
      name.includes(ql) ||
      (qn.length > 0 && (nname.includes(qn) || nrole.includes(qn) || nrole.startsWith(qn)))
    )
  })
}

export type ChatMentionTextareaHandle = {
  insertAtSign: () => void
  focus: () => void
}

type ChatMentionTextareaProps = {
  value: string
  onChange: (next: string) => void
  agents: Agent[]
  disabled?: boolean
  placeholder?: string
  textareaClassName?: string
  onSubmit: () => void
  labels: {
    noMatches: string
    listLabel: string
  }
}

export const ChatMentionTextarea = forwardRef<ChatMentionTextareaHandle, ChatMentionTextareaProps>(
  function ChatMentionTextarea(
    { value, onChange, agents, disabled, placeholder, textareaClassName, onSubmit, labels },
    ref
  ) {
    const taRef = useRef<HTMLTextAreaElement>(null)
    const [caret, setCaret] = useState(0)
    const [highlight, setHighlight] = useState(0)

    const mentionCtx = useMemo(() => getActiveMention(value, caret), [value, caret])
    const filtered = useMemo(
      () => (mentionCtx ? filterProjectAgents(agents, mentionCtx.query) : []),
      [agents, mentionCtx]
    )

    const listOpen = Boolean(mentionCtx && agents.length > 0)

    useEffect(() => {
      setHighlight(0)
    }, [mentionCtx?.start, mentionCtx?.query])

    useEffect(() => {
      setHighlight((h) => (filtered.length === 0 ? 0 : Math.min(h, filtered.length - 1)))
    }, [filtered.length])

    const pickAgent = useCallback(
      (agent: Agent) => {
        const el = taRef.current
        const ctx = getActiveMention(value, caret)
        if (!ctx || !el) return
        const before = value.slice(0, ctx.start)
        const after = value.slice(caret)
        const ins = `@${agent.name} `
        const next = before + ins + after
        onChange(next)
        const pos = before.length + ins.length
        requestAnimationFrame(() => {
          el.focus()
          el.setSelectionRange(pos, pos)
          setCaret(pos)
        })
      },
      [value, caret, onChange]
    )

    const insertAtSign = useCallback(() => {
      const el = taRef.current
      if (!el || disabled) return
      const start = el.selectionStart ?? value.length
      const end = el.selectionEnd ?? value.length
      const next = value.slice(0, start) + '@' + value.slice(end)
      onChange(next)
      const pos = start + 1
      requestAnimationFrame(() => {
        el.focus()
        el.setSelectionRange(pos, pos)
        setCaret(pos)
      })
    }, [value, onChange, disabled])

    useImperativeHandle(ref, () => ({
      insertAtSign,
      focus: () => taRef.current?.focus(),
    }))

    const onAreaChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      onChange(e.target.value)
      setCaret(e.target.selectionStart ?? 0)
    }

    const onAreaSelect = (e: React.SyntheticEvent<HTMLTextAreaElement>) => {
      setCaret(e.currentTarget.selectionStart ?? 0)
    }

    const onAreaClick = (e: React.MouseEvent<HTMLTextAreaElement>) => {
      setCaret(e.currentTarget.selectionStart ?? 0)
    }

    const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      const ctx = getActiveMention(value, caret)
      const list = ctx ? filterProjectAgents(agents, ctx.query) : []
      const open = Boolean(ctx && agents.length > 0 && list.length > 0)

      if (open) {
        if (e.key === 'ArrowDown') {
          e.preventDefault()
          setHighlight((i) => Math.min(i + 1, list.length - 1))
          return
        }
        if (e.key === 'ArrowUp') {
          e.preventDefault()
          setHighlight((i) => Math.max(i - 1, 0))
          return
        }
        if (e.key === 'Enter' || (e.key === 'Tab' && !e.shiftKey)) {
          e.preventDefault()
          pickAgent(list[highlight]!)
          return
        }
      }

      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        onSubmit()
      }
    }

    return (
      <div className="relative">
        {listOpen && (
          <div
            className="absolute bottom-full left-0 right-0 z-50 mb-2 max-h-48 overflow-y-auto rounded-md border border-border bg-popover shadow-lg"
            role="listbox"
            aria-label={labels.listLabel}
          >
            {filtered.length === 0 ? (
              <div className="px-3 py-2 text-xs text-muted-foreground">{labels.noMatches}</div>
            ) : (
              filtered.map((agent, idx) => (
                <button
                  key={agent.id}
                  type="button"
                  role="option"
                  aria-selected={idx === highlight}
                  className={cn(
                    'flex w-full flex-col items-start gap-0.5 px-3 py-2 text-left text-sm transition-colors',
                    idx === highlight ? 'bg-accent text-accent-foreground' : 'hover:bg-accent/50'
                  )}
                  onMouseDown={(ev) => ev.preventDefault()}
                  onMouseEnter={() => setHighlight(idx)}
                  onClick={() => pickAgent(agent)}
                >
                  <span className="font-medium text-foreground">{agent.name}</span>
                  <span className="font-mono text-xs text-muted-foreground">{agent.model}</span>
                </button>
              ))
            )}
          </div>
        )}
        <Textarea
          ref={taRef}
          value={value}
          onChange={onAreaChange}
          onSelect={onAreaSelect}
          onClick={onAreaClick}
          onKeyUp={onAreaSelect}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          rows={1}
          disabled={disabled}
          className={textareaClassName}
        />
      </div>
    )
  }
)
