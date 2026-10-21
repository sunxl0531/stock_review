"""Network-free screening. Unknown inputs never silently become passing values."""
from dataclasses import dataclass
from bisect import bisect_left, bisect_right
import csv
import io
import math

BOARDS = ("沪市主板", "深市主板", "创业板", "科创板", "北交所")

@dataclass
class Filters:
    boards: tuple = BOARDS
    exclude_st: bool = True
    exclude_suspended: bool = True
    exclude_new: bool = True
    change_min: float | None = None
    change_max: float | None = None
    ratio_min: float | None = None
    amount_min: float | None = None
    breakout_days: int | None = None
    ma_bullish: bool = False
    snakea_cross: bool = False

    def __post_init__(self):
        if self.change_min is not None and self.change_max is not None and self.change_min > self.change_max:
            raise ValueError("涨跌幅下限不能大于上限")

def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None

def breakout(row, history, periods, calendar, as_of):
    if not history:
        return None, "历史数据待补齐"
    if not history.get("comparable") or history.get("basis_date") != as_of:
        return None, "历史价格基准未验证或已过期"
    if row.get("quote_date") != as_of:
        return None, "行情交易日期未确认或不一致"
    expected = [d for d in calendar if d < as_of][-periods:]
    bars = {b["date"]: b for b in history.get("bars", [])}
    if len(expected) != periods or any(d not in bars for d in expected):
        return None, "历史不足或交易日缺口"
    highs = [number(bars[d].get("high")) for d in expected]
    price = number(row.get("price"))
    if price is None or price <= 0 or any(h is None or h <= 0 for h in highs):
        return None, "价格缺失"
    threshold = max(highs)
    return price > threshold, f"此前{periods}日高点 {threshold:.2f}"

def technical_signals(history, calendar, as_of, filters):
    """Evaluate the same cached daily indicators as the detail chart."""
    from .indicators import add_indicators
    if not history:
        return None, "指标历史数据待补齐"
    if history.get("basis_date") != as_of:
        return None, "指标日线已过期，请更新历史"
    periods = 20 if filters.ma_bullish else 14
    expected = sorted({d for d in calendar if d <= as_of})[-periods:]
    records = [b for b in history.get("bars", []) if b.get("date", "") <= as_of]
    dates = {b.get("date") for b in records}
    if (len(expected) != periods or expected[-1] != as_of
            or any(d not in dates for d in expected)):
        return None, "指标历史不足或交易日缺口"
    try:
        df = add_indicators(records)
    except (ValueError, TypeError, KeyError):
        return None, "指标历史格式异常，请更新历史"
    if df.close.tail(periods).isna().any():
        return None, "指标收盘价缺失"
    last, previous = df.iloc[-1], df.iloc[-2]
    return {
        "ma_bullish": bool(last.MA5 > last.MA10 > last.MA20),
        "snakea_cross": bool(previous.close <= previous.SNAKEA and last.close > last.SNAKEA),
        "indicator_date": last.date,
        "ma5": float(last.MA5), "ma10": float(last.MA10), "ma20": float(last.MA20),
        "snakea": float(last.SNAKEA),
    }, ""

def screen(rows, filters, calendar, histories, as_of):
    calendar = sorted(set(calendar))
    result = []
    for row in rows:
        failed, unknown = [], []
        if row.get("board") is None:
            unknown.append("市场归属待补齐")
        elif row["board"] not in filters.boards:
            failed.append("市场未选择")
        if number(row.get("price")) is None or number(row.get("price")) <= 0:
            unknown.append("无有效行情价格")
        if row.get("quote_date") and row["quote_date"] != as_of:
            unknown.append("行情日期与本批次不一致")
        if filters.exclude_st:
            name = row.get("name")
            if not name:
                unknown.append("ST状态未知")
            elif "ST" in name.upper():
                failed.append("ST股票")
        if filters.exclude_suspended:
            if row.get("status_date") != as_of or row.get("suspended") is None:
                unknown.append("停牌状态待确认")
            elif row["suspended"]:
                failed.append("停牌")
        if filters.exclude_new:
            listed = row.get("listed")
            if not listed or not calendar or calendar[-1] < as_of or listed > as_of:
                unknown.append("上市日期或交易日历待补齐")
            else:
                # A calendar beginning after the listing date still proves >=60
                # if it contains at least 60 subsequent market sessions.
                count = bisect_right(calendar, as_of) - bisect_left(calendar, listed)
                if count < 60:
                    if listed < calendar[0]:
                        unknown.append("交易日历覆盖不足")
                    else:
                        failed.append("上市不足60个交易日")
        for field, label, lower, upper in [
            ("change_pct", "涨跌幅", filters.change_min, filters.change_max),
            ("volume_ratio", "量比", filters.ratio_min, None),
            ("amount", "成交额", filters.amount_min, None),
        ]:
            if lower is None and upper is None:
                continue
            value = number(row.get(field))
            if value is None:
                unknown.append(label + "缺失")
            elif (lower is not None and value < lower) or (upper is not None and value > upper):
                failed.append(label + "不满足")
        state, reason = "未启用", ""
        if filters.breakout_days:
            ok, reason = breakout(row, histories.get(row["code"]), filters.breakout_days, calendar, as_of)
            state = "盘中突破" if ok else "未突破" if ok is False else "待判定"
            if ok is None:
                unknown.append(reason)
            elif not ok:
                failed.append("未突破")
        technical = {"ma_state":"未启用", "snakea_state":"未启用", "indicator_date":""}
        if filters.ma_bullish or filters.snakea_cross:
            signals, detail = technical_signals(histories.get(row["code"]), calendar, as_of, filters)
            if signals is None:
                unknown.append(detail)
            else:
                technical.update(signals)
            for enabled, signal, label, column in [
                (filters.ma_bullish, "ma_bullish", "均线多头排列", "ma_state"),
                (filters.snakea_cross, "snakea_cross", "日K上穿SNAKEA", "snakea_state"),
            ]:
                if enabled:
                    technical[column] = "待判定" if signals is None else "满足" if signals[signal] else "不满足"
                    if signals is not None and not signals[signal]:
                        failed.append(label + "不满足")
        result.append(row | technical | {"result": "未匹配" if failed else "无法判定" if unknown else "匹配",
                             "reason": "；".join(failed + unknown), "breakout": state,
                             "breakout_detail": reason})
    return result

LABELS = {"code":"代码", "name":"名称", "board":"市场", "price":"最新价", "change_pct":"涨跌幅(%)",
          "volume_ratio":"量比", "amount":"成交额(元)", "breakout":"突破状态",
          "ma_state":"均线多头", "snakea_state":"上穿SNAKEA", "indicator_date":"指标日线日期", "result":"筛选结果",
          "reason":"说明", "quote_time":"行情时间", "fetched_at":"获取时间", "source":"来源"}

def export_csv(rows):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(LABELS.values())
    for row in rows:
        values = []
        for key in LABELS:
            value = row.get(key, "")
            if key == "code" or (isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r"))):
                value = "'" + str(value)
            values.append(value)
        writer.writerow(values)
    return output.getvalue().encode("utf-8-sig")
