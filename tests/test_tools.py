from __future__ import annotations

from pathlib import Path

from kensei.tools import (
    HttpTool,
    ReadFileTool,
    ShellTool,
    WriteFileTool,
    clip,
    strip_ansi,
)


def test_strip_ansi():
    assert strip_ansi("\x1b[31mhola\x1b[0m") == "hola"


def test_clip_keeps_head_and_tail():
    text = "a" * 1000 + "b" * 1000
    result = clip(text, limit=200)
    assert "truncados" in result
    assert result.startswith("a")
    assert result.endswith("b")


def test_shell_dry_run(tmp_path: Path):
    result = ShellTool(tmp_path, dry_run=True).run("uname -a")
    assert result.ok
    assert "DRY-RUN" in result.output
    assert result.meta["dry_run"] is True


def test_shell_real_echo(tmp_path: Path):
    result = ShellTool(tmp_path, dry_run=False).run("echo kensei")
    assert result.ok
    assert "kensei" in result.output
    assert result.exit_code == 0


def test_shell_missing_cwd(tmp_path: Path):
    result = ShellTool(tmp_path, dry_run=False).run("echo x", cwd=str(tmp_path / "nope"))
    assert not result.ok
    assert "cwd no existe" in result.output


def test_write_and_read_inside_workspace(tmp_path: Path):
    writer = WriteFileTool(tmp_path)
    result = writer.run("notes/hello.txt", "hola kensei")
    assert result.ok
    reader = ReadFileTool(tmp_path)
    read = reader.run("notes/hello.txt")
    assert read.ok
    assert read.output == "hola kensei"


def test_write_blocks_escape(tmp_path: Path):
    workspace = tmp_path / "ws"
    workspace.mkdir()
    result = WriteFileTool(workspace).run("../escape.txt", "x")
    assert not result.ok
    assert "fuera del workspace" in result.output
    assert not (tmp_path / "escape.txt").exists()


def test_read_missing_file(tmp_path: Path):
    result = ReadFileTool(tmp_path).run("nope.txt")
    assert not result.ok
    assert "no existe" in result.output


def test_http_local_invalid_port():
    result = HttpTool(timeout=1.0).run("http://127.0.0.1:1/")
    assert not result.ok
    assert "error HTTP" in result.output
