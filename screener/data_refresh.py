"""One explicit full-market acquisition job, persisted progress and bounded concurrency."""
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from .service import Service
from .history_cache import HistoryCache
from .review import ReviewRepository, ReviewRunner
from .store import now


class MarketRefresh:
    def __init__(self, store, service=None):
        self.store = store
        self.service = service or Service(store)
        self.repo = ReviewRepository(store)

    def start(self, workers=5, source="tencent", history_source="tencent"):
        if type(workers) is not int or not 1 <= workers <= 10:
            raise ValueError("线程数必须在1～10之间")
        owner = uuid.uuid4().hex
        if not self.repo.claim("market-data", owner):
            raise RuntimeError("已有数据或复盘任务运行中，请先等待或停止")
        self.store.put("market:stop", False)
        self.store.put("market:refresh", dict(status="running", current="准备获取", processed=0,
            total=0, errors=[], missing=0, success=0, started_at=now(), updated_at=now()))
        try:
            threading.Thread(target=self.run, args=(owner, workers, source, history_source), daemon=True).start()
        except Exception:
            self.repo.release(owner)
            raise

    def run(self, owner, workers, source, history_source):
        state = self.store.get("market:refresh")
        def save(**values):
            state.update(values, updated_at=now())
            self.store.put("market:refresh", state)
            self.repo.heartbeat(owner)
        def stopped():
            return self.store.get("market:stop", False)
        try:
            for operation, board in [("calendar", None), ("directory", "沪市主板"),
                    ("directory", "科创板"), ("directory", "深圳"), ("directory", "北交所")]:
                if stopped():
                    save(status="paused", current="已停止")
                    return
                save(current="更新"+(board or "交易日历"))
                self.service.refresh_basic(operation, board)
            if stopped():
                save(status="paused", current="已停止")
                return
            save(current="获取全市场最新行情")
            self.service.refresh_quotes(source)
            try:
                self.service.refresh_suspensions()
            except Exception as exc:
                state["errors"].append("停牌资料："+str(exc)[:200])
            days = [d for d in self.store.get("calendar", {}).get("days", []) if d <= now()[:10]]
            if not days:
                raise ValueError("交易日历不足，无法确定日K目标日期")
            target = max(days)
            stocks = self.service.directory()
            save(target=target, total=len(stocks), current="更新全市场日K")
            if history_source == "tencent":
                daily = {}
                for offset in range(0, len(stocks), 80):
                    if stopped():
                        save(status="paused", current="已停止")
                        return
                    group = stocks[offset:offset+80]
                    symbols = [("sh" if r["board"] in ("沪市主板", "科创板") else "bj" if r["board"] == "北交所" else "sz")+r["code"] for r in group]
                    save(current=f"获取日K补全行情 {offset+1} / {len(stocks)}")
                    response = self.service.request("review_quotes_tencent", symbols=symbols)
                    daily.update({r["code"]:r for r in response["rows"]})
                self.store.put("market:daily", {"rows":daily, "fetched_at":now()})
            throttled = ReviewRunner(self.repo, self.service)._request_history
            # A bounded queue means stopping does not leave thousands of queued requests.
            pending = iter(stocks)
            halted = False
            exhausted = False
            failures = 0
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="market-data") as pool:
                active = {}
                while active or not exhausted:
                    if stopped():
                        halted = True
                    while not halted and not exhausted and len(active) < workers:
                        row = next(pending, None)
                        if row is None:
                            exhausted = True
                            break
                        future = pool.submit(HistoryCache(self.store, throttled).refresh,
                            row["code"], row.get("board"), target, history_source)
                        active[future] = row
                    if not active:
                        break
                    finished, _ = wait(active, timeout=3, return_when=FIRST_COMPLETED)
                    for future in finished:
                        row = active.pop(future)
                        try:
                            history = future.result()
                            failures = 0
                            state["success"] += 1
                            if history.get("basis_date") != target:
                                state["missing"] += 1
                        except Exception as exc:
                            failures += 1
                            reason = str(exc)[:200]
                            state["errors"].append(row["code"]+"："+reason)
                            if failures >= 3 or any(w in reason.lower() for w in ("429", "403", "限流", "quota")):
                                halted = True
                        state["processed"] += 1
                    save(current="正在完成已发出的请求" if halted else "更新全市场日K")
            save(status="paused" if halted else "partial" if state["errors"] or state["missing"] else "done",
                 current="已暂停，可再次获取以补齐缓存" if halted else "本轮获取完成")
        except Exception as exc:
            state["errors"].append(str(exc)[:300])
            save(status="paused", current="获取中断，旧缓存已保留")
        finally:
            self.repo.release(owner)
