"""Normalize sources; run blocking market SDKs in a bounded worker process."""
from datetime import datetime
from pathlib import Path
import json
import os
import re
import subprocess
import sys
from .core import number

def code(value):
    text = str(value).strip().split(".")[0].zfill(6)
    if not re.fullmatch(r"\d{6}", text):
        raise ValueError("证券代码格式错误")
    return text

def day(value):
    text = str(value)[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d").date().isoformat()
    except ValueError:
        return None

def normalize_quotes(records):
    return [{"code": code(r["代码"]), "name": r.get("名称"), "price": number(r.get("最新价")),
             "change_pct": number(r.get("涨跌幅")), "volume_ratio": number(r.get("量比")),
             "amount": number(r.get("成交额")), "quote_date": None, "quote_time": None}
            for r in records]

def normalize_directory(records, board):
    result = []
    for r in records:
        shenzhen = board == "深圳"
        industry = r.get("所属行业")
        industry = industry.strip() if isinstance(industry, str) else None
        if industry in ("", "-", "nan"):
            industry = None
        result.append({"code": code(r["A股代码" if shenzhen else "证券代码"]),
                       "name": r.get("A股简称" if shenzhen else "证券简称"),
                       "listed": day(r.get("A股上市日期" if shenzhen else "上市日期")),
                       "board": ({"主板":"深市主板", "创业板":"创业板"}.get(r.get("板块")) if shenzhen else board),
                       "industry":industry})
    return result

def normalize_history(adjusted, raw):
    mapping = {"日期":"date", "开盘":"open", "最高":"high", "最低":"low", "收盘":"close", "成交量":"volume"}
    bars = sorted([{v: day(r.get(k)) if v == "date" else number(r.get(k)) for k, v in mapping.items()} for r in adjusted], key=lambda b: b["date"] or "")
    raw = sorted(raw, key=lambda r: str(r.get("日期", "")))
    comparable = False
    basis = bars[-1]["date"] if bars else None
    if bars and raw:
        last = next((r for r in reversed(raw) if day(r.get("日期")) == basis), None)
    else:
        last = None
    if last:
        close = number(last.get("收盘"))
        comparable = (close is not None and bars[-1]["close"] is not None
                      and abs(close - bars[-1]["close"]) <= 0.011)
    return {"bars": bars, "basis_date": basis, "comparable": comparable, "adjustment": "qfq"}

def parse_tencent(text):
    rows = []
    for content in re.findall(r'="([^"]*)"', text):
        f = content.split("~")
        if len(f) < 50 or not re.fullmatch(r"\d{6}", f[2]):
            continue
        try:
            stamp = datetime.strptime(f[30], "%Y%m%d%H%M%S")
        except ValueError:
            stamp = None
        amount = number(f[37])
        rows.append({"code": code(f[2]), "name": f[1], "price": number(f[3]), "change_pct": number(f[32]),
                     "volume_ratio": number(f[49]), "amount": amount * 10000 if amount is not None else None,
                     "quote_date": stamp.date().isoformat() if stamp else None,
                     "quote_time": stamp.isoformat(sep=" ") if stamp else None})
    return rows

def parse_tencent_daily_quotes(text):
    """Parse OHLC from Tencent's multi-symbol spot response for daily pre-screening."""
    rows = []
    for content in re.findall(r'="([^"]*)"', text):
        f = content.split("~")
        if len(f) < 38 or not re.fullmatch(r"\d{6}", f[2]):
            continue
        try:
            stamp = datetime.strptime(f[30], "%Y%m%d%H%M%S")
        except ValueError:
            continue
        values = {key:number(f[i]) for key,i in (("close",3),("previous_close",4),
                   ("open",5),("volume",6),("high",33),("low",34))}
        if any(v is None for v in values.values()):
            continue
        if values["volume"] <= 0:
            # Suspended quotes may retain a close but report zero OHLC.
            # They cannot form a daily candle; let the per-stock history path decide.
            continue
        rows.append({"code":code(f[2]), "date":stamp.date().isoformat(),
                     "quote_time":stamp.isoformat(sep=" "), **values})
    return rows

class Provider:
    def call(self, operation, **kwargs):
        root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            completed = subprocess.run([sys.executable, "-m", "screener.worker"],
                input=json.dumps({"operation": operation, "kwargs": kwargs}), capture_output=True,
                encoding="utf-8", errors="replace", cwd=root, env=env, timeout=90,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("请求超过90秒已停止，保留旧数据。可稍后手动重试。") from exc
        lines = [line for line in completed.stdout.splitlines() if line.startswith("__RESULT__")]
        if not lines:
            raise RuntimeError("数据进程未返回结果：" + completed.stderr[-300:])
        payload = json.loads(lines[-1][10:])
        if "error" in payload:
            raise RuntimeError(payload["error"])
        return payload["data"]
