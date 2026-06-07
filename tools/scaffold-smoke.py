from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)


def run_command(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


def main() -> int:
    project = ROOT / "scaffold-smoke-check"
    if project.exists():
        shutil.rmtree(project)
    try:
        created = run_command([str(PYTHON), str(ROOT / "271.py"), "new", str(project)], ROOT)
        assert "Created twohundredseventyone project" in created.stdout
        assert (project / "271.py").exists()
        assert (project / "271.cmd").exists()
        assert (project / "app.271").exists()
        assert (project / "tests" / "app.271").exists()

        doctor = run_command([str(PYTHON), str(project / "271.py"), "doctor"], project)
        assert "Doctor found the toolchain ready." in doctor.stdout

        app = run_command([str(PYTHON), str(project / "271.py"), "run", "app.271"], project)
        assert "Hello from scaffold-smoke-check" in app.stdout
        assert "jew is 271" in app.stdout

        check = run_command([str(PYTHON), str(project / "271.py"), "check", "."], project)
        assert "check clean" in check.stdout

        tests = run_command([str(PYTHON), str(project / "271.py"), "test", "tests"], project)
        assert "All 1 test file(s) passed." in tests.stdout

        lint = run_command([str(PYTHON), str(project / "271.py"), "lint", "."], project)
        assert "look readable" in lint.stdout

        compile_result = run_command([str(PYTHON), str(project / "271.py"), "compile", "app.271"], project)
        assert "Compiled 1 file(s)" in compile_result.stdout

        emit = run_command([str(PYTHON), str(project / "271.py"), "emit-python", "app.271"], project)
        assert "Emitted app.271" in emit.stdout
        emitted = run_command([str(PYTHON), str(project / "emitted" / "app.py")], project)
        assert "Hello from scaffold-smoke-check" in emitted.stdout

        pack = run_command([str(PYTHON), str(project / "271.py"), "pack", "app.271"], project)
        assert "Packed app.271" in pack.stdout
        packed = run_command([str(PYTHON), str(project / "dist" / "app.pyz")], project)
        assert "Hello from scaffold-smoke-check" in packed.stdout

        print("Scaffold smoke test passed.")
        return 0
    finally:
        if project.exists():
            shutil.rmtree(project)


if __name__ == "__main__":
    raise SystemExit(main())
