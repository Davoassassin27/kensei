from __future__ import annotations

from kensei.protocol import parse_tool_calls, render_tool_call, render_tool_response, tool_specs


def test_parse_single_call():
    text = '<tool_call>{"name":"shell","arguments":{"cmd":"uname -a"}}</tool_call>'
    calls = parse_tool_calls(text)
    assert len(calls) == 1
    assert calls[0].name == "shell"
    assert calls[0].arguments == {"cmd": "uname -a"}
    assert calls[0].error is None


def test_parse_multiple_calls_with_prose():
    text = (
        "Voy a mirar el estado.\n"
        '<tool_call>{"name":"shell","arguments":{"cmd":"uptime"}}</tool_call>\n'
        '<tool_call>{"name":"recall","arguments":{"query":"btrfs","k":3}}</tool_call>'
    )
    calls = parse_tool_calls(text)
    assert [call.name for call in calls] == ["shell", "recall"]
    assert calls[1].arguments["k"] == 3


def test_parse_fenced_json():
    text = '<tool_call>```json\n{"name":"shell","arguments":{"cmd":"id"}}\n```</tool_call>'
    calls = parse_tool_calls(text)
    assert len(calls) == 1
    assert calls[0].name == "shell"
    assert calls[0].error is None


def test_parse_invalid_json_reports_error():
    calls = parse_tool_calls('<tool_call>{"name": "shell", "arguments": </tool_call>')
    assert len(calls) == 1
    assert calls[0].error
    assert "JSON" in calls[0].error


def test_parse_unknown_tool_reports_error():
    calls = parse_tool_calls('<tool_call>{"name":"rm_rf","arguments":{}}</tool_call>')
    assert len(calls) == 1
    assert calls[0].name == "rm_rf"
    assert calls[0].error and "desconocida" in calls[0].error


def test_parse_missing_name():
    calls = parse_tool_calls('<tool_call>{"arguments":{"cmd":"id"}}</tool_call>')
    assert calls[0].error
    assert "name" in calls[0].error


def test_parse_arguments_not_object():
    calls = parse_tool_calls('<tool_call>{"name":"shell","arguments":"id"}</tool_call>')
    assert calls[0].error
    assert "arguments" in calls[0].error


def test_parse_unclosed_tag():
    calls = parse_tool_calls('<tool_call>{"name":"shell","arguments":{"cmd":"id"}}')
    assert calls[0].error
    assert "tool_call" in calls[0].error


def test_parse_bare_json_fallback():
    calls = parse_tool_calls('{"name":"shell","arguments":{"cmd":"echo kensei"}}')
    assert len(calls) == 1
    assert calls[0].name == "shell"
    assert calls[0].arguments["cmd"] == "echo kensei"
    assert calls[0].error is None


def test_parse_fenced_json_fallback():
    calls = parse_tool_calls('```json\n{"name":"recall","arguments":{"query":"btrfs"}}\n```')
    assert len(calls) == 1
    assert calls[0].name == "recall"
    assert calls[0].error is None


def test_parse_prose_with_json_is_not_a_call():
    text = 'El comando sería {"name":"shell","arguments":{"cmd":"id"}} pero no lo ejecuto.'
    assert parse_tool_calls(text) == []


def test_fallback_ignores_unknown_tool():
    assert parse_tool_calls('{"name":"frobnicate","arguments":{}}') == []


def test_json_fallback_can_be_disabled():
    text = '{"name":"shell","arguments":{"cmd":"echo kensei"}}'
    assert parse_tool_calls(text, allow_json_fallback=False) == []


def test_code_block_fallback_is_opt_in():
    text = "```bash\nsudo btrfs subvolume list /\n```"
    assert parse_tool_calls(text) == []
    calls = parse_tool_calls(text, allow_code_block=True)
    assert len(calls) == 1
    assert calls[0].name == "shell"
    assert calls[0].arguments["cmd"] == "sudo btrfs subvolume list /"


def test_multiple_code_blocks_are_not_auto_selected():
    text = "```bash\nuname -a\n```\n\n```bash\ndf -hT\n```"
    assert parse_tool_calls(text, allow_code_block=True) == []


def test_code_block_with_json_tool_call():
    text = '```json\n{"name":"read_file","arguments":{"path":"/etc/os-release"}}\n```'
    calls = parse_tool_calls(text, allow_code_block=True)
    assert len(calls) == 1
    assert calls[0].name == "read_file"


def test_render_roundtrip():
    text = render_tool_call("shell", {"cmd": "df -hT"})
    calls = parse_tool_calls(text)
    assert calls[0].name == "shell"
    assert calls[0].arguments["cmd"] == "df -hT"
    assert render_tool_response("ok").startswith("<tool_response>")


def test_tool_specs_mentions_all_tools():
    specs = tool_specs()
    for name in ("shell", "read_file", "write_file", "http_get", "recall"):
        assert name in specs
