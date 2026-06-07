from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)


def main() -> int:
    run = subprocess.run(
        [str(PYTHON), str(ROOT / "271.py"), "run", str(ROOT / "examples" / "trace-error.271")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert run.returncode == 1
    stderr = run.stderr
    assert "Plain English error: Cannot divide by zero." in stderr
    assert "Trace:" in stderr
    assert "Number over Zero" in stderr
    assert "while using Divide" in stderr
    assert "while using Wrap Divide" in stderr
    assert "Say Use Wrap Divide with 271" in stderr

    subprocess.run([str(PYTHON), str(ROOT / "271.py"), "compile", str(ROOT / "examples" / "trace-error.271")], cwd=ROOT, check=True, capture_output=True, text=True)
    compiled = subprocess.run(
        [str(PYTHON), str(ROOT / "271.py"), "run-compiled", str(ROOT / ".271-cache" / "trace-error.271c")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert compiled.returncode == 1
    assert "Trace:" in compiled.stderr
    assert "trace-error.271 line 3" in compiled.stderr

    channel = subprocess.run(
        [str(PYTHON), str(ROOT / "271.py"), "run", str(ROOT / "examples" / "channel-runtime-error.271")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert channel.returncode == 1
    assert "Channel message must be Int" in channel.stderr
    assert "while using Send Later" in channel.stderr

    collection = subprocess.run(
        [str(PYTHON), str(ROOT / "271.py"), "run", str(ROOT / "examples" / "collection-runtime-error.271")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert collection.returncode == 1
    assert "List item must be Int" in collection.stderr
    assert "while using Add Later" in collection.stderr

    print("Trace smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
