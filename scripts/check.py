"""Run lint, format check, type check and tests. Usage: python scripts/check.py"""

import subprocess
import sys

STEPS = [
    ("ruff lint", [sys.executable, "-m", "ruff", "check", "."]),
    ("ruff format", [sys.executable, "-m", "ruff", "format", "--check", "."]),
    ("mypy", [sys.executable, "-m", "mypy"]),
    ("pytest", [sys.executable, "-m", "pytest", "-q"]),
]

failed = []
for name, cmd in STEPS:
    print(f"\n== {name}")
    if subprocess.run(cmd).returncode != 0:
        failed.append(name)

print("\nFAILED: " + ", ".join(failed) if failed else "\nAll checks passed.")
sys.exit(1 if failed else 0)
