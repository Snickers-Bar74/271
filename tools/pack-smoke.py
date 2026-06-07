from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)


def main() -> int:
    scratch = ROOT / "pack-smoke-check"
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir()
    try:
        source = scratch / "packed.271"
        source.write_text('Make Number be 271\nSay "packed {Number}"\n', encoding="utf-8")
        subprocess.run([str(PYTHON), str(ROOT / "271.py"), "pack", str(source)], cwd=ROOT, check=True, capture_output=True, text=True)
        packed = ROOT / "dist" / "packed.pyz"
        assert packed.exists()
        source.unlink()
        run = subprocess.run([str(PYTHON), str(packed)], cwd=ROOT, check=True, capture_output=True, text=True)
        assert "packed 271" in run.stdout
        print("Pack smoke test passed.")
        return 0
    finally:
        if scratch.exists():
            shutil.rmtree(scratch)


if __name__ == "__main__":
    raise SystemExit(main())
