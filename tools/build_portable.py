"""Bundle the current standalone CPython and installed wheels; no network."""
from pathlib import Path
import json
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]

def build():
    name = "A股筛选器-Windows-x64"
    target = ROOT / "dist" / name
    if target.exists():
        raise SystemExit("Output already exists; choose a fresh build directory instead of overwriting it.")
    target.mkdir(parents=True)
    runtime = target / "runtime"
    base = Path(sys.base_prefix)
    shutil.copytree(base, runtime, ignore=shutil.ignore_patterns("site-packages", "__pycache__", "tests", "test", "Scripts", "include", "libs"))
    packages = Path(sys.prefix) / "Lib" / "site-packages"
    shutil.copytree(packages, runtime / "Lib" / "site-packages", ignore=shutil.ignore_patterns("__pycache__", "tests", "test", "pip", "pip-*.dist-info", "_pytest", "pytest", "pytest-*.dist-info"))
    # Isolate the embedded interpreter from the destination machine's Python and user packages.
    (runtime / "python312._pth").write_text("python312.zip\n.\nDLLs\nLib\nLib/site-packages\n..\nimport site\n", encoding="utf-8")
    for name_ in ("app.py", "launcher.py", "start.bat", "README.md", "requirements.txt", "requirements-lock.txt"):
        shutil.copy2(ROOT / name_, target / name_)
    for name_ in ("screener", ".streamlit"):
        shutil.copytree(ROOT / name_, target / name_, ignore=shutil.ignore_patterns("__pycache__"))
    # A source copy accompanies the runtime so users can keep refining it.
    shutil.copytree(ROOT / "docs", target / "docs")
    for name_ in ("start.bat",):
        path = target / name_
        path.write_bytes(path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\n", "\r\n").encode("utf-8"))
    python = runtime / "python.exe"
    subprocess.run([str(python), "-c", "import sys,streamlit,pandas,plotly,akshare,sqlite3; from screener.core import Filters; print('Portable imports OK', sys.prefix)"], cwd=target, check=True)
    output = ROOT / "dist" / "A-share-screener-Windows-x64.zip"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in target.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                archive.write(path, path.relative_to(target.parent))
    print(json.dumps({"folder": str(target), "archive": str(output), "bytes": output.stat().st_size}, ensure_ascii=True))

if __name__ == "__main__":
    build()
