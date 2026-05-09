import type { Agent } from '@/lib/types'

function normalize(text: string): string {
  return text.toLowerCase().replace(/[^a-z0-9]+/g, '')
}

/** Совместимо с логикой бэкенда: имя / часть имени / роль. */
export function extractMentionedAgentIds(text: string, agents: Agent[]): string[] {
  const ids: string[] = []
  const seen = new Set<string>()
  const re = /@([A-Za-z][A-Za-z0-9_\- ]*)/g
  let m: RegExpExecArray | null
  while ((m = re.exec(text)) !== null) {
    const token = m[1].trim()
    const nt = normalize(token)
    if (!nt) continue
    for (const a of agents) {
      const nname = normalize(a.name)
      const nrole = normalize(a.role)
      const nameMatch =
        nname === nt || nname.startsWith(nt) || nt.length >= 2 && nname.includes(nt)
      const roleMatch = nrole === nt
      if (nameMatch || roleMatch) {
        if (!seen.has(a.id)) {
          ids.push(a.id)
          seen.add(a.id)
        }
        break
      }
    }
  }
  return ids
}
