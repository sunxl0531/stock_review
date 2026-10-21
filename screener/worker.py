"""External requests only. This process can safely be terminated on timeout."""
import json
import sys
from datetime import date, timedelta
from .provider import normalize_quotes, normalize_directory, normalize_history, parse_tencent, parse_tencent_daily_quotes

def install_transport_guard():
    import requests
    # Some SDK functions omit timeout. Bound every requests transport call.
    original_send = requests.sessions.Session.send
    def bounded_send(self, request, **options):
        if options.get("timeout") is None:
            options["timeout"] = (8, 15)
        response = original_send(self, request, **options)
        if response.status_code in (401, 403, 429):
            # SDK retry helpers catch RequestException / ValueError. RuntimeError
            # intentionally escapes that loop so quota errors make one attempt.
            raise RuntimeError(f"HTTP {response.status_code}：接口限流或拒绝访问，已停止请求")
        response.raise_for_status()
        return response
    requests.sessions.Session.send = bounded_send

def execute(operation, **kwargs):
    import requests
    install_transport_guard()
    if operation == "history" and kwargs.get("source", "tencent") == "tencent":
        from .history import fetch_tencent_history, history_symbol
        return fetch_tencent_history(history_symbol(kwargs["code"], kwargs.get("board")), kwargs["date"],
                                     start_date=kwargs.get("start_date"))
    if operation == "quotes_tencent":
        rows, calls = [], 0
        symbols = kwargs["symbols"]
        if not symbols:
            raise ValueError("请先更新基础资料，再刷新腾讯行情")
        session = requests.Session()
        for start in range(0, len(symbols), 80):
            response = session.get("https://qt.gtimg.cn/q=" + ",".join(symbols[start:start+80]), timeout=(8, 15))
            response.raise_for_status()
            response.encoding = "gbk"
            parsed = parse_tencent(response.text)
            if not parsed:
                raise ValueError("行情分批返回空数据，可能限流；本次快照未替换")
            rows.extend(parsed)
            calls += 1
        return {"rows": rows, "source": "腾讯公开行情", "http_requests": calls}
    if operation == "review_quotes_tencent":
        symbols = kwargs["symbols"]
        if not symbols or len(symbols) > 80:
            raise ValueError("批量行情每次需1～80只股票")
        response = requests.get("https://qt.gtimg.cn/q=" + ",".join(symbols), timeout=(8, 15))
        response.raise_for_status()
        response.encoding = "gbk"
        rows = parse_tencent_daily_quotes(response.text)
        if not rows:
            raise ValueError("腾讯批量行情为空，复盘已暂停")
        return {"rows": rows, "source":"腾讯批量行情", "http_requests":1}
    import akshare as ak
    if operation == "quotes_eastmoney":
        return {"rows": normalize_quotes(ak.stock_zh_a_spot_em().to_dict("records")),
                "source": "AKShare / 东方财富", "http_requests": None}
    if operation == "directory":
        board = kwargs["board"]
        if board in ("沪市主板", "科创板"):
            frame = ak.stock_info_sh_name_code(symbol="主板A股" if board == "沪市主板" else "科创板")
        elif board == "深圳":
            frame = ak.stock_info_sz_name_code(symbol="A股列表")
        else:
            frame = ak.stock_info_bj_name_code()
        return {"rows": normalize_directory(frame.to_dict("records"), board)}
    if operation == "calendar":
        return {"days": sorted({str(d)[:10] for d in ak.tool_trade_date_hist_sina()["trade_date"]})}
    if operation == "suspensions":
        frame = ak.stock_tfp_em(date=kwargs["date"].replace("-", ""))
        # Preserve intervals: a suspension announcement may be for a future session.
        records = frame.to_dict("records")
        return {"date": kwargs["date"], "records": [{k: str(v) for k, v in r.items()} for r in records]}
    if operation == "history":
        end = kwargs["date"].replace("-", "")
        start = (date.fromisoformat(kwargs["start_date"]) if kwargs.get("start_date")
                 else date.fromisoformat(kwargs["date"]) - timedelta(days=220)).strftime("%Y%m%d")
        arguments = dict(symbol=kwargs["code"], period="daily", start_date=start, end_date=end)
        adjusted = ak.stock_zh_a_hist(**arguments, adjust="qfq").to_dict("records")
        raw = ak.stock_zh_a_hist(**arguments, adjust="").to_dict("records")
        if not adjusted or not raw:
            raise ValueError("历史数据为空，未覆盖原缓存")
        return normalize_history(adjusted, raw) | {"source": "东方财富历史日线", "http_requests": None}
    raise ValueError("未知操作")

if __name__ == "__main__":
    try:
        args = json.loads(sys.stdin.read())
        result = {"data": execute(args["operation"], **args["kwargs"])}
    except Exception as exc:
        result = {"error": f"{type(exc).__name__}: {str(exc)[:350]}"}
    print("__RESULT__" + json.dumps(result, ensure_ascii=True, allow_nan=False))
