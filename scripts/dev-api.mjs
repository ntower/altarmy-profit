// Start the Python API for `npm run dev` using the project venv's interpreter (Windows or POSIX layout).
// `--hosted` (npm run dev:hosted) loads hosted.env: hosted mode, signed in with the real Firebase project.
import { spawn } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const python = [join(root, '.venv', 'Scripts', 'python.exe'), join(root, '.venv', 'bin', 'python')].find(existsSync)
if (!python) {
  console.error('No .venv found: python -m venv .venv, then .venv\Scripts\python -m pip install -e ".[dev,ui]"')
  process.exit(1)
}

/** KEY=VALUE lines of an env file; blank lines and # comments are skipped. */
function readEnvFile(path) {
  const env = {}
  for (const line of readFileSync(path, 'utf8').split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$/)
    if (m) env[m[1]] = m[2]
  }
  return env
}

const args = process.argv.slice(2)
const hosted = args.includes('--hosted')
const env = hosted ? { ...process.env, ...readEnvFile(join(root, 'hosted.env')) } : process.env
const child = spawn(python, ['-m', 'altarmy_profit.cli', 'ui', '--no-browser', ...args.filter((a) => a !== '--hosted')], {
  cwd: root,
  stdio: 'inherit',
  env,
})
child.on('exit', (code) => process.exit(code ?? 0))
