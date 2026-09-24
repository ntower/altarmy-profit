"""Run lint, format check, type check and tests for the Python package and the front end.

Usage: python scripts/check.py [--skip-frontend]

The front-end steps regenerate frontend/openapi.json and src/api/schema.d.ts from the API first, so
the TypeScript build always checks against the current API. They need `npm ci` in frontend/ once.
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"

python_steps: list[tuple[str, list[str], Path]] = [
    ("ruff lint", [sys.executable, "-m", "ruff", "check", "."], ROOT),
    ("ruff format", [sys.executable, "-m", "ruff", "format", "--check", "."], ROOT),
    ("mypy", [sys.executable, "-m", "mypy"], ROOT),
    ("pytest", [sys.executable, "-m", "pytest", "-q"], ROOT),
]


def frontend_steps() -> list[tuple[str, list[str], Path]]:
    # On Windows npm is npm.cmd; a bare "npm" argv fails without shell=True, so resolve the real path.
    npm = shutil.which("npm")
    if npm is None:
        sys.exit("npm not found: install Node.js, or pass --skip-frontend")
    if not (FRONTEND / "node_modules").is_dir():
        sys.exit("frontend/node_modules missing: run `npm ci` in frontend/, or pass --skip-frontend")
    return [
        ("openapi export", [sys.executable, str(ROOT / "scripts" / "export_openapi.py")], ROOT),
        ("gen-types", [npm, "run", "gen-types"], FRONTEND),
        ("oxlint", [npm, "run", "lint"], FRONTEND),
        ("vitest", [npm, "test"], FRONTEND),
        ("tsc + vite build", [npm, "run", "build"], FRONTEND),
    ]


steps = python_steps if "--skip-frontend" in sys.argv[1:] else python_steps + frontend_steps()
failed = []
for name, cmd, cwd in steps:
    print(f"\n== {name}", flush=True)
    if subprocess.run(cmd, cwd=cwd).returncode != 0:
        failed.append(name)

print("\nFAILED: " + ", ".join(failed) if failed else "\nAll checks passed.")
sys.exit(1 if failed else 0)
