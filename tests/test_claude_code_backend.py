"""ClaudeCodeLLM against a fake `claude` executable (no CLI login or network needed)."""

import json
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ontoextract.llm import ClaudeCodeLLM, LLMError  # noqa: E402

FAKE = """#!/usr/bin/env python3
import json, sys
args = sys.argv[1:]
prompt = sys.stdin.read()
json.dump({{"args": args, "prompt": prompt}}, open({log!r}, "w"))
schema = json.loads(args[args.index("--json-schema") + 1])
ok = "FAIL" not in prompt
print(json.dumps({{
    "type": "result", "subtype": "success" if ok else "error_max_structured_output_retries",
    "is_error": not ok, "result": "boom" if not ok else "",
    "structured_output": {{"echo": sorted(schema["properties"])}} if ok else None,
    "total_cost_usd": 0.25,
    "usage": {{"input_tokens": 3, "output_tokens": 400, "cache_creation_input_tokens": 1500,
               "cache_read_input_tokens": 0}}}}))
"""


@pytest.fixture
def fake_claude(tmp_path):
    log = tmp_path / "call.json"
    exe = tmp_path / "claude"
    exe.write_text(FAKE.format(log=str(log)))
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    return exe, log


def test_call_flags_prompt_and_usage(fake_claude):
    exe, log = fake_claude
    llm = ClaudeCodeLLM(binary=str(exe), retries=0)
    schema = {"type": "object", "properties": {"classes": {}}, "additionalProperties": False}
    assert llm.json_call("SYS", "the doc", "the task", schema) == {"echo": ["classes"]}

    call = json.loads(log.read_text())
    args = call["args"]
    assert args[0] == "-p" and args[args.index("--system-prompt") + 1] == "SYS"
    assert args[args.index("--model") + 1] == "claude-opus-5-5"
    assert args[args.index("--effort") + 1] == "high"
    assert args[args.index("--tools") + 1] == "" and "--strict-mcp-config" in args
    assert json.loads(args[args.index("--json-schema") + 1]) == schema
    assert call["prompt"] == "<document>\nthe doc\n</document>\n\nthe task"
    assert llm.usage["output"] == 400 and llm.usage["cache_write"] == 1500
    assert llm.cost_usd() == 0.25


def test_error_result_raises(fake_claude):
    exe, _ = fake_claude
    llm = ClaudeCodeLLM(binary=str(exe), retries=0)
    with pytest.raises(LLMError, match="boom"):
        llm.json_call("SYS", "FAIL", "task", {"type": "object", "properties": {}})
