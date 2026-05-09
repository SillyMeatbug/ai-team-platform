/**
 * Удаляет кэш загрузок SWC (%LOCALAPPDATA%/next-swc на Windows).
 * Помогает при зависании на «Downloading swc package @next/swc-wasm-nodejs…».
 */
import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'

const localAppData = process.env.LOCALAPPDATA
const dir = localAppData
  ? path.join(localAppData, 'next-swc')
  : path.join(os.homedir(), 'AppData', 'Local', 'next-swc')

try {
  fs.rmSync(dir, { recursive: true, force: true })
  console.warn(`[clean-swc-cache] removed ${dir}`)
} catch (err) {
  if (err && typeof err === 'object' && 'code' in err && err.code !== 'ENOENT') throw err
}
