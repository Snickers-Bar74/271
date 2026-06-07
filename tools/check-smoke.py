from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)


def main() -> int:
    scratch = ROOT / "check-smoke-check"
    if scratch.exists():
        shutil.rmtree(scratch)
    scratch.mkdir()
    try:
        good = scratch / "good.271"
        good.write_text(
            'Make Mood be If true\n'
            '  "bright"\n'
            'Otherwise\n'
            '  "dim"\n'
            'Make Report be Map with\n'
            '  "mood" meaning Mood\n'
            '  "number" meaning jew\n'
            'Expect Item "number" of Report is 271\n',
            encoding="utf-8",
        )
        bad = scratch / "bad.271"
        bad.write_text(
            'Keep Limit be 3\n'
            'Change Limit to 4\n'
            'Make Age be "old" as Int\n'
            'Say Missing Name\n'
            'Use Missing Teaching with 1\n'
            'Stop\n',
            encoding="utf-8",
        )

        good_run = subprocess.run([str(PYTHON), str(ROOT / "271.py"), "check", str(good)], cwd=ROOT, check=True, capture_output=True, text=True)
        assert "check clean" in good_run.stdout

        bad_run = subprocess.run([str(PYTHON), str(ROOT / "271.py"), "check", str(bad)], cwd=ROOT, capture_output=True, text=True)
        assert bad_run.returncode == 1
        messages = bad_run.stderr
        assert "Limit is kept and cannot be changed" in messages
        assert "Age must be Int, but it is String" in messages
        assert "I do not know the name Missing Name" in messages
        assert "I do not know how to use Missing Teaching" in messages
        assert "Stop can only be used inside Repeat" in messages

        privacy = subprocess.run([str(PYTHON), str(ROOT / "271.py"), "check", str(ROOT / "examples" / "privacy-error.271")], cwd=ROOT, capture_output=True, text=True)
        assert privacy.returncode == 1
        assert "Pin of Account is private" in privacy.stderr

        parent = subprocess.run([str(PYTHON), str(ROOT / "271.py"), "check", str(ROOT / "examples" / "parent-error.271")], cwd=ROOT, capture_output=True, text=True)
        assert parent.returncode == 1
        assert "Account does not know how to Missing Label" in parent.stderr
        assert "Parent can only be used inside an object teaching" in parent.stderr

        method_bad = scratch / "method-bad.271"
        method_bad.write_text(
            'Object Account\n'
            '  Has Name as String\n'
            '\n'
            '  Teach Label With using Self and Prefix as String returns String\n'
            '    "{Prefix}: {Name of Self}"\n'
            '\n'
            '  Teach Wrong using Self returns Int\n'
            '    Name of Self\n'
            '\n'
            'Make Person be New Account with Name be "Ada"\n'
            'Say Use Label With of Person with 271\n',
            encoding="utf-8",
        )
        method_bad_run = subprocess.run([str(PYTHON), str(ROOT / "271.py"), "check", str(method_bad)], cwd=ROOT, capture_output=True, text=True)
        assert method_bad_run.returncode == 1
        assert "Wrong must return Int, but it returns String" in method_bad_run.stderr, method_bad_run.stderr
        assert "Prefix must be String, but it is Int" in method_bad_run.stderr, method_bad_run.stderr

        destructure = subprocess.run([str(PYTHON), str(ROOT / "271.py"), "check", str(ROOT / "examples" / "destructure-error.271")], cwd=ROOT, capture_output=True, text=True)
        assert destructure.returncode == 1
        assert "Destructuring needs 2 value(s), but it received 1" in destructure.stderr
        assert "Int cannot be destructured" in destructure.stderr
        assert "Map does not have Grace to destructure" in destructure.stderr
        assert "Player does not have Missing Field to destructure" in destructure.stderr

        maybe = subprocess.run([str(PYTHON), str(ROOT / "271.py"), "check", str(ROOT / "examples" / "maybe-error.271")], cwd=ROOT, capture_output=True, text=True)
        assert maybe.returncode == 1
        assert "Missing may be nothing. Add as Maybe Type." in maybe.stderr
        assert "Present may be nothing. Add as Maybe Type." in maybe.stderr
        assert "Maybe First may be nothing. Add as Maybe Type." in maybe.stderr
        assert "Maybe Message may be nothing. Add as Maybe Type." in maybe.stderr

        result = subprocess.run([str(PYTHON), str(ROOT / "271.py"), "check", str(ROOT / "examples" / "result-error.271")], cwd=ROOT, capture_output=True, text=True)
        assert result.returncode == 1
        assert "This Result is ignored. Use Need, Match, Make, or Ignore Result." in result.stderr
        assert "Ignore Result needs a Result value." in result.stderr

        map_missing = subprocess.run([str(PYTHON), str(ROOT / "271.py"), "check", str(ROOT / "examples" / "map-error.271")], cwd=ROOT, capture_output=True, text=True)
        assert map_missing.returncode == 1
        assert "Score may be nothing. Add as Maybe Type." in map_missing.stderr

        mutation = subprocess.run([str(PYTHON), str(ROOT / "271.py"), "check", str(ROOT / "examples" / "mutation-error.271")], cwd=ROOT, capture_output=True, text=True)
        assert mutation.returncode == 1
        assert "Count must be Int, but it is String." in mutation.stderr
        assert "Name must be String, but it is Int." in mutation.stderr
        assert "Profile does not have Missing." in mutation.stderr

        union = subprocess.run([str(PYTHON), str(ROOT / "271.py"), "check", str(ROOT / "examples" / "union-match-error.271")], cwd=ROOT, capture_output=True, text=True)
        assert union.returncode == 1
        assert "Match on Command must handle Quit Command or use When anything." in union.stderr

        channel = subprocess.run([str(PYTHON), str(ROOT / "271.py"), "check", str(ROOT / "examples" / "channel-error.271")], cwd=ROOT, capture_output=True, text=True)
        assert channel.returncode == 1
        assert "Channel message must be Int, but it is String." in channel.stderr

        collection = subprocess.run([str(PYTHON), str(ROOT / "271.py"), "check", str(ROOT / "examples" / "collection-error.271")], cwd=ROOT, capture_output=True, text=True)
        assert collection.returncode == 1
        assert "List item must be Int, but it is String." in collection.stderr
        assert "Set item must be String, but it is Int." in collection.stderr
        assert "Map key must be String, but it is Int." in collection.stderr
        assert "Map value must be Int, but it is String." in collection.stderr

        field_pattern = subprocess.run([str(PYTHON), str(ROOT / "271.py"), "check", str(ROOT / "examples" / "field-pattern-error.271")], cwd=ROOT, capture_output=True, text=True)
        assert field_pattern.returncode == 1
        assert "Player does not have Missing Field to match" in field_pattern.stderr
        assert "I do not know the type Missing Type" in field_pattern.stderr

        malformed_map = scratch / "malformed-map.271"
        malformed_map.write_text(
            'Make Broken be Map with "name"\n',
            encoding="utf-8",
        )
        malformed_map_run = subprocess.run([str(PYTHON), str(ROOT / "271.py"), "check", str(malformed_map)], cwd=ROOT, capture_output=True, text=True)
        assert malformed_map_run.returncode == 1
        assert "Map entries need the word meaning" in malformed_map_run.stderr

        print("Check smoke test passed.")
        return 0
    finally:
        if scratch.exists():
            shutil.rmtree(scratch)


if __name__ == "__main__":
    raise SystemExit(main())
