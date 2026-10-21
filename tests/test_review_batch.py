from datetime import date, timedelta

from screener.provider import parse_tencent_daily_quotes
from screener.review import ReviewRepository, ReviewRunner
from screener.store import Store
from screener.validation import validate

DAYS = [(date(2026, 1, 1)+timedelta(days=i)).isoformat() for i in range(100)]
TARGET = DAYS[-1]

def history(days, last=20):
    return {"basis_date":days[-1], "comparable":True, "source":"腾讯历史日线",
            "bars":[{"date":d,"open":p,"high":p+1,"low":p-1,"close":p,"volume":100}
                    for d,p in zip(days, [20]*(len(days)-1)+[last])]}

def test_tencent_batch_quote_contains_day_ohlc_and_previous_close():
    fields = [""]*88
    for index,value in {2:"600001",3:"11.44",4:"11.65",5:"11.62",6:"1245097",
                        30:"20261020161500",33:"11.68",34:"11.38"}.items():
        fields[index] = value
    rows = parse_tencent_daily_quotes('v_sh600001="'+'~'.join(fields)+'";')
    validate("review_quotes_tencent", {"rows":rows}, {})
    assert rows[0]["code"] == "600001"
    assert rows[0]["date"] == "2026-10-20"
    assert rows[0]["previous_close"] == 11.65
    assert rows[0]["high"] == 11.68

class BatchService:
    def __init__(self):
        self.calls = []
    def request(self, operation, **kwargs):
        self.calls.append((operation, kwargs))
        if operation == "calendar":
            return {"days":DAYS}
        if operation == "directory":
            return {"rows":[{"code":f"60000{i}", "name":f"股票{i}",
                             "board":"沪市主板", "listed":DAYS[0]} for i in (1,2,3)]}
        if operation == "review_quotes_tencent":
            return {"rows":[{"code":f"60000{i}", "date":TARGET,"open":20,
                             "high":31, "low":14, "close":close,
                             "previous_close":20, "volume":100}
                            for i,close in ((1,15),(2,30))]}
        if operation == "history":
            return history(DAYS[-30:], last=30)
        raise AssertionError(operation)

def test_batch_mode_avoids_individual_history_for_local_nonmatch(tmp_path):
    store = Store(tmp_path/"market.db")
    for i in (1,2):
        store.put(f"history:60000{i}", history(DAYS[-31:-1]))
    repo = ReviewRepository(store)
    service = BatchService()
    runner = ReviewRunner(repo, service, delay=0)
    run = runner.create({"boards":["沪市主板"],"source":"tencent", "requested_date":TARGET,
                         "exclude_st":True, "exclude_new":True, "workers":2,"fast_batch":True})
    runner.run(run["id"])
    assert repo.get(run["id"])["status"] == "done"
    by_code = {r["code"]:r for r in repo.results(run["id"])}
    assert by_code["600001"]["outcome"] == "no_match"
    assert by_code["600001"]["cache_mode"] == "batch"
    assert by_code["600002"]["outcome"] == "match"
    assert by_code["600003"]["outcome"] == "match"
    assert sum(op == "review_quotes_tencent" for op,_ in service.calls) == 1
    assert {args["code"] for op,args in service.calls if op == "history"} == {"600002","600003"}
    assert store.get("history:600001")["basis_date"] == DAYS[-2]
