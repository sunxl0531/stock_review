"""Verify the shipped ZIP after relocating it; no developer Python imports."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import time
import urllib.request
import zipfile
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]
archive_path = ROOT / "dist" / "A-share-screener-Windows-x64.zip"
destination = ROOT / ".portable-check" / "迁移验证 空格"
if destination.exists() and "--reuse" not in sys.argv:
    raise SystemExit("Verification directory already exists; do not overwrite it.")
destination.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(archive_path) as archive:
    for member in archive.infolist():
        resolved = (destination / member.filename).resolve()
        if not resolved.is_relative_to(destination.resolve()):
            raise ValueError("Unsafe archive path")
    assert archive.testzip() is None
    if "--reuse" not in sys.argv:
        archive.extractall(destination)
folder = next(destination.iterdir())
python = folder / "runtime" / "python.exe"
env = os.environ.copy()
for key in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "SCREENER_DATA_DIR"):
    env.pop(key, None)
env["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
env["PYTHONIOENCODING"] = "utf-8"
check = '''from pathlib import Path
import sys
root = Path.cwd().resolve()
assert all(Path(p).resolve().is_relative_to(root) for p in sys.path), sys.path
import streamlit, pandas, plotly, akshare
from streamlit.testing.v1 import AppTest
from screener.provider import Provider
def forbidden(*args, **kwargs):
    raise AssertionError("No automatic network calls")
Provider.call = forbidden
a = AppTest.from_file(str(root / "app.py")).run(timeout=30)
assert not a.exception, a.exception
assert any("暂无行情" in i.value for i in a.info)
a.toggle(key="demo").set_value(True).run(timeout=30)
assert not a.exception, a.exception
assert len(a.dataframe) > 0
print("Relocated isolated runtime + empty app + demo UI: PASS")
'''
subprocess.run([str(python), "-c", check], cwd=folder, env=env, check=True,
               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
with (destination / "server.log").open("w", encoding="utf-8") as log:
    proc = subprocess.Popen([str(python), "-m", "streamlit", "run", "app.py", "--server.headless=true",
                             "--server.address=127.0.0.1", f"--server.port={port}"], cwd=folder, env=env,
                            stdout=log, stderr=log, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        ready = False
        for _ in range(60):
            if proc.poll() is not None:
                break
            try:
                with opener.open(f"http://127.0.0.1:{port}/_stcore/health", timeout=1) as response:
                    if response.status == 200:
                        ready = True
                        break
            except OSError:
                time.sleep(.5)
        assert ready, "Portable HTTP server did not become ready"
    finally:
        proc.terminate()
        proc.wait(timeout=15)
report = {"archive": str(archive_path), "bytes": archive_path.stat().st_size,
          "sha256": hashlib.file_digest(archive_path.open("rb"), "sha256").hexdigest(),
          "relocation": "PASS: Chinese path + spaces", "isolated_runtime": "PASS",
          "ui_empty_and_demo": "PASS", "local_server_health": "PASS",
          "other_physical_pc": "not tested"}
(ROOT / "dist" / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(report, ensure_ascii=True))
