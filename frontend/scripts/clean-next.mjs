import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..')
const nextDir = path.join(root, '.next')

try {
  fs.rmSync(nextDir, { recursive: true, force: true })
  console.warn('[clean-next] removed .next')
} catch (err) {
  if (err && typeof err === 'object' && 'code' in err && err.code !== 'ENOENT') throw err
}
