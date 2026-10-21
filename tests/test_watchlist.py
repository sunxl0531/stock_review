import pytest
from screener.watchlist_ui import build_watch_rows


def test_watchlist_handles_empty_missing_and_saved_review():
    assert build_watch_rows([], [], [], None) == []
    rows = build_watch_rows(["600001","000001"],
        [{"code":"600001","name":"甲","board":"沪市主板"}],
        [{"code":"600001","outcome":"match","close":11,"snakea":10,"snakea_previous":9}],
        "2026-10-20")
    assert rows[0]["代码"] == "000001" and rows[0]["复盘状态"] == "未覆盖"
    assert rows[1]["复盘状态"] == "入选"
    assert rows[1]["距SNAKEA %"] == pytest.approx(10)
