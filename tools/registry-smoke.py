from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)
PORT = "2711"


def main() -> int:
    project = ROOT / "remote-install-check"
    if project.exists():
        shutil.rmtree(project)
    project.mkdir()
    shutil.copy(ROOT / "271.py", project / "271.py")
    shutil.copy(ROOT / "271.cmd", project / "271.cmd")
    (project / "use-package.271").write_text(
        'Bring Package "friendly-tools/greetings.271" names Friendly Greeting\n'
        'Say Use Friendly Greeting with "Remote"\n',
        encoding="utf-8",
    )
    server = subprocess.Popen(
        [str(PYTHON), str(ROOT / "271.py"), "serve-registry", PORT],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        time.sleep(1.5)
        add = subprocess.run(
            [str(PYTHON), str(project / "271.py"), "add", "friendly-tools", "from", f"http://127.0.0.1:{PORT}"],
            cwd=project,
            text=True,
            capture_output=True,
            check=True,
        )
        run = subprocess.run(
            [str(PYTHON), str(project / "271.py"), "run", "use-package.271"],
            cwd=project,
            text=True,
            capture_output=True,
            check=True,
        )
        assert "Installed friendly-tools" in add.stdout
        assert "Hello Remote, from a package" in run.stdout
        print("Registry smoke test passed.")
        return 0
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
        if project.exists():
            shutil.rmtree(project)


if __name__ == "__main__":
    raise SystemExit(main())
