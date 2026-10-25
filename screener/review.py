"""Explicit, resumable daily reviews with per-run chart snapshots."""
import json
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from bisect import bisect_left, bisect_right

from .core import BOARDS
from .indicators import add_indicators
from .history_cache import HistoryCache, provider_source
from .review_metrics import review_metrics
from .service import Service
from .store import now
from .validation import validate


def closed_quote_history(history, quote, calendar, target):
    """Complete a lagging Tencent daily feed from a verified post-close spot bar."""
    if not quote or not history or not history.get("comparable"):
        return None
    previous = [day for day in calendar if day < target]
    if (not previous or history.get("basis_date") != previous[-1]
            or quote.get("date") != target
            or not (quote.get("quote_time") or "").startswith(target+" ")
            or (quote.get("quote_time") or "")[11:19] < "15:05:00"
            or quote.get("volume", 0) <= 0):
        return None
    last = history["bars"][-1]
    if abs(last["close"]-quote["previous_close"]) > .011:
        return None
    bar = {key:quote[key] for key in ("date","open","high","low","close","volume")}
    return history | {"bars":history["bars"]+[bar], "basis_date":target,
                      "cache_mode":"spot_close", "verification":"腾讯收盘行情补足滞后的历史日K"}


def needs_scan(result):
    return result is None or result.get("outcome") == "error" or (
        result.get("outcome") == "unknown" and result.get("reason") == "目标日的日K尚未返回")


def review_signal(history, calendar, target):
    unknown = lambda reason: {"outcome":"unknown", "reason":reason}
    if not history or history.get("basis_date") != target:
        return unknown("目标日的日K尚未返回")
    records = [b for b in history.get("bars", []) if b.get("date", "") <= target]
    expected = sorted({d for d in calendar if d <= target})[-15:]
    dates = {b.get("date") for b in records}
    if len(expected) < 15 or expected[-1] != target or any(d not in dates for d in expected):
        return unknown("不足15根连续日K或存在交易日缺口")
    try:
        df = add_indicators(records)
    except (ValueError, TypeError, KeyError):
        return unknown("历史日K格式异常")
    if df.close.tail(15).isna().any():
        return unknown("收盘价缺失")
    if df.volume.iloc[-1] <= 0:
        return {"outcome":"excluded", "reason":"目标日日K无成交"}
    count = 0
    start_known = True
    for i in range(len(df)-1, -1, -1):
        row = df.iloc[i]
        if not (row.close > 0 and row.SNAKEA > 0):
            if count <= 2:
                return unknown("历史不足，无法确认本轮站上起点")
            start_known = False
            break
        if row.close <= row.SNAKEA:
            break
        count += 1
    else:
        start_known = False
    if count:
        required = count+13 if start_known else count+12
        needed = sorted({d for d in calendar if d <= target})[-required:]
        if len(needed) != required or any(d not in dates for d in needed):
            return unknown("站上区间存在交易日缺口")
    last, previous = df.iloc[-1], df.iloc[-2]
    delta = float(last.SNAKEA - previous.SNAKEA)
    direction = "上行" if delta > 1e-9 else "下行" if delta < -1e-9 else "走平"
    matched = count in (1, 2) or (count > 2 and direction == "上行")
    return {
        "outcome":"match" if matched else "no_match",
        "reason": ("站上1～2天" if count in (1,2) else "持续站上且SNAKEA上行") if matched
                  else "未站上SNAKEA" if not count else "站上超过2天但SNAKEA未上行",
        "above_days":count, "above_days_at_least":not start_known,
        "break_date":df.date.iloc[-count] if count and start_known else "",
        "close":float(last.close), "snakea":float(last.SNAKEA),
        "snakea_previous":float(previous.SNAKEA), "snakea_direction":direction,
        "indicator_date":target,
    }


class ReviewRepository:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS review_results(
                    run_id TEXT, code TEXT, value TEXT NOT NULL,
                    PRIMARY KEY(run_id,code));
                CREATE TABLE IF NOT EXISTS review_lease(
                    id INTEGER PRIMARY KEY CHECK(id=1), run_id TEXT, owner TEXT, expires REAL);
            """)

    def get(self, run_id):
        return self.store.get("review:run:"+run_id)

    def save(self, run):
        run["updated_at"] = now()
        self.store.put("review:run:"+run["id"], run)

    def runs(self):
        with self.store.connect() as db:
            rows = db.execute("SELECT value FROM documents WHERE key LIKE 'review:run:%'").fetchall()
        return sorted([json.loads(r[0]) for r in rows], key=lambda r:r["created_at"], reverse=True)

    def results(self, run_id, include_history=True):
        with self.store.connect() as db:
            field = "value" if include_history else "json_remove(value, '$.history')"
            rows = db.execute(f"SELECT {field} FROM review_results WHERE run_id=? ORDER BY code", (run_id,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def result(self, run_id, code):
        with self.store.connect() as db:
            row = db.execute("SELECT value FROM review_results WHERE run_id=? AND code=?", (run_id, code)).fetchone()
        return json.loads(row[0]) if row else None

    def put_result(self, run_id, result):
        with self.store.connect() as db:
            db.execute("INSERT OR REPLACE INTO review_results VALUES(?,?,?)",
                       (run_id, result["code"], json.dumps(result, ensure_ascii=False, allow_nan=False)))

    def stop(self, run_id):
        self.store.put("review:stop:"+run_id, True)

    def active(self):
        with self.store.connect() as db:
            row = db.execute("SELECT run_id FROM review_lease WHERE id=1 AND expires>?", (time.time(),)).fetchone()
        return row[0] if row else None

    def claim(self, run_id, owner):
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT expires FROM review_lease WHERE id=1").fetchone()
            if row and row[0] > time.time():
                return False
            db.execute("INSERT OR REPLACE INTO review_lease VALUES(1,?,?,?)",
                       (run_id, owner, time.time()+180))
        return True

    def heartbeat(self, owner):
        with self.store.connect() as db:
            changed = db.execute("UPDATE review_lease SET expires=? WHERE id=1 AND owner=?",
                                 (time.time()+180, owner)).rowcount
        if not changed:
            raise RuntimeError("复盘任务占用已失效，请重新继续")

    def release(self, owner):
        with self.store.connect() as db:
            db.execute("DELETE FROM review_lease WHERE owner=?", (owner,))


class ReviewRunner:
    def __init__(self, repo, service=None, delay=0.1):
        self.repo = repo
        self.service = service or Service(repo.store)
        self.delay = delay
        self._request_lock = threading.Lock()
        self._next_request = 0.0

    def create(self, config):
        if not config["boards"] or not set(config["boards"]) <= set(BOARDS):
            raise ValueError("请选择有效市场")
        if config["source"] not in ("tencent", "eastmoney"):
            raise ValueError("未知历史来源")
        if type(config.get("workers", 1)) is not int or not 1 <= config.get("workers", 1) <= 10:
            raise ValueError("并发数必须是1至10的整数")
        run = dict(id=uuid.uuid4().hex, config=config, status="ready", stage=0,
                   created_at=now(), updated_at=now(), target=None, total=0,
                   processed=0, current="", error="")
        self.repo.save(run)
        return run

    def start(self, run_id):
        owner = uuid.uuid4().hex
        if not self.repo.claim(run_id, owner):
            raise RuntimeError("已有复盘任务进行中，请先停止或等待结束")
        run = self.repo.get(run_id)
        if run["status"] in ("paused", "running", "partial"):
            # A resumed scan must re-fetch today's quotes and directory; otherwise
            # morning quotes and old unknown verdicts survive a post-close retry.
            run["stage"] = 0
            self.repo.save(run)
            context_key = "review:context:"+run_id
            context = self.repo.store.get(context_key, {})
            for key in ("batch_complete", "batch_index", "batch_quotes", "batch_fetched_at"):
                context.pop(key, None)
            self.repo.store.put(context_key, context)
        self.repo.store.put("review:stop:"+run_id, False)
        thread = threading.Thread(target=self.run, args=(run_id,owner), daemon=True)
        try:
            thread.start()
        except Exception:
            self.repo.release(owner)
            raise

    def run(self, run_id, owner=None):
        if owner is None:
            owner = uuid.uuid4().hex
            if not self.repo.claim(run_id, owner):
                return
        run = self.repo.get(run_id)
        try:
            run.update(status="running", error="")
            self.repo.save(run)
            self._execute(run, owner)
        except Exception as exc:
            run.update(status="paused", error=str(exc)[:500])
            self.repo.save(run)
        finally:
            self.repo.release(owner)

    def checkpoint(self, run, owner):
        self.repo.heartbeat(owner)
        if self.repo.store.get("review:stop:"+run["id"], False):
            run.update(status="paused", current="已停止")
            self.repo.save(run)
            return False
        return True

    def _execute(self, run, owner):
        cfg = run["config"]
        groups = [b for b in ("沪市主板","科创板","深圳","北交所")
                  if b in cfg["boards"] or (b == "深圳" and set(cfg["boards"]) & {"深市主板","创业板"})]
        steps = [("calendar", None)] + [("directory", b) for b in groups]
        context_key = "review:context:"+run["id"]
        context = self.repo.store.get(context_key, {"calendar":[], "stocks":[]})
        for stage in range(run["stage"], len(steps)):
            if not self.checkpoint(run, owner):
                return
            operation, board = steps[stage]
            run["current"] = "获取交易日历" if board is None else "获取目录："+board
            self.repo.save(run)
            data = self.service.request(operation, **({"board":board} if board else {}))
            if operation == "calendar":
                context["calendar"] = sorted(set(data["days"]))
                days = [d for d in context["calendar"] if d <= cfg["requested_date"]]
                if not days or context["calendar"][-1] < cfg["requested_date"]:
                    raise ValueError("交易日历覆盖不足，请稍后重试")
                run["target"] = days[-1]
            else:
                stocks = {r["code"]:r for r in context["stocks"]}
                stocks.update({r["code"]:r for r in data["rows"] if r.get("board") in cfg["boards"]})
                context["stocks"] = list(stocks.values())
            self.repo.store.put(context_key, context)
            run["stage"] = stage+1
            self.repo.save(run)
        run["total"] = len(context["stocks"])
        if not run["total"]:
            raise ValueError("所选市场目录为空，未开始扫描")
        previous = {r["code"]:r for r in self.repo.results(run["id"], include_history=False)}
        if cfg["source"] == "tencent" and not context.get("batch_complete"):
            cached = [stock for stock in context["stocks"] if self.exclusion(
                stock, context["calendar"], run["target"], cfg) is None
                and needs_scan(previous.get(stock["code"]))]
            context.setdefault("batch_quotes", {})
            for start in range(context.get("batch_index", 0), len(cached), 80):
                if not self.checkpoint(run, owner):
                    return
                group = cached[start:start+80]
                run["current"] = f"批量读取当日行情 {start+1}～{start+len(group)} / {len(cached)}"
                self.repo.save(run)
                symbols = [("sh" if r["board"] in ("沪市主板","科创板") else
                            "bj" if r["board"] == "北交所" else "sz")+r["code"] for r in group]
                data = self.service.request("review_quotes_tencent", symbols=symbols)
                context["batch_quotes"].update({r["code"]:r for r in data["rows"]})
                context["batch_index"] = start+len(group)
                context["batch_fetched_at"] = now()
                self.repo.store.put(context_key, context)
            context["batch_complete"] = True
            self.repo.store.put(context_key, context)
        pending = iter(stock for stock in context["stocks"] if needs_scan(previous.get(stock["code"])))
        workers = cfg.get("workers", 1)
        consecutive_errors = 0
        halted = False
        halt_reason = ""
        exhausted = False
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="review-history") as pool:
            active = {}
            while active or not exhausted:
                self.repo.heartbeat(owner)
                if self.repo.store.get("review:stop:"+run["id"], False):
                    halted = True
                    halt_reason = "已停止；当前请求结束后可继续"
                while not halted and not exhausted and len(active) < workers:
                    stock = next(pending, None)
                    if stock is None:
                        exhausted = True
                        break
                    run["current"] = stock["code"]+" "+(stock.get("name") or "")
                    self.repo.save(run)
                    active[pool.submit(self._scan_stock, stock, context["calendar"], run["target"], cfg,
                                       context.get("batch_quotes", {}).get(stock["code"]),
                                       context.get("batch_fetched_at"))] = stock
                if not active:
                    break
                done, _ = wait(active, timeout=5, return_when=FIRST_COMPLETED)
                for future in done:
                    stock = active.pop(future)
                    try:
                        result = future.result()
                    except Exception as exc:
                        result = stock | {"outcome":"error", "reason":str(exc)[:500], "fetched_at":now()}
                    self.repo.put_result(run["id"], result)
                    previous[stock["code"]] = result
                    run["processed"] = len(previous)
                    self.repo.save(run)
                    consecutive_errors = consecutive_errors+1 if result["outcome"] == "error" else 0
                    if result["outcome"] == "error" and (consecutive_errors >= 3 or any(
                            word in result["reason"].lower() for word in ("429","403","限流","quota"))):
                        halted = True
                        halt_reason = "接口连续失败或限流，已暂停。可稍后点击继续复盘。"
        if halted:
            run.update(status="paused", current="", error=halt_reason, processed=len(previous))
            self.repo.save(run)
            return
        run.update(status="partial" if any(r["outcome"] == "error" for r in previous.values()) else "done",
                   current="", finished_at=now(), processed=len(previous))
        self.repo.save(run)

    def _request_history(self, operation, **kwargs):
        # Limit launch rate across workers; each history task may make multiple HTTP calls.
        with self._request_lock:
            wait_for = max(0.0, self._next_request-time.monotonic())
            if wait_for:
                time.sleep(wait_for)
            self._next_request = time.monotonic()+self.delay
        return self.service.request(operation, **kwargs)

    def _quick_signal(self, stock, calendar, target, cfg, quote):
        if not quote or quote["date"] != target or quote["volume"] <= 0:
            return None
        old = self.repo.store.get("history:"+stock["code"])
        if not old or provider_source(old) != "tencent":
            return None
        try:
            validate("history", old, {})
        except (ValueError, TypeError):
            return None
        dates = sorted(d for d in calendar if d <= target)
        if len(dates) < 2:
            return None
        previous_day = dates[-2]
        records = [b for b in old["bars"] if b["date"] < target]
        if len(records) < 15 or records[-1]["date"] != previous_day:
            return None
        if not old.get("comparable") or abs(records[-1]["close"]-quote["previous_close"]) > .011:
            return None
        bar = {k:quote[k] for k in ("date","open","high","low","close","volume")}
        result = review_signal({"basis_date":target, "bars":records+[bar]}, calendar, target)
        if result["outcome"] != "no_match":
            return None
        # Borderline prices or a flat SNAKEA need the adjusted daily feed.
        if abs(result["close"]-result["snakea"])/result["snakea"] < .02:
            return None
        if result["above_days"] > 2 and result["snakea_direction"] == "走平":
            return None
        return result | {"cache_mode":"batch", "verification":"批量初筛；未逐股核对前复权"}

    def _scan_stock(self, stock, calendar, target, cfg, quote=None, batch_fetched_at=None):
        result = self.exclusion(stock, calendar, target, cfg)
        if result is None:
            if cfg.get("fast_batch") and not cfg.get("force_refresh", False):
                result = self._quick_signal(stock, calendar, target, cfg, quote)
                if result is not None:
                    result["data_fetched_at"] = batch_fetched_at
        if result is None:
            try:
                history = HistoryCache(self.repo.store, self._request_history).refresh(
                    stock["code"], stock["board"], target, cfg["source"],
                    allow_closed_cache=not cfg.get("force_refresh", False))
                if history["basis_date"] != target and cfg["source"] == "tencent":
                    history = closed_quote_history(history, quote, calendar, target) or history
                result = review_signal(history, calendar, target)
                result.update(cache_mode=history["cache_mode"], data_fetched_at=history["fetched_at"])
                if history.get("verification"):
                    result["verification"] = history["verification"]
                if result["outcome"] in ("match", "no_match"):
                    result.update(review_metrics(result | {"history":history}))
                if result["outcome"] == "match":
                    result["history"] = history
            except Exception as exc:
                result = {"outcome":"error", "reason":str(exc)[:500]}
        return stock | result | {"fetched_at":now()}

    @staticmethod
    def exclusion(stock, calendar, target, cfg):
        if cfg.get("exclude_st") and not stock.get("name"):
            return {"outcome":"unknown", "reason":"股票名称缺失，ST状态未知"}
        if cfg.get("exclude_st") and "ST" in (stock.get("name") or "").upper():
            return {"outcome":"excluded", "reason":"ST股票"}
        if cfg.get("exclude_new"):
            listed = stock.get("listed")
            if not listed:
                return {"outcome":"unknown", "reason":"上市日期缺失"}
            count = bisect_right(calendar,target)-bisect_left(calendar,listed)
            if count < 60:
                if listed < calendar[0]:
                    return {"outcome":"unknown", "reason":"交易日历不足以判断上市天数"}
                return {"outcome":"excluded", "reason":"上市不足60个交易日"}
        return None
