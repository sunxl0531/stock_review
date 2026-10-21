"""Validate external payloads before they can replace a usable cache."""
import re
from .core import BOARDS, number
from .provider import day

def require(condition, message):
    if not condition:
        raise ValueError("接口数据校验失败：" + message)

def valid_code(value):
    return isinstance(value, str) and re.fullmatch(r"\d{6}", value) is not None

def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and number(value) is not None

def validate(operation, data, arguments):
    require(isinstance(data, dict), "预期对象")
    if operation == "calendar":
        days = data.get("days")
        require(isinstance(days, list) and bool(days), "交易日历为空")
        require(all(isinstance(d, str) and day(d) == d for d in days), "交易日期格式")
        require(days == sorted(set(days)), "交易日历重复或未排序")
    elif operation == "directory" or operation.startswith("quotes_"):
        rows = data.get("rows")
        require(isinstance(rows, list) and bool(rows), "证券数据为空")
        require(all(isinstance(r, dict) and valid_code(r.get("code")) for r in rows), "证券代码格式")
        require(len({r["code"] for r in rows}) == len(rows), "重复代码")
        if operation == "directory":
            expected = {"深市主板", "创业板"} if arguments.get("board") == "深圳" else {arguments.get("board")}
            require(all(r.get("board") in expected and r.get("board") in BOARDS and isinstance(r.get("name"), str)
                        and bool(r["name"]) and "listed" in r
                        and (r["listed"] is None or day(r["listed"]) == r["listed"]) for r in rows), "证券目录字段")
        else:
            fields = {"code", "name", "price", "change_pct", "volume_ratio", "amount", "quote_date"}
            require(all(fields <= r.keys() and isinstance(r.get("name"), str) and bool(r["name"]) for r in rows), "行情字段缺失")
            require(all(r[k] is None or numeric(r[k]) for r in rows for k in ("price", "change_pct", "volume_ratio", "amount")), "行情数值格式")
            require(any(numeric(r["price"]) and r["price"] > 0 for r in rows), "没有有效价格")
            require(all(r["quote_date"] is None or day(r["quote_date"]) == r["quote_date"] for r in rows), "行情日期格式")
    elif operation == "suspensions":
        require(data.get("date") == arguments.get("date") and day(data.get("date")) == data.get("date"), "停牌日期不一致")
        require(isinstance(data.get("records"), list), "停牌记录字段缺失")
        for row in data["records"]:
            require(isinstance(row, dict) and valid_code(row.get("代码")) and day(row.get("停牌时间")) is not None
                    and "预计复牌时间" in row and "停牌截止时间" in row, "停牌记录字段异常")
    elif operation == "history":
        bars = data.get("bars")
        require(isinstance(bars, list) and bool(bars), "历史行情为空")
        require(isinstance(data.get("comparable"), bool) and isinstance(data.get("basis_date"), str)
                and day(data["basis_date"]) == data["basis_date"], "历史基准格式")
        require(all(isinstance(b, dict) and isinstance(b.get("date"), str) and day(b["date"]) == b["date"]
                    and all(numeric(b.get(k)) for k in ("open", "high", "low", "close", "volume"))
                    and b["low"] <= min(b["open"], b["close"]) <= max(b["open"], b["close"]) <= b["high"] for b in bars), "历史行情字段或价格异常")
        dates = [b["date"] for b in bars]
        require(dates == sorted(set(dates)) and dates[-1] == data["basis_date"], "历史日期重复或基准不符")
    elif operation == "review_quotes_tencent":
        rows = data.get("rows")
        require(isinstance(rows, list) and bool(rows), "批量行情为空")
        require(all(isinstance(r, dict) and valid_code(r.get("code")) and day(r.get("date")) == r.get("date")
                    and all(numeric(r.get(k)) for k in ("open","high","low","close","volume","previous_close"))
                    and r["low"] <= min(r["open"],r["close"]) <= max(r["open"],r["close"]) <= r["high"]
                    for r in rows), "批量日K字段异常")
        require(len({r["code"] for r in rows}) == len(rows), "批量行情代码重复")
