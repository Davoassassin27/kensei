from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from kensei import __version__
from kensei.guard import Decision, Guard, Scope
from kensei.ollama import OllamaClient, OllamaError
from kensei.paths import (
    data_dir,
    default_scope_path,
    derived_dir,
    prompt_path,
    root,
    state_dir,
)
from kensei.protocol import ToolCall, parse_tool_calls, tool_specs
from kensei.rag import RagIndex
from kensei.tools import (
    HttpTool,
    ReadFileTool,
    ShellTool,
    ToolResult,
    WriteFileTool,
)


def _configure_windows_console() -> None:
    """Evitar UnicodeEncodeError de cp1252 en la consola de Windows."""
    if os.name != "nt":
        return
    try:
        import ctypes
    except ImportError:
        return
    with contextlib.suppress(Exception):
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    for stream in (sys.stdout, sys.stderr):
        try:
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


_configure_windows_console()
console = Console(legacy_windows=False)
DEFAULT_MODEL = os.environ.get("KENSEI_MODEL", "kensei")
DEFAULT_OLLAMA = os.environ.get("KENSEI_OLLAMA_URL", "http://127.0.0.1:11434")
MAX_TOOL_ROUNDS = 8

RISK_STYLE = {
    "low": "green",
    "medium": "yellow",
    "high": "red",
    "critical": "bold red",
}

FALLBACK_SYSTEM = """Eres Kensei, el operador de terminal de Ronin. Sé breve, verificable y
respetuoso del alcance autorizado. Usá el protocolo <tool_call>{"name":"shell","arguments":{"cmd":"..."}}</tool_call>.
"""


# ---------------------------------------------------------------------------
# Prompt / context
# ---------------------------------------------------------------------------
def load_system_prompt(scope: Scope, rag_enabled: bool) -> str:
    path = prompt_path()
    base = path.read_text(encoding="utf-8") if path.exists() else FALLBACK_SYSTEM
    parts = [
        base,
        "\n\n## Scope activo\n",
        f"- {scope.summary()}\n",
        f"- archivo: {scope.path or '(ninguno)'}\n",
        "- Si un target no está en el scope, no lo toques.\n",
        "\n## Herramientas\n",
        tool_specs(),
    ]
    if rag_enabled:
        parts.append(
            "\n## Memoria\n"
            "El harness puede inyectar `[CONTEXTO RECUPERADO]`. Usalo y citá la fuente. "
            "También podés llamar `recall` para buscar más.\n"
        )
    return "".join(parts)


def user_payload(text: str, rag: RagIndex | None, k: int, show: bool = True) -> str:
    if rag is None:
        return text
    context = rag.context(text, k=k)
    if not context:
        return text
    if show:
        console.print(f"[dim]memoria: recuperando hasta {k} fragmentos[/dim]")
    return f"[CONTEXTO RECUPERADO]\n{context}\n[FIN CONTEXTO]\n\nPregunta: {text}"


# ---------------------------------------------------------------------------
# Guard / tool execution
# ---------------------------------------------------------------------------
def make_guard(scope_path: str | None) -> Guard:
    scope = Scope.load(scope_path)
    return Guard(scope)


def confirm_execution(decision: Decision, args: argparse.Namespace) -> bool:
    if args.yes:
        return True
    if not decision.needs_confirmation and decision.risk == "low":
        return True
    if not sys.stdin.isatty():
        console.print("[red]Se requiere confirmación, pero no hay TTY. Usá --yes en un entorno controlado.[/red]")
        return False
    detail = "\n".join(f"- {reason}" for reason in decision.reasons) or "- sin detalles"
    return Confirm.ask(
        f"[{RISK_STYLE.get(decision.risk, 'white')}]Riesgo {decision.risk}[/]. "
        f"¿Ejecutar?\n{detail}",
        default=False,
    )


def print_decision(decision: Decision, title: str = "Guard") -> None:
    if decision.blocked:
        style = "red"
        state = "BLOQUEADO"
    elif decision.needs_confirmation:
        style = "yellow"
        state = "REQUIERE CONFIRMACIÓN"
    else:
        style = "green"
        state = "PERMITIDO"
    body = [f"[{style}]{state}[/] — riesgo: [{RISK_STYLE.get(decision.risk, 'white')}]{decision.risk}[/]"]
    if decision.targets:
        body.append(f"targets: {', '.join(decision.targets)}")
    if decision.reasons:
        body.append("razones: " + "; ".join(decision.reasons))
    console.print(Panel("\n".join(body), title=title, border_style=style))


def dry(tool: str, detail: str) -> ToolResult:
    return ToolResult(
        True,
        f"DRY-RUN: no se ejecutó {tool}.\n{detail}\n"
        "El operador debe relanzar con --execute (y confirmar si corresponde).",
        meta={"dry_run": True},
    )


def auto_shell_menu(
    command: str,
    decision: Decision,
    guard: Guard,
) -> tuple[str, str, Decision]:
    """Menú humano-en-el-bucle para el modo --auto.

    Devuelve (acción, comando, decisión), con acción en
    {"execute", "dry", "cancel"}.
    """
    if not sys.stdin.isatty():
        console.print("[red]--auto necesita una TTY para preguntar; usá --yes o --execute.[/red]")
        return "cancel", command, decision

    while True:
        print_decision(decision, title=f"auto: {command[:80]}")
        if decision.blocked:
            console.print("[red]Bloqueado por el guard; solo podés editar o cancelar.[/red]")
            choice = Prompt.ask("acción", choices=["2", "4"], default="4")
        else:
            console.print(Text("  [1] ejecutar   [2] editar   [3] dry-run   [4] cancelar"))
            choice = Prompt.ask(
                "acción",
                choices=["1", "2", "3", "4"],
                default="1" if decision.risk == "low" else "2",
            )
        if choice == "1" and not decision.blocked:
            return "execute", command, decision
        if choice == "3" and not decision.blocked:
            return "dry", command, decision
        if choice == "4":
            return "cancel", command, decision

        edited = Prompt.ask("comando", default=command).strip()
        if not edited:
            continue
        command = edited
        decision = guard.check(tool="shell", command=command)


def auto_file_menu(tool: str, value: str, decision: Decision, guard: Guard, field: str) -> tuple[str, str, Decision]:
    if not sys.stdin.isatty():
        console.print("[red]--auto necesita una TTY para preguntar; usá --yes o --execute.[/red]")
        return "cancel", value, decision
    while True:
        print_decision(decision, title=f"auto: {tool} {value[:80]}")
        if decision.blocked:
            console.print("[red]Bloqueado por el guard; solo podés editar o cancelar.[/red]")
            choice = Prompt.ask("acción", choices=["2", "4"], default="4")
        else:
            console.print(Text("  [1] ejecutar   [2] editar   [3] dry-run   [4] cancelar"))
            choice = Prompt.ask("acción", choices=["1", "2", "3", "4"], default="1")
        if choice == "1" and not decision.blocked:
            return "execute", value, decision
        if choice == "3" and not decision.blocked:
            return "dry", value, decision
        if choice == "4":
            return "cancel", value, decision
        edited = Prompt.ask(field, default=value).strip()
        if not edited:
            continue
        value = edited
        if tool == "http_get":
            decision = guard.check(tool="http_get", url=value)
        else:
            decision = guard.check(tool=tool, path=value)


def execute_call(
    call: ToolCall,
    *,
    args: argparse.Namespace,
    guard: Guard,
    shell: ShellTool,
    reader: ReadFileTool,
    writer: WriteFileTool,
    http: HttpTool,
    rag: RagIndex | None,
) -> tuple[ToolResult, Decision | None]:
    if call.error:
        return ToolResult(False, f"ERROR DE PROTOCOLO: {call.error}", exit_code=2), None

    name = call.name
    arguments = call.arguments

    if name == "recall":
        query = str(arguments.get("query", "")).strip()
        if not query:
            return ToolResult(False, "recall requiere query", exit_code=2), None
        if rag is None:
            return ToolResult(False, "no hay índice RAG; corré `kensei index`", exit_code=2), None
        hits = rag.search(query, k=int(arguments.get("k", 6)))
        if not hits:
            return ToolResult(True, "Sin resultados en la memoria local."), None
        lines = []
        for hit in hits:
            lines.append(
                f"[{hit['source']}] {hit['title']} — {hit['url']}\n{str(hit['text'])[:900]}"
            )
        return ToolResult(True, "\n\n---\n\n".join(lines), meta={"hits": len(hits)}), None

    if name == "shell":
        command = str(arguments.get("cmd", "")).strip()
        decision = guard.check(tool="shell", command=command)
        print_decision(decision, title=f"shell: {command[:80]}")
        if decision.blocked:
            audit_record = {"tool": name, "command": command, "decision": decision.__dict__}
            guard.audit.write({**audit_record, "result": "blocked"})
            return ToolResult(
                False,
                "BLOQUEADO por el guard:\n- " + "\n- ".join(decision.reasons),
                exit_code=126,
            ), decision

        auto_handled = bool(getattr(args, "auto", False) and not args.yes)
        if auto_handled:
            action, command, decision = auto_shell_menu(command, decision, guard)
            arguments["cmd"] = command
            audit_record = {"tool": name, "command": command, "decision": decision.__dict__}
            if action == "cancel":
                guard.audit.write({**audit_record, "result": "cancelled"})
                return ToolResult(False, "Cancelado por el operador.", exit_code=126), decision
            if action == "dry":
                guard.audit.write({**audit_record, "result": "dry-run"})
                return dry("shell", f"$ {command}"), decision
        else:
            audit_record = {"tool": name, "command": command, "decision": decision.__dict__}
            if not confirm_execution(decision, args):
                guard.audit.write({**audit_record, "result": "cancelled"})
                return ToolResult(False, "Cancelado por el operador.", exit_code=126), decision

        if not args.execute:
            guard.audit.write({**audit_record, "result": "dry-run"})
            return dry("shell", f"$ {command}"), decision
        result = shell.run(
            command,
            cwd=arguments.get("cwd"),
            timeout=int(arguments.get("timeout", 120)),
        )
        guard.audit.write(
            {
                **audit_record,
                "result": "ok" if result.ok else "error",
                "exit_code": result.exit_code,
                "duration_ms": result.duration_ms,
            }
        )
        return result, decision

    if name == "http_get":
        url = str(arguments.get("url", "")).strip()
        decision = guard.check(tool="http_get", url=url)
        print_decision(decision, title=f"http_get: {url[:80]}")
        if decision.blocked:
            guard.audit.write({"tool": name, "url": url, "decision": decision.__dict__, "result": "blocked"})
            return ToolResult(False, "BLOQUEADO por el guard:\n- " + "\n- ".join(decision.reasons), 126), decision
        auto_handled = bool(getattr(args, "auto", False) and not args.yes)
        if auto_handled:
            action, url, decision = auto_file_menu("http_get", url, decision, guard, "URL")
            arguments["url"] = url
            if action == "cancel":
                guard.audit.write({"tool": name, "url": url, "decision": decision.__dict__, "result": "cancelled"})
                return ToolResult(False, "Cancelado por el operador.", 126), decision
            if action == "dry":
                guard.audit.write({"tool": name, "url": url, "decision": decision.__dict__, "result": "dry-run"})
                return dry("http_get", f"GET {url}"), decision
        elif not confirm_execution(decision, args):
            guard.audit.write({"tool": name, "url": url, "decision": decision.__dict__, "result": "cancelled"})
            return ToolResult(False, "Cancelado por el operador.", 126), decision
        if not args.execute:
            guard.audit.write({"tool": name, "url": url, "decision": decision.__dict__, "result": "dry-run"})
            return dry("http_get", f"GET {url}"), decision
        result = http.run(url)
        guard.audit.write(
            {"tool": name, "url": url, "decision": decision.__dict__, "result": "ok" if result.ok else "error"}
        )
        return result, decision

    if name == "read_file":
        path = str(arguments.get("path", "")).strip()
        decision = guard.check(tool="read_file", path=path)
        print_decision(decision, title=f"read_file: {path[:80]}")
        if decision.blocked:
            return ToolResult(False, "BLOQUEADO por el guard.", 126), decision
        auto_handled = bool(getattr(args, "auto", False) and not args.yes)
        if auto_handled:
            action, path, decision = auto_file_menu("read_file", path, decision, guard, "ruta")
            arguments["path"] = path
            if action == "cancel":
                return ToolResult(False, "Cancelado por el operador.", 126), decision
            if action == "dry":
                return dry("read_file", f"leer {path}"), decision
        elif not confirm_execution(decision, args):
            return ToolResult(False, "Cancelado por el operador.", 126), decision
        if not args.execute:
            return dry("read_file", f"leer {path}"), decision
        result = reader.run(path)
        guard.audit.write(
            {"tool": name, "path": path, "decision": decision.__dict__, "result": "ok" if result.ok else "error"}
        )
        return result, decision

    if name == "write_file":
        path = str(arguments.get("path", "")).strip()
        content = str(arguments.get("content", ""))
        decision = guard.check(tool="write_file", path=path)
        print_decision(decision, title=f"write_file: {path[:80]}")
        if decision.blocked:
            return ToolResult(False, "BLOQUEADO por el guard.", 126), decision
        auto_handled = bool(getattr(args, "auto", False) and not args.yes)
        if auto_handled:
            action, path, decision = auto_file_menu("write_file", path, decision, guard, "ruta")
            arguments["path"] = path
            if action == "cancel":
                return ToolResult(False, "Cancelado por el operador.", 126), decision
            if action == "dry":
                return dry("write_file", f"escribir {len(content)} caracteres en {path}"), decision
        elif not confirm_execution(decision, args):
            return ToolResult(False, "Cancelado por el operador.", 126), decision
        if not args.execute:
            return dry("write_file", f"escribir {len(content)} caracteres en {path}"), decision
        result = writer.run(path, content)
        guard.audit.write(
            {"tool": name, "path": path, "decision": decision.__dict__, "result": "ok" if result.ok else "error"}
        )
        return result, decision

    return ToolResult(False, f"herramienta no implementada: {name}", 2), None


# ---------------------------------------------------------------------------
# Conversation loop
# ---------------------------------------------------------------------------
def trim_history(messages: list[dict[str, Any]], limit: int = 40) -> list[dict[str, Any]]:
    if len(messages) <= limit:
        return messages
    system = messages[0]
    tail = messages[-limit:]
    while tail and tail[0].get("role") != "user":
        tail.pop(0)
    return [system] + tail


def run_conversation(
    client: OllamaClient,
    messages: list[dict[str, Any]],
    *,
    args: argparse.Namespace,
    guard: Guard,
    rag: RagIndex | None,
) -> str | None:
    shell = ShellTool(workspace=Path.cwd(), dry_run=not args.execute)
    reader = ReadFileTool(workspace=Path.cwd())
    writer = WriteFileTool(workspace=Path.cwd())
    http = HttpTool()

    final = ""
    for round_index in range(1, args.max_tool_rounds + 1):
        messages[:] = trim_history(messages)
        try:
            content = client.chat(
                messages,
                options={
                    "temperature": args.temperature,
                    "top_p": 0.9,
                    "num_ctx": args.num_ctx,
                },
            )
        except OllamaError as exc:
            console.print(Panel(str(exc), title="Ollama", border_style="red"))
            return None
        messages.append({"role": "assistant", "content": content})
        first_turn = not any(message.get("role") == "tool" for message in messages)
        calls = parse_tool_calls(
            content,
            allow_code_block=args.allow_code_blocks and first_turn,
            allow_json_fallback=first_turn,
        )

        if calls:
            console.print(Markdown(content.split("<tool_call>")[0].strip() or "_usando herramienta…_"))
            for call in calls:
                if call.error:
                    console.print(Panel(Text(f"{call.error}\n{call.raw[:500]}"), title="Protocolo", border_style="red"))
                    messages.append({"role": "tool", "content": f"ERROR DE PROTOCOLO: {call.error}"})
                    continue
                console.print(
                    Syntax(
                        json.dumps({"name": call.name, "arguments": call.arguments}, ensure_ascii=False, indent=2),
                        "json",
                        theme="monokai",
                        line_numbers=False,
                    )
                )
                result, _decision = execute_call(
                    call,
                    args=args,
                    guard=guard,
                    shell=shell,
                    reader=reader,
                    writer=writer,
                    http=http,
                    rag=rag,
                )
                messages.append({"role": "tool", "content": result.output})
                title = f"{call.name} -> {'ok' if result.ok else 'error'}"
                console.print(
                    Panel(
                        Text(result.output),
                        title=title,
                        border_style="green" if result.ok else "red",
                        subtitle=f"exit={result.exit_code} {result.duration_ms}ms",
                    )
                )
            if round_index == args.max_tool_rounds:
                console.print("[red]Límite de tool-calls alcanzado. Corto el bucle.[/red]")
                break
            continue

        final = content
        console.print(Markdown(content))
        break

    if not args.execute:
        console.print(
            "[dim]Modo dry-run: no se ejecutó nada. Para dar manos: `--execute` "
            "(y confirmá cada paso).[/dim]"
        )
    return final


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------
def cmd_chat(args: argparse.Namespace) -> int:
    guard = make_guard(args.scope)
    rag = None if args.no_rag else RagIndex()
    if rag is not None and rag.count() == 0:
        console.print("[yellow]RAG vacío. El chat sigue sin memoria; corré `kensei index`.[/yellow]")
        rag = None
    system = load_system_prompt(guard.scope, rag is not None)
    client = OllamaClient(base_url=args.base_url, model=args.model, timeout=args.timeout)
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]

    console.print(
        Panel(
            f"Kensei {__version__} · modelo [bold]{args.model}[/] · "
            f"execute={'yes' if args.execute else 'no'} · scope={guard.scope.engagement}\n"
            "Escribí tu tarea. `salir` para terminar.",
            title="Kensei",
            border_style="cyan",
        )
    )
    while True:
        try:
            text = console.input("[bold cyan]kensei>[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return 0
        if text.lower() in {"salir", "exit", "quit", ":q"}:
            return 0
        if not text:
            continue
        messages.append({"role": "user", "content": user_payload(text, rag, args.rag_k)})
        if run_conversation(client, messages, args=args, guard=guard, rag=rag) is None:
            return 1
        console.print()


def cmd_ask(args: argparse.Namespace) -> int:
    if not args.prompt:
        console.print("[red]Falta el prompt.[/red]")
        return 2
    guard = make_guard(args.scope)
    rag = None if args.no_rag else RagIndex()
    if rag is not None and rag.count() == 0:
        rag = None
    system = load_system_prompt(guard.scope, rag is not None)
    client = OllamaClient(base_url=args.base_url, model=args.model, timeout=args.timeout)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_payload(args.prompt, rag, args.rag_k)},
    ]
    if run_conversation(client, messages, args=args, guard=guard, rag=rag) is None:
        return 1
    return 0


def cmd_auto(args: argparse.Namespace) -> int:
    if not args.prompt:
        if not sys.stdin.isatty():
            console.print("[red]Falta el prompt y no hay TTY.[/red]")
            return 2
        args.prompt = Prompt.ask("kensei(auto)›")
    if not args.prompt.strip():
        console.print("[red]Prompt vacío.[/red]")
        return 2
    args.auto = True
    args.execute = True
    console.print(
        Panel(
            "Modo auto: el modelo propone; vos elegís ejecutar, editar, dry-run o cancelar.",
            title="Kensei // auto",
            border_style="yellow",
        )
    )
    return cmd_ask(args)


def cmd_index(args: argparse.Namespace) -> int:
    index = RagIndex(args.db)
    try:
        count = index.build(args.chunks, reset=True)
    except FileNotFoundError as exc:
        console.print(f"[red]{exc}[/red]")
        return 1
    console.print(f"[green]Índice listo:[/] {count} chunks en {index.db_path}")
    return 0


def cmd_recall(args: argparse.Namespace) -> int:
    index = RagIndex(args.db)
    hits = index.search(args.query, k=args.k)
    if not hits:
        console.print("[yellow]Sin resultados.[/yellow]")
        return 0
    table = Table(title=f"Memoria: {args.query}", show_lines=True)
    table.add_column("fuente", style="cyan", no_wrap=True)
    table.add_column("título", style="bold")
    table.add_column("fragmento")
    for hit in hits:
        snippet = " ".join(str(hit["text"]).split())[:500]
        table.add_row(Text(str(hit["source"])), Text(str(hit["title"])), Text(snippet))
    console.print(table)
    return 0


def cmd_scope(args: argparse.Namespace) -> int:
    scope = Scope.load(args.scope)
    console.print(Panel(scope.summary(), title="Scope", border_style="cyan"))
    if scope.notes:
        console.print(Panel(scope.notes, title="Notas"))
    if not scope.authorized:
        console.print(
            f"[yellow]Sin autorización. Copiá {root() / 'config' / 'scope.example.yaml'} "
            f"a {default_scope_path()} y editá targets.[/yellow]"
        )
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    checks: list[tuple[str, str, str]] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append((name, status, detail))

    add("python", "PASS", sys.version.split()[0])
    add("kensei_home", "PASS", str(root()))
    add("prompt", "PASS" if prompt_path().exists() else "WARN", str(prompt_path()))

    chunks = derived_dir("chunks.jsonl")
    add("chunks", "PASS" if chunks.exists() else "WARN", str(chunks))
    index = RagIndex()
    add("rag", "PASS" if index.count() > 0 else "WARN", f"{index.count()} chunks en {index.db_path}")

    scope_path = Path(args.scope) if args.scope else default_scope_path()
    try:
        scope = Scope.load(scope_path)
        status = "PASS" if scope.authorized else "WARN"
        add("scope", status, f"{scope_path} — {scope.summary()}")
    except (TypeError, ValueError) as exc:
        add("scope", "FAIL", str(exc))

    client = OllamaClient(base_url=args.base_url, model=args.model)
    try:
        models = client.tags()
        add("ollama", "PASS", f"{args.base_url} ({len(models)} modelos)")
        names = {str(m.get("name", "")).split(":")[0] for m in models}
        add("model", "PASS" if args.model.split(":")[0] in names else "WARN", args.model)
    except OllamaError as exc:
        add("ollama", "FAIL", str(exc))

    try:
        guard = Guard(scope)
        blocked = guard.check(tool="shell", command="nmap -sV 8.8.8.8")
        allowed = guard.check(tool="shell", command="systemctl status sshd")
        global_scope = scope.authorized and any(
            str(net) in {"0.0.0.0/0", "::/0"} for net in scope.cidrs
        )
        if global_scope:
            add("guard_public", "WARN", "scope global: no hay targets fuera de alcance por diseño")
        else:
            add("guard_public", "PASS" if blocked.blocked else "FAIL", "; ".join(blocked.reasons))
        add("guard_readonly", "PASS" if allowed.allowed else "FAIL", "; ".join(allowed.reasons) or "ok")
    except Exception as exc:  # noqa: BLE001 - doctor no debe romper
        add("guard", "FAIL", str(exc))

    add("audit", "PASS", str(state_dir() / "audit.jsonl"))
    add("data", "PASS" if data_dir().exists() else "WARN", str(data_dir()))

    table = Table(title="Kensei doctor", show_lines=True)
    table.add_column("check", style="bold")
    table.add_column("status")
    table.add_column("detalle")
    colors = {"PASS": "green", "WARN": "yellow", "FAIL": "red"}
    for name, status, detail in checks:
        table.add_row(name, f"[{colors.get(status, 'white')}]{status}[/]", detail)
    console.print(table)

    return 1 if any(status == "FAIL" for _, status, _ in checks) else 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kensei", description="Kensei, el SLM de terminal de Ronin.")
    parser.add_argument("--version", action="version", version=f"kensei {__version__}")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--model", default=DEFAULT_MODEL, help=f"modelo Ollama (default: {DEFAULT_MODEL})")
    common.add_argument("--base-url", default=DEFAULT_OLLAMA, help="URL de Ollama")
    common.add_argument("--scope", default=None, help="ruta a scope.yaml")
    common.add_argument("--execute", action="store_true", help="ejecutar herramientas (sin esto es dry-run)")
    common.add_argument("--yes", action="store_true", help="confirmar automáticamente (solo entornos controlados)")
    common.add_argument("--temperature", type=float, default=0.2)
    common.add_argument("--num-ctx", type=int, default=8192)
    common.add_argument("--timeout", type=float, default=300.0, help="timeout de Ollama en segundos")
    common.add_argument(
        "--allow-code-blocks",
        action="store_true",
        help="aceptar un bloque ```bash como tool-call (modelos base)",
    )
    common.add_argument("--max-tool-rounds", type=int, default=MAX_TOOL_ROUNDS)

    rag = argparse.ArgumentParser(add_help=False)
    rag.add_argument("--no-rag", action="store_true", help="no inyectar memoria documental")
    rag.add_argument("--rag-k", type=int, default=5)

    sub = parser.add_subparsers(dest="command", required=True)

    chat = sub.add_parser("chat", parents=[common, rag], help="sesión interactiva")
    chat.set_defaults(func=cmd_chat)

    ask = sub.add_parser("ask", parents=[common, rag], help="una pregunta y salir")
    ask.add_argument("prompt", nargs="?", help="tarea o pregunta")
    ask.set_defaults(func=cmd_ask)

    auto = sub.add_parser(
        "auto",
        parents=[common, rag],
        help="agente con human-in-the-loop: propone, editás y confirmás",
    )
    auto.add_argument("prompt", nargs="?", help="tarea o pregunta")
    auto.set_defaults(func=cmd_auto)

    index = sub.add_parser("index", help="construir el índice FTS5")
    index.add_argument("--chunks", default=None)
    index.add_argument("--db", default=None)
    index.set_defaults(func=cmd_index)

    recall = sub.add_parser("recall", help="buscar en la memoria documental")
    recall.add_argument("query")
    recall.add_argument("--k", type=int, default=6)
    recall.add_argument("--db", default=None)
    recall.set_defaults(func=cmd_recall)

    scope = sub.add_parser("scope", help="mostrar el scope activo")
    scope.add_argument("--scope", default=None)
    scope.set_defaults(func=cmd_scope)

    doctor = sub.add_parser("doctor", help="diagnóstico del harness")
    doctor.add_argument("--model", default=DEFAULT_MODEL)
    doctor.add_argument("--base-url", default=DEFAULT_OLLAMA)
    doctor.add_argument("--scope", default=None)
    doctor.set_defaults(func=cmd_doctor)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        console.print("\n[dim]interrumpido[/dim]")
        return 130
    except (TypeError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
