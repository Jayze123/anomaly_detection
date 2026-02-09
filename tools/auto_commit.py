from __future__ import annotations

import subprocess
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

REPO_ROOT = Path(__file__).resolve().parents[1]
IGNORE_DIRS = {
    ".git",
    "artifacts",
    "outputs",
    "__pycache__",
    ".venv",
}


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, cwd=str(REPO_ROOT), check=False)


def _should_ignore(path: Path) -> bool:
    parts = set(path.parts)
    return bool(parts & IGNORE_DIRS)


def _regenerate_docs() -> None:
    _run(["python", "tools/generate_docs.py"])


def _git_commit_all() -> None:
    _run(["git", "add", "."])
    _run(["git", "commit", "-m", f"Auto update {time.strftime('%Y-%m-%d %H:%M:%S')}"])
    _run(["git", "push"])


class ChangeHandler(FileSystemEventHandler):
    def __init__(self):
        self._last = 0.0

    def on_any_event(self, event):
        now = time.time()
        if now - self._last < 2.0:
            return
        self._last = now
        path = Path(event.src_path)
        if _should_ignore(path):
            return
        _regenerate_docs()
        _git_commit_all()


def main() -> int:
    observer = Observer()
    handler = ChangeHandler()
    observer.schedule(handler, str(REPO_ROOT), recursive=True)
    observer.start()
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
