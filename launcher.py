"""Run with either bundled Python or the development environment."""
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
import os

def main():
    root = Path(__file__).resolve().parent
    os.chdir(root)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    print("A-share screener is starting...", flush=True)
    print("Keep this window open. Close it or press Ctrl+C to stop.", flush=True)
    process = subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(root / "app.py"),
                  "--server.address=127.0.0.1", f"--server.port={port}", "--server.headless=true",
                  "--browser.gatherUsageStats=false"], cwd=root)
    try:
        # Never route localhost readiness checks through a configured proxy.
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        for _ in range(60):
            if process.poll() is not None:
                raise RuntimeError("Server stopped before opening. See the error above.")
            try:
                with opener.open(url + "/_stcore/health", timeout=1) as response:
                    if response.status == 200:
                        webbrowser.open(url)
                        print("Open " + url, flush=True)
                        break
            except OSError:
                time.sleep(.5)
        process.wait()
    except KeyboardInterrupt:
        pass
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)

if __name__ == "__main__":
    main()
