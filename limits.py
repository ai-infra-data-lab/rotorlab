"""Shared server/browser capacity settings; restart the server after changing JSON."""
import json
from pathlib import Path

LIMITS = json.loads(Path(__file__).with_name("limits.json").read_text(encoding="utf-8"))
if any(isinstance(v, bool) or not isinstance(v, int) or v < 1 for v in LIMITS.values()):
    raise ValueError("limits.json: capacities must be positive integers")
