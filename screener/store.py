"""Small SQLite document store. No shared global connections."""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
import sqlite3
import threading

CHINA = timezone(timedelta(hours=8))
LOCKS = {}
LOCKS_GUARD = threading.Lock()

def now():
    return datetime.now(CHINA).isoformat(timespec="seconds")

class Store:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""CREATE TABLE IF NOT EXISTS documents(key TEXT PRIMARY KEY, value TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS requests(id INTEGER PRIMARY KEY, time TEXT, operation TEXT, ok INTEGER, detail TEXT);""")

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def get(self, key, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM documents WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key, payload):
        data = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO documents VALUES(?, ?)", (key, data))

    def log(self, operation, ok, detail=""):
        with self.connect() as db:
            db.execute("INSERT INTO requests(time, operation, ok, detail) VALUES(?, ?, ?, ?)",
                       (now(), operation, int(ok), str(detail)[:500]))

    def logs(self):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            return [dict(r) for r in db.execute("SELECT * FROM requests ORDER BY id DESC LIMIT 100")]

    def watchlist(self):
        return self.get("watchlist", [])

    def set_watchlist(self, codes):
        self.put("watchlist", sorted(set(codes)))

    @contextmanager
    def task_lock(self):
        with LOCKS_GUARD:
            lock = LOCKS.setdefault(str(self.path), threading.Lock())
        if not lock.acquire(blocking=False):
            raise RuntimeError("已有请求任务正在进行，请等待结束")
        try:
            yield
        finally:
            lock.release()
