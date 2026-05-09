/**
 * Полная переустановка пакета `next` и бинарников `@next/swc-*`.
 * Нужна при ошибках: Can't resolve './report-global-error', TAR_ENTRY_ERROR, обрыв установки.
 */
import fs from 'node:fs'
import path from 'node:path'
import { execSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), '..')
const nm = path.join(root, 'node_modules')
const pkg = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8'))
const nextVer = pkg.dependencies?.next ?? pkg.devDependencies?.next ?? '16.2.6'

console.warn(
  '[repair-next] Перед стартом: закрой dev-сервер (npm run dev), другие терминалы в этом каталоге; антивирус может сильно замедлять удаление node_modules.'
)

execSync('node ./scripts/clean-next.mjs', { cwd: root, stdio: 'inherit' })
execSync('node ./scripts/clean-swc-cache.mjs', { cwd: root, stdio: 'inherit' })

/** На Windows fs.rmSync по node_modules/next может «висеть» минутами без вывода — быстрее rd /s /q. */
function rmTreeFast(target, label) {
  if (!fs.existsSync(target)) {
    console.warn(`[repair-next] ${label}: каталога нет, пропуск`)
    return
  }
  const t0 = Date.now()
  const abs = path.resolve(target)
  if (process.platform === 'win32') {
    try {
      execSync(`cmd /c if exist "${abs}" rd /s /q "${abs}"`, { stdio: 'inherit' })
    } catch {
      // rd иногда падает на залоченных файлах
    }
  }
  if (fs.existsSync(target)) {
    console.warn(`[repair-next] ${label}: добиваю остатки через fs.rmSync (может занять время)…`)
    fs.rmSync(target, { recursive: true, force: true })
  }
  console.warn(`[repair-next] ${label}: готово за ${((Date.now() - t0) / 1000).toFixed(1)}s`)
}

console.warn('[repair-next] удаляю node_modules/next …')
rmTreeFast(path.join(nm, 'next'), 'next')

const nextScoped = path.join(nm, '@next')
if (fs.existsSync(nextScoped)) {
  for (const name of fs.readdirSync(nextScoped)) {
    if (name.startsWith('swc-')) {
      console.warn(`[repair-next] удаляю @next/${name} …`)
      rmTreeFast(path.join(nextScoped, name), `@next/${name}`)
    }
  }
}

console.warn(`[repair-next] npm install next@${nextVer} (может занять несколько минут, вывод npm может быть скудным)…`)
execSync(`npm install next@${nextVer} --no-fund --no-audit`, {
  cwd: root,
  stdio: 'inherit',
})

/** Точная версия для SWC и имени .tgz (при next в package.json как ^16.2.6 иначе ломается npm pack). */
let resolvedSwcVer = nextVer
try {
  const nextPkgPath = path.join(nm, 'next', 'package.json')
  if (fs.existsSync(nextPkgPath)) {
    resolvedSwcVer = JSON.parse(fs.readFileSync(nextPkgPath, 'utf8')).version
    console.warn(`[repair-next] разрешённая версия next (SWC): ${resolvedSwcVer}`)
  }
} catch {
  const m = String(nextVer).match(/\d+\.\d+\.\d+/)
  if (m) resolvedSwcVer = m[0]
}

/** Нативный SWC часто не попадает в дерево (omit optional / баг npm tar на Windows) — без .node Next уходит в WASM. */
if (process.platform === 'win32' && process.arch === 'x64') {
  console.warn(`[repair-next] npm install @next/swc-win32-x64-msvc@${resolvedSwcVer} …`)
  execSync(`npm install @next/swc-win32-x64-msvc@${resolvedSwcVer} --no-fund --no-audit`, {
    cwd: root,
    stdio: 'inherit',
  })
  const swcDir = path.join(nm, '@next', 'swc-win32-x64-msvc')
  const nodeFile = path.join(swcDir, 'next-swc.win32-x64-msvc.node')

  if (!fs.existsSync(nodeFile)) {
    const tgzName = `next-swc-win32-x64-msvc-${resolvedSwcVer}.tgz`
    const tgzPath = path.join(root, tgzName)
    const extractRoot = path.join(root, '_swc_extract_tmp')
    console.warn(`[repair-next] нет ${path.basename(nodeFile)} после npm — пробуем npm pack + tar`)
    try {
      if (fs.existsSync(tgzPath)) fs.unlinkSync(tgzPath)
      fs.rmSync(extractRoot, { recursive: true, force: true })
      execSync(`npm pack @next/swc-win32-x64-msvc@${resolvedSwcVer}`, { cwd: root, stdio: 'inherit' })
      if (!fs.existsSync(tgzPath)) {
        throw new Error(`не создан архив ${tgzName}`)
      }
      fs.mkdirSync(extractRoot, { recursive: true })
      execSync(`tar -xzf "${tgzPath}"`, { cwd: extractRoot, stdio: 'inherit' })
      const packedNode = path.join(extractRoot, 'package', 'next-swc.win32-x64-msvc.node')
      if (!fs.existsSync(packedNode)) {
        throw new Error('в .tgz нет next-swc.win32-x64-msvc.node')
      }
      fs.mkdirSync(swcDir, { recursive: true })
      fs.copyFileSync(packedNode, nodeFile)
      fs.rmSync(extractRoot, { recursive: true, force: true })
      fs.unlinkSync(tgzPath)
      console.warn('[repair-next] нативный SWC восстановлен через npm pack + tar')
    } catch (err) {
      console.error('[repair-next] не удалось восстановить SWC:', err)
      process.exitCode = 1
    }
  }
}
