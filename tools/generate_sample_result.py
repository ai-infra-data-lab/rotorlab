"""Generate the fictional sample's numerical results for the JS smoke check."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine import analyze
from model import sample_model


def main():
    out = ROOT / "artifacts" / "sample-result.json"
    result = analyze(sample_model())
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    print("Generated artifacts/sample-result.json (fictional model)")


if __name__ == "__main__":
    main()
