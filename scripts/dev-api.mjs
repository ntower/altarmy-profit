// Start the Python API for `npm run dev` using the project venv's interpreter (Windows or POSIX layout).
import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const python = [join(root, '.venv', 'Scripts', 'python.exe'), join(root, '.venv', 'bin', 'python')].find(existsSync)
if (!python) {
  console.error('No .venv found: python -m venv .venv, then .venv\\Scripts\\python -m pip install -e ".[dev,ui]"')
  process.exit(1)
}

const child = spawn(python, ['-m', 'wowprofit.cli', 'ui', '--no-browser', ...process.argv.slice(2)], {
  cwd: root,
  stdio: 'inherit',
})
child.on('exit', (code) => process.exit(code ?? 0))
