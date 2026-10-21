import pytest
from screener.review_metrics import review_metrics


def bars():
    return [{"date":f"2026-01-{day:02d}","open":10,"high":11,"low":9,"close":10,"volume":100}
            for day in range(1,21)]


def test_metrics_use_saved_adjusted_history_and_can_overlap():
    result = {"close":11,"snakea":10,"snakea_previous":9,
              "history":{"bars":bars(), "basis_date":"2026-01-20"}, "indicator_date":"2026-01-20"}
    values = review_metrics(result)
    assert values["distance_pct"] == pytest.approx(10)
    assert values["snakea_change_pct"] == pytest.approx(100/9)
    assert values["stop_lower"] == pytest.approx(10)
    assert values["stop_color"] == "红"


def test_missing_old_snapshot_or_zero_denominator_is_unknown():
    assert review_metrics({"close":11,"snakea":0,"snakea_previous":0}) == {
        "distance_pct":None,"snakea_change_pct":None,"stop_lower":None,"stop_color":None}
    values = review_metrics({"close":11,"snakea":10,"snakea_previous":9})
    assert values["distance_pct"] == pytest.approx(10)
    assert values["stop_lower"] is None


def test_saved_stop_value_survives_lightweight_result_view():
    values = review_metrics({"close":11,"snakea":10,"snakea_previous":9,
                             "stop_lower":10,"stop_color":"红"})
    assert values["stop_lower"] == 10
    assert values["stop_color"] == "红"
