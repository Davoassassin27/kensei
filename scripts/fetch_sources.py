from __future__ import annotations

import argparse
import html as html_lib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from _common import ROOT, load_yaml, write_jsonl
from bs4 import BeautifulSoup

SOURCES_FILE = ROOT / "config" / "sources.yaml"
RAW = ROOT / "data" / "raw"
USER_AGENT = "Kensei/0.1 (Ronin local research; https://github.com/davosoler/work-os)"


def remove_tree(path: Path) -> None:
    """Borrar un árbol aunque Windows haya marcado archivos como read-only."""

    def on_error(func: Any, target: str, _exc: Any) -> None:
        os.chmod(target, stat.S_IWRITE)
        func(target)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=on_error)
    else:
        shutil.rmtree(path, onerror=on_error)


def run_git(args: list[str], cwd: Path | None = None) -> None:
    result = subprocess.run(
        ["git", "-c", "core.longpaths=true", *args],
        cwd=str(cwd) if cwd else None,
        check=False,
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} falló:\n{result.stderr.strip()}")


def clone_source(name: str, cfg: dict[str, Any], force: bool) -> None:
    dest = RAW / name
    repo = cfg["repo"]
    ref = cfg.get("ref", "main")
    includes = [str(pattern) for pattern in cfg.get("include", [])]
    if dest.exists() and (dest / ".git").exists() and not force:
        print(f"[skip] {name}: ya existe {dest} (usá --force para reclonar)")
        return
    if dest.exists() and force:
        print(f"[force] borrando {dest}")
        remove_tree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"[git] {name} ← {repo} ({ref})")

    sparse = bool(includes)
    clone_args = ["clone", "--depth", "1", "--branch", ref, "--single-branch"]
    if sparse:
        # Sin blobs ni checkout completo: en Windows las rutas de imágenes
        # de HackTricks superan MAX_PATH y rompen el clone normal.
        clone_args += ["--filter=blob:none", "--no-checkout"]
    clone_args += [repo, str(dest)]
    run_git(clone_args)

    if sparse:
        run_git(["-C", str(dest), "sparse-checkout", "init", "--no-cone"])
        run_git(["-C", str(dest), "sparse-checkout", "set", "--no-cone", *includes])
        run_git(["-C", str(dest), "checkout"])
        print(f"[git] {name}: sparse checkout de {', '.join(includes)}")


def wiki_request(params: dict[str, str]) -> dict[str, Any]:
    url = f"https://wiki.archlinux.org/api.php?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def html_to_text(raw_html: str) -> str:
    """Convertir el HTML de Arch Wiki a texto con encabezados y code fences."""
    soup = BeautifulSoup(raw_html, "lxml")
    root = soup.select_one("div.mw-parser-output") or soup

    for selector in (
        "script",
        "style",
        ".mw-editsection",
        ".archwiki-template-meta-related-articles",
        ".navbox",
        ".catlinks",
        ".printfooter",
    ):
        for tag in root.select(selector):
            tag.decompose()

    codes: dict[str, str] = {}
    for index, pre in enumerate(root.find_all("pre")):
        code = pre.get_text("\n").strip("\n")
        if not code.strip():
            continue
        key = f"@@KENSEI_CODE_{index}@@"
        codes[key] = f"```\n{code}\n```"
        pre.replace_with(key)

    for heading in root.find_all(re.compile(r"^h[1-6]$")):
        level = int(heading.name[1])
        title = heading.get_text(" ", strip=True)
        heading.replace_with(f"\n\n{'#' * level} {title}\n\n")

    for item in root.find_all("li"):
        item.insert(0, "- ")

    text = root.get_text("\n")
    text = html_lib.unescape(text)
    for key, code in codes.items():
        text = text.replace(key, code)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fetch_archwiki(cfg: dict[str, Any], limit: int | None, force: bool) -> None:
    dest = RAW / "archwiki"
    dest.mkdir(parents=True, exist_ok=True)
    index_path = dest / "index.jsonl"
    if index_path.exists() and not force:
        print(f"[skip] archwiki: ya existe {index_path} (usá --force)")
        return

    pages_file = ROOT / cfg["pages_file"]
    titles = []
    for line in pages_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            titles.append(line)
    # dedupe preservando orden
    titles = list(dict.fromkeys(titles))
    if limit:
        titles = titles[:limit]
    print(f"[wiki] {len(titles)} páginas curadas")

    index: list[dict[str, Any]] = []
    missing: list[str] = []

    for position, requested in enumerate(titles, start=1):
        params = {
            "action": "parse",
            "format": "json",
            "formatversion": "2",
            "prop": "text",
            "redirects": "1",
            "page": requested,
        }
        try:
            data = wiki_request(params)
        except (urllib.error.URLError, TimeoutError) as exc:
            print(f"[wiki] error en {requested}: {exc}")
            missing.append(requested)
            continue

        if "error" in data:
            missing.append(requested)
            continue
        page = data.get("parse") or {}
        title = str(page.get("title") or requested).strip()
        raw_html = str(page.get("text") or "")
        text = html_to_text(raw_html)
        if len(text) < 300:
            missing.append(title)
            continue

        safe = "".join(c if c.isalnum() or c in "._- " else "_" for c in title).strip()
        safe = safe.replace(" ", "_")[:150] or "page"
        path = dest / f"{safe}.txt"
        path.write_text(text, encoding="utf-8")
        index.append(
            {
                "source": "archwiki",
                "title": title,
                "pageid": page.get("pageid"),
                "path": str(path.relative_to(ROOT)),
                "url": f"https://wiki.archlinux.org/title/{urllib.parse.quote(title.replace(' ', '_'))}",
                "license": cfg["license"],
                "chars": len(text),
            }
        )
        if position % 5 == 0 or position == len(titles):
            print(f"[wiki] {position}/{len(titles)}")
        time.sleep(0.2)

    write_jsonl(index_path, index)
    print(f"[wiki] {len(index)} páginas guardadas; {len(missing)} faltantes/short")
    if missing:
        print("[wiki] faltantes: " + ", ".join(missing[:20]))


def main() -> int:
    parser = argparse.ArgumentParser(description="Descargar fuentes de Kensei.")
    parser.add_argument("--sources-file", default=str(SOURCES_FILE))
    parser.add_argument("--only", nargs="*", default=None, help="archwiki hacktricks payloads thr tldr gtfobins")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--limit", type=int, default=None, help="límite de páginas ArchWiki")
    args = parser.parse_args()

    config = load_yaml(args.sources_file)
    sources = config.get("sources", {})
    selected = args.only or list(sources.keys())
    unknown = [name for name in selected if name not in sources]
    if unknown:
        print(f"fuentes desconocidas: {unknown}", file=sys.stderr)
        return 2

    RAW.mkdir(parents=True, exist_ok=True)
    for name in selected:
        cfg = sources[name]
        kind = cfg.get("kind")
        try:
            if kind == "archwiki":
                fetch_archwiki(cfg, args.limit, args.force)
            elif kind == "git":
                clone_source(name, cfg, args.force)
            elif kind == "local":
                print(f"[skip] {name}: fuente local, no se descarga")
            else:
                print(f"[skip] {name}: kind desconocido {kind!r}")
        except Exception as exc:  # noqa: BLE001 - CLI de descarga
            print(f"[error] {name}: {exc}", file=sys.stderr)
            return 1
    print("[done] fuentes en", RAW)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
