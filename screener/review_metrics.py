"""Display-only values derived from a saved review result and its K-line snapshot."""
import math
import pandas as pd

from .indicators import add_indicators


def _positive(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (TypeError, ValueError):
        return None


def review_metrics(result: dict) -> dict:
    close = _positive(result.get("close"))
    snakea = _positive(result.get("snakea"))
    previous = _positive(result.get("snakea_previous"))
    values = {"distance_pct":100*(close/snakea-1) if close and snakea else None,
              "snakea_change_pct":100*(snakea/previous-1) if snakea and previous else None,
              "stop_lower":_positive(result.get("stop_lower")), "stop_color":result.get("stop_color")}
    history = result.get("history") or {}
    if not history.get("bars"):
        return values
    try:
        df = add_indicators(history["bars"])
        date = result.get("indicator_date") or history.get("basis_date")
        found = df.loc[df.date == date]
        if found.empty:
            return values
        row = found.iloc[-1]
        red, green = pd.notna(row.stop_red), pd.notna(row.stop_green)
        if red or green:
            values["stop_lower"] = float(row.B2)
            values["stop_color"] = "红绿重合" if red and green else "红" if red else "绿"
    except (ValueError, TypeError, KeyError):
        pass
    return values
