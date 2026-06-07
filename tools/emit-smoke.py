from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)


def main() -> int:
    cases = {
        "emitted-demo": ["emitted total 10"],
        "jew": ["271"],
        "emitted-advanced": [
            "Ada?",
            "3",
            "ready? True",
            "15",
            "5",
            "loop 3",
            "some Ada",
            "count 3",
            "ok",
            "Plain English error: bad",
            "finished",
        ],
    }
    for name, expected_lines in cases.items():
        subprocess.run([str(PYTHON), str(ROOT / "271.py"), "emit-python", str(ROOT / "examples" / f"{name}.271")], cwd=ROOT, check=True, capture_output=True, text=True)
        emitted = ROOT / "emitted" / f"{name}.py"
        assert emitted.exists()
        text = emitted.read_text(encoding="utf-8")
        assert "import runner271" not in text
        run = subprocess.run([str(PYTHON), str(emitted)], cwd=ROOT, check=True, capture_output=True, text=True)
        for expected in expected_lines:
            assert expected in run.stdout, run.stdout
    print("Emit smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
