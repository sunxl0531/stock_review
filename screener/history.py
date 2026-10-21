"""Tencent daily bars, explicit two-call refresh with no automatic fallback."""
from datetime import date, timedelta
import requests
from .provider import code, day, normalize_history
from .core import number

URL = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"

def history_symbol(stock_code, board=None):
    stock_code = code(stock_code)
    prefix = {"沪市主板":"sh", "科创板":"sh", "深市主板":"sz",
              "创业板":"sz", "北交所":"bj"}.get(board)
    if prefix is None:
        if stock_code.startswith("6"):
            prefix = "sh"
        elif stock_code.startswith(("0", "3")):
            prefix = "sz"
        elif stock_code.startswith(("4", "8", "92")):
            prefix = "bj"
        else:
            raise ValueError("无法识别证券市场，请先更新基础资料")
    return prefix + stock_code

def fetch_tencent_history(symbol, end_date, session=None, start_date=None):
    end = date.fromisoformat(end_date).isoformat()
    start = date.fromisoformat(start_date).isoformat() if start_date else (date.fromisoformat(end) - timedelta(days=220)).isoformat()
    if start > end:
        raise ValueError("历史开始日期不能晚于结束日期")
    session = session or requests.Session()
    results = []
    for adjustment in ("qfq", ""):
        try:
            response = session.get(URL, params={"param": f"{symbol},day,{start},{end},640,{adjustment}"},
                                   timeout=(8, 15))
            response.raise_for_status()
            payload = response.json()
        except requests.exceptions.ProxyError as exc:
            raise RuntimeError("腾讯历史接口代理连接失败。请检查本机代理连接，或手动切换历史数据来源；旧缓存已保留。") from exc
        if payload.get("code") != 0:
            raise ValueError("腾讯历史接口返回错误，未替换缓存")
        data = payload.get("data", {}).get(symbol, {})
        bars = data.get("qfqday", data.get("day", [])) if adjustment else data.get("day", [])
        if not isinstance(bars, list) or not bars:
            raise ValueError(f"腾讯未返回 {symbol} 的{'前复权' if adjustment else '未复权'}日线，可手动切换历史来源")
        records = []
        for bar in bars:
            if not isinstance(bar, list) or len(bar) < 6 or day(bar[0]) is None:
                raise ValueError("腾讯历史字段格式变化，未替换缓存")
            # This endpoint can ignore the requested range and return 640 bars.
            # Filter both responses locally to avoid mixing later dates into an old snapshot.
            if not start <= bar[0] <= end:
                continue
            volume = number(bar[5])
            # For STAR the endpoint reports shares; other A-share boards report lots.
            # Keep the application's common unit of lots (100 shares).
            if volume is not None and symbol.startswith("sh688"):
                volume /= 100
            records.append({"日期": bar[0], "开盘": bar[1], "收盘": bar[2], "最高": bar[3], "最低": bar[4], "成交量": volume})
        if not records:
            raise ValueError("指定日期范围内无历史数据，未替换缓存")
        results.append(records)
    return normalize_history(*results) | {"source": "腾讯历史日线", "http_requests": 2}
