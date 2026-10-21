"""Small explicit network check; never called on app startup."""
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from screener.provider import Provider

p = Provider()
for operation, kwargs in [("quotes_tencent", {"symbols": ["sh600000", "sz000001", "sz300750", "sh688001", "bj920001"]}),
                           ("directory", {"board": "沪市主板"}), ("calendar", {})]:
    try:
        result = p.call(operation, **kwargs)
        summary = {"operation": operation, "count": len(result.get("rows", result.get("days", []))),
                   "sample": result.get("rows", result.get("days", []))[:1]}
        print(json.dumps(summary, ensure_ascii=True), flush=True)
    except Exception as exc:
        print(json.dumps({"operation": operation, "error": str(exc)}, ensure_ascii=True), flush=True)
