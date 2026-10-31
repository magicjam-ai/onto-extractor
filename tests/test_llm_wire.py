"""Checks the request the SDK actually sends, and response parsing, against a local
mock server (no API key or network needed)."""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ontoextract.llm import LLM  # noqa: E402

CAPTURED = {}


def _sse(events):
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        CAPTURED["path"] = self.path
        CAPTURED["headers"] = dict(self.headers)
        CAPTURED["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        body = _sse([
            {"type": "message_start", "message": {
                "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
                "content": [], "stop_reason": None, "stop_sequence": None,
                "usage": {"input_tokens": 100, "output_tokens": 1,
                          "cache_creation_input_tokens": 2000, "cache_read_input_tokens": 0}}},
            {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": '{"classes": [{"name": "order",'}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": ' "definition": "d", "evidence": []}]}'}},
            {"type": "content_block_stop", "index": 0},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
             "usage": {"output_tokens": 500}},
            {"type": "message_stop"},
        ])
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_request_shape_and_parsing(monkeypatch):
    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", f"http://127.0.0.1:{server.server_port}")
    try:
        llm = LLM()
        schema = {"type": "object", "properties": {}, "additionalProperties": False}
        out = llm.json_call("SYS", "the doc", "the task", schema)
    finally:
        server.shutdown()

    assert out == {"classes": [{"name": "order", "definition": "d", "evidence": []}]}
    body = CAPTURED["body"]
    assert body["model"] == "claude-opus-5-5" and body["stream"] is True
    assert body["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in CAPTURED["headers"].get("anthropic-beta", "")
    assert body["output_config"] == {"effort": "high",
                                     "format": {"type": "json_schema", "schema": schema}}
    doc_block, task_block = body["messages"][0]["content"]
    assert doc_block["cache_control"] == {"type": "ephemeral"} and "the doc" in doc_block["text"]
    assert task_block["text"] == "the task"
    assert "thinking" not in body and "temperature" not in body
    assert llm.usage["cache_write"] == 2000 and llm.usage["output"] == 500
    assert round(llm.cost_usd(), 4) == round((100 * 4 + 2000 * 5 + 500 * 20) / 1e6, 4)
