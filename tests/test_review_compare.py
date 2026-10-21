from screener.review_compare import comparable_previous, compare_reviews


def run(day, boards=("沪市主板",), st=True, new=True, created="10:00", source="tencent"):
    return {"id":day+created, "target":day, "created_at":day+"T"+created,
            "config":{"boards":list(boards), "exclude_st":st, "exclude_new":new, "source":source}}


def row(code, outcome, **more):
    return {"code":code,"name":code,"outcome":outcome} | more


def test_previous_is_older_day_with_same_exclusions_and_boards():
    current = run("2026-10-20")
    old = run("2026-10-19")
    runs = [current, run("2026-10-20", created="09:00"),
            run("2026-10-19", st=False), run("2026-10-19", boards=("创业板",)), old]
    assert comparable_previous(runs, current) == old
    assert comparable_previous([current], current) is None
    assert comparable_previous([current, run("2026-10-19", source="eastmoney")], current) is None


def test_changes_require_two_explicit_verified_results():
    old = [row("1","no_match"),row("2","match"),row("3","match"),
           row("4","match"),row("5","match"),row("6","match"),row("7","unknown")]
    new = [row("1","match"),row("2","match"),row("3","no_match"),
           row("4","no_match",cache_mode="batch"),row("5","error"),
           row("7","match"),row("8","match")]
    groups = compare_reviews(old,new)
    assert {r["code"] for r in groups["new"]} == {"1"}
    assert {r["code"] for r in groups["continued"]} == {"2"}
    assert {r["code"] for r in groups["exited"]} == {"3"}
    assert {r["code"] for r in groups["uncertain"]} == {"4","5","6","7","8"}
