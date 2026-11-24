from __future__ import annotations

import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
MAX_OUTPUT = 24_000
MAX_FILE = 200_000
MAX_HTTP = 100_000


@dataclass
class ToolResult:
    ok: bool
    output: str
    exit_code: int = 0
    duration_ms: int = 0
    meta: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "output": self.output,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "meta": self.meta,
        }


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def clip(text: str, limit: int = MAX_OUTPUT) -> str:
    text = strip_ansi(text)
    if len(text) <= limit:
        return text
    half = limit // 2
    return (
        text[:half]
        + f"\n\n[... {len(text) - limit} caracteres truncados ...]\n\n"
        + text[-half:]
    )


def _within(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def safe_write_path(workspace: Path, raw: str) -> Path:
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = workspace / candidate
    candidate = candidate.resolve()
    if not _within(workspace, candidate):
        raise ValueError(f"write_file fuera del workspace: {candidate}")
    return candidate


class ShellTool:
    def __init__(self, workspace: Path, dry_run: bool = True):
        self.workspace = workspace.resolve()
        self.dry_run = dry_run

    def run(self, cmd: str, cwd: str | None = None, timeout: int = 120) -> ToolResult:
        started = time.monotonic()
        if self.dry_run:
            return ToolResult(
                ok=True,
                output=f"DRY-RUN: no se ejecutó.\n$ {cmd}",
                exit_code=0,
                duration_ms=int((time.monotonic() - started) * 1000),
                meta={"dry_run": True, "cmd": cmd},
            )

        workdir = Path(cwd).expanduser() if cwd else self.workspace
        if not workdir.is_absolute():
            workdir = self.workspace / workdir
        if not workdir.exists():
            return ToolResult(False, f"cwd no existe: {workdir}", exit_code=2)

        env = os.environ.copy()
        env.setdefault("NO_COLOR", "1")
        env.setdefault("TERM", "dumb")
        env["KENSEI"] = "1"

        if os.name == "nt":
            argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd]
        else:
            argv = ["/bin/bash", "-lc", cmd]

        try:
            proc = subprocess.run(
                argv,
                check=False,
                cwd=str(workdir),
                capture_output=True,
                text=True,
                errors="replace",
                timeout=max(1, min(timeout, 600)),
                env=env,
            )
            output = (proc.stdout or "") + (proc.stderr or "")
            code = proc.returncode
            ok = code == 0
        except subprocess.TimeoutExpired as exc:
            out = exc.stdout or ""
            err = exc.stderr or ""
            if isinstance(out, bytes):
                out = out.decode("utf-8", "replace")
            if isinstance(err, bytes):
                err = err.decode("utf-8", "replace")
            output = f"{out}{err}\n[timeout después de {timeout}s]"
            code = 124
            ok = False
        except FileNotFoundError as exc:
            output = f"ejecutable no encontrado: {exc}"
            code = 127
            ok = False

        return ToolResult(
            ok=ok,
            output=clip(output),
            exit_code=code,
            duration_ms=int((time.monotonic() - started) * 1000),
            meta={"cwd": str(workdir), "cmd": cmd},
        )


class ReadFileTool:
    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()

    def run(self, path: str) -> ToolResult:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.workspace / candidate
        candidate = candidate.resolve()
        if not candidate.exists():
            return ToolResult(False, f"archivo no existe: {candidate}", exit_code=2)
        if not candidate.is_file():
            return ToolResult(False, f"no es un archivo regular: {candidate}", exit_code=2)
        try:
            text = candidate.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return ToolResult(False, f"no se pudo leer {candidate}: {exc}", exit_code=1)
        return ToolResult(
            True,
            clip(text, MAX_FILE),
            meta={"path": str(candidate), "bytes": candidate.stat().st_size},
        )


class WriteFileTool:
    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()

    def run(self, path: str, content: str) -> ToolResult:
        try:
            candidate = safe_write_path(self.workspace, path)
        except ValueError as exc:
            return ToolResult(False, str(exc), exit_code=2)
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            candidate.write_text(content, encoding="utf-8")
        except OSError as exc:
            return ToolResult(False, f"no se pudo escribir {candidate}: {exc}", exit_code=1)
        return ToolResult(
            True,
            f"escrito: {candidate} ({len(content)} caracteres)",
            meta={"path": str(candidate), "chars": len(content)},
        )


class HttpTool:
    def __init__(self, timeout: float = 20.0):
        self.timeout = timeout

    def run(self, url: str) -> ToolResult:
        started = time.monotonic()
        try:
            with (
                httpx.Client(
                    timeout=self.timeout,
                    follow_redirects=False,
                    headers={"User-Agent": "Kensei/0.1 (Ronin local authorized testing)"},
                ) as client,
                client.stream("GET", url) as response,
            ):
                chunks: list[bytes] = []
                received = 0
                for chunk in response.iter_bytes():
                    chunks.append(chunk)
                    received += len(chunk)
                    if received >= MAX_HTTP:
                        break
                raw = b"".join(chunks)
                status = response.status_code
                final_url = str(response.url)
                header_items = list(response.headers.items())
        except httpx.HTTPError as exc:
            return ToolResult(
                False,
                f"error HTTP: {exc}",
                exit_code=1,
                duration_ms=int((time.monotonic() - started) * 1000),
            )

        text = raw.decode("utf-8", errors="replace")
        if received >= MAX_HTTP:
            text += "\n\n[... respuesta truncada ...]"
        headers = "\n".join(f"{key}: {value}" for key, value in header_items)
        body = clip(text, MAX_HTTP)
        output = f"HTTP {status}\n{headers}\n\n{body}"
        ok = 200 <= status < 400
        return ToolResult(
            ok=ok,
            output=output,
            exit_code=0 if ok else 1,
            duration_ms=int((time.monotonic() - started) * 1000),
            meta={"url": final_url, "status": status},
        )
