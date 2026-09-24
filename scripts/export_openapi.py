"""Write the API's OpenAPI spec to frontend/openapi.json (input for `npm run gen-types`).

Usage: python scripts/export_openapi.py
"""

import json
from pathlib import Path

from altarmy_profit.api import create_app

OUT = Path(__file__).resolve().parents[1] / "frontend" / "openapi.json"

spec = create_app("unused.db", static_dir=None).openapi()
OUT.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(f"wrote {OUT}")
