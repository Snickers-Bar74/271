from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PYTHON = Path(sys.executable)


def frame(payload: dict) -> bytes:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8") + body


def read_frame(process: subprocess.Popen) -> dict:
    headers = {}
    while True:
        line = process.stdout.readline()
        if not line:
            raise RuntimeError("The LSP server stopped before sending a response.")
        text = line.decode("utf-8").strip()
        if not text:
            break
        key, value = text.split(":", 1)
        headers[key.lower()] = value.strip()
    body = process.stdout.read(int(headers["content-length"]))
    return json.loads(body.decode("utf-8"))


def main() -> int:
    process = subprocess.Popen(
        [str(PYTHON), str(ROOT / "271.py"), "lsp"],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdin is not None

    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {
                "textDocument": {
                    "uri": "file:///broken.271",
                    "languageId": "twohundredseventyone",
                    "version": 1,
                    "text": "let Number be 3\nSay   Number\n",
                }
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "textDocument/formatting",
            "params": {"textDocument": {"uri": "file:///broken.271"}},
        },
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "textDocument/completion",
            "params": {
                "textDocument": {"uri": "file:///broken.271"},
                "position": {"line": 1, "character": 0},
            },
        },
        {"jsonrpc": "2.0", "id": 4, "method": "shutdown", "params": None},
        {"jsonrpc": "2.0", "method": "exit", "params": None},
    ]
    for message in messages:
        process.stdin.write(frame(message))
        process.stdin.flush()

    initialize = read_frame(process)
    diagnostics = read_frame(process)
    formatting = read_frame(process)
    completions = read_frame(process)
    shutdown = read_frame(process)

    process.wait(timeout=5)

    assert initialize["result"]["serverInfo"]["name"] == "twohundredseventyone"
    assert diagnostics["method"] == "textDocument/publishDiagnostics"
    assert diagnostics["params"]["diagnostics"]
    assert "Use Make instead of let" in diagnostics["params"]["diagnostics"][0]["message"]
    assert formatting["result"][0]["newText"] == "let Number be 3\nSay Number\n"
    labels = [item["label"] for item in completions["result"]["items"]]
    assert "Make" in labels
    assert "Teach" in labels
    assert shutdown["result"] is None
    print("LSP smoke test passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
