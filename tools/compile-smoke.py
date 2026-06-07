from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)


def main() -> int:
    scratch = ROOT / "compile-smoke-check"
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir()
    try:
        source = scratch / "standalone.271"
        source.write_text('Make Number be 271\nSay "compiled {Number}"\n', encoding="utf-8")
        subprocess.run([str(PYTHON), str(ROOT / "271.py"), "compile", str(source)], cwd=ROOT, check=True, capture_output=True, text=True)
        compiled = ROOT / ".271-cache" / "standalone.271c"
        assert compiled.exists()
        artifact = json.loads(compiled.read_text(encoding="utf-8"))
        assert "program" in artifact
        source.unlink()
        run = subprocess.run([str(PYTHON), str(ROOT / "271.py"), "run-compiled", str(compiled)], cwd=ROOT, check=True, capture_output=True, text=True)
        assert "compiled 271" in run.stdout
        print("Compile smoke test passed.")
        return 0
    finally:
        if scratch.exists():
            shutil.rmtree(scratch)


if __name__ == "__main__":
    raise SystemExit(main())
