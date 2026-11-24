from __future__ import annotations

import ipaddress
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from kensei.paths import default_scope_path, ensure_parent, state_dir

RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}

# (regex, risk, reason)
DESTRUCTIVE_RULES: tuple[tuple[re.Pattern[str], str, str], ...] = tuple(
    (
        re.compile(pattern, re.IGNORECASE | re.MULTILINE),
        risk,
        reason,
    )
    for pattern, risk, reason in [
        (r"\brm\s+(?:-[a-zA-Z]*[rf][a-zA-Z]*\s+)+(?:/|/\*|~|\$HOME|/home)(?:\s|$)", "critical", "rm recursivo sobre raíz o home"),
        (r"\bmkfs(?:\.[a-z0-9]+)?\s+", "critical", "formateo de filesystem"),
        (r"\bwipefs\s+", "critical", "borrado de firmas de filesystem"),
        (r"\bdd\b[^\n]*\bof\s*=\s*/dev/(?:sd|nvme|vd|mmcblk|disk)", "critical", "escritura directa sobre un disco"),
        (r"\bshred\b[^\n]*/dev/", "critical", "shred sobre un dispositivo"),
        (r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:", "critical", "fork bomb"),
        (r"\b(?:btrfs\s+subvolume\s+(?:delete|destroy))\s+/(?:\s|$)", "critical", "borrado del subvolumen raíz"),
        (r"\bchmod\s+-R\s+777\s+/(?:\s|$)", "high", "chmod 777 recursivo sobre /"),
        (r"\bchown\s+-R\s+[^\s]+\s+/(?:\s|$)", "high", "chown recursivo sobre /"),
        (r"\bsnapper\s+(?:delete|rollback)\b", "high", "borrado/rollback de snapshots"),
        (r"\bpacman\s+-Rdd\b|\bpacman\s+-R\s+--nodeps\b", "high", "desinstalación ignorando dependencias"),
        (r"\bsystemctl\s+(?:disable|mask)\s+(?:sshd|networkmanager|systemd-resolved|ollama|docker|ufw)\b", "high", "deshabilitar un servicio crítico"),
        (r"\biptables\s+-F\b|\bnft\s+flush\s+ruleset\b|\bufw\s+disable\b", "high", "vaciar el firewall"),
        (r"\bhistory\s+-c\b|\btruncate\s+-s\s*0\b|\bfind\s+/\s+-delete\b", "high", "borrado de rastros o archivos"),
        (r"\bgit\s+clean\s+-[a-zA-Z]*[fdx]", "high", "git clean destructivo"),
        (r"\bdocker\s+system\s+prune\s+-a\b|\bdocker\s+volume\s+prune\b", "high", "prune de Docker"),
        (r"\bkubectl\s+delete\b|\bterraform\s+destroy\b", "high", "borrado de infraestructura"),
        (r"\b(?:curl|wget)\b[^\n|]*\|\s*(?:bash|sh|zsh)\b", "high", "pipe-to-shell"),
        (r"\b(?:cat|tar|base64|history|env|find)\b[^\n|]*\|\s*(?:curl|wget|nc|ncat|socat|ssh)\b", "high", "posible exfiltración de datos"),
        (r"\b(?:nc|ncat|socat)\b[^\n]*\s-e\s+", "high", "reverse shell con -e"),
        (r"\b(?:mount|umount|fdisk|parted|sgdisk|gdisk)\b", "high", "cambio de discos/montajes"),
        (r"\b(?:iptables|nft|ufw)\b", "high", "cambio de firewall"),
    ]
)

SENSITIVE_PATH_RE = re.compile(
    r"(?:/etc/(?:shadow|gshadow|sudoers)|\.ssh/(?:id_|config|known_hosts)|"
    r"\.aws/credentials|\.kube/config|\.docker/config\.json|\.gnupg/|"
    r"(?:^|/)\.env(?:$|\.)|credentials|secrets?\.(?:json|ya?ml|txt)|"
    r"/root/)",
    re.IGNORECASE,
)

NETWORK_TOOL_RE = re.compile(
    r"\b(?:nmap|masscan|zmap|ffuf|gobuster|feroxbuster|dirb|nikto|nuclei|sqlmap|"
    r"hydra|medusa|patator|netexec|nxc|crackmapexec|smbclient|smbmap|rpcclient|"
    r"enum4linux|impacket-[a-z0-9_-]+|responder|bettercap|msfconsole|msfvenom|"
    r"wpscan|joomscan|droopescan|whatweb|wafw00f|subfinder|amass|assetfinder|"
    r"httpx|naabu|dnsx|katana|gau|waybackurls|curl|wget|ssh|scp|sftp|rsync|"
    r"nc|ncat|socat|telnet|ftp)\b",
    re.IGNORECASE,
)

AGGRESSIVE_TOOL_RE = re.compile(
    r"\b(?:sqlmap|hydra|medusa|msfconsole|msfvenom|nuclei|responder|bettercap|"
    r"impacket-[a-z0-9_-]+|netexec|nxc|crackmapexec)\b",
    re.IGNORECASE,
)

SERVICE_CHANGE_RE = re.compile(
    r"\b(?:systemctl\s+(?:restart|stop|start|reload|enable|disable)|"
    r"service\s+\S+\s+(?:restart|stop|start)|kill(?:all)?|pkill)\b",
    re.IGNORECASE,
)

URL_RE = re.compile(r"https?://[^\s'\"<>`]+", re.IGNORECASE)
IPV4_RE = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w./])")
CIDR_RE = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}/\d{1,2}(?![\w.])")
DOMAIN_RE = re.compile(
    r"(?<![\w.-])(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}(?![\w.-])"
)

FILE_EXTENSIONS = {
    "md", "py", "sh", "json", "yaml", "yml", "txt", "html", "htm", "js", "ts",
    "tsx", "jsx", "go", "rs", "c", "h", "cpp", "hpp", "log", "conf", "toml",
    "lock", "git", "png", "jpg", "jpeg", "gif", "svg", "webp", "pdf", "zip",
    "gz", "xz", "zst", "tar", "exe", "dll", "so", "bin", "db", "sqlite",
}


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value]
    raise ValueError(f"se esperaba una lista, se recibió {type(value).__name__}")


def _parse_networks(values: Iterable[str], field_name: str) -> list[Any]:
    result = []
    for value in values:
        try:
            result.append(ipaddress.ip_network(str(value), strict=False))
        except ValueError as exc:
            raise ValueError(f"{field_name}: red inválida {value!r}: {exc}") from exc
    return result


@dataclass
class Scope:
    engagement: str = "unset"
    authorized: bool = False
    cidrs: list[Any] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)
    deny_cidrs: list[Any] = field(default_factory=list)
    deny_domains: list[str] = field(default_factory=list)
    notes: str = ""
    path: str | None = None

    @classmethod
    def load(cls, path: str | Path | None = None) -> Scope:
        scope_path = Path(path).expanduser() if path else default_scope_path()
        if not scope_path.exists():
            return cls(path=str(scope_path))
        raw = yaml.safe_load(scope_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise TypeError(f"{scope_path}: el scope debe ser un objeto YAML")
        targets = raw.get("targets") or {}
        deny = raw.get("deny") or {}
        if not isinstance(targets, dict) or not isinstance(deny, dict):
            raise TypeError(f"{scope_path}: targets/deny deben ser objetos")
        authorized = raw.get("authorized", False)
        if not isinstance(authorized, bool):
            raise TypeError(f"{scope_path}: authorized debe ser true/false, no {authorized!r}")
        return cls(
            engagement=str(raw.get("engagement", "unset")),
            authorized=authorized,
            cidrs=_parse_networks(_as_list(targets.get("cidrs")), "targets.cidrs"),
            domains=[d.lower().rstrip(".") for d in _as_list(targets.get("domains"))],
            urls=[u.rstrip("/") for u in _as_list(targets.get("urls"))],
            deny_cidrs=_parse_networks(_as_list(deny.get("cidrs")), "deny.cidrs"),
            deny_domains=[d.lower().rstrip(".") for d in _as_list(deny.get("domains"))],
            notes=str(raw.get("notes", "")),
            path=str(scope_path),
        )

    def summary(self) -> str:
        parts = [
            f"engagement={self.engagement}",
            f"authorized={'yes' if self.authorized else 'no'}",
            f"cidrs={[str(n) for n in self.cidrs] or '[]'}",
            f"domains={self.domains or '[]'}",
            f"urls={self.urls or '[]'}",
        ]
        return " ".join(parts)

    # -- network checks -------------------------------------------------
    def _denied_ip(self, ip: Any) -> bool:
        return any(ip in net for net in self.deny_cidrs)

    def _denied_domain(self, host: str) -> bool:
        return any(_match_domain(host, pattern) for pattern in self.deny_domains)

    def is_ip_allowed(self, value: str | Any) -> bool:
        ip = ipaddress.ip_address(value) if isinstance(value, str) else value
        if self._denied_ip(ip):
            return False
        if ip.is_loopback:
            return True
        return any(ip in net for net in self.cidrs)

    def is_network_allowed(self, value: str) -> bool:
        try:
            net = ipaddress.ip_network(value, strict=False)
        except ValueError:
            return False
        for denied in self.deny_cidrs:
            if net.subnet_of(denied) or denied.subnet_of(net):
                return False
        if net.is_loopback:
            return True
        return any(net.subnet_of(allowed) for allowed in self.cidrs)

    def is_domain_allowed(self, host: str) -> bool:
        host = host.lower().rstrip(".")
        if self._denied_domain(host):
            return False
        if host == "localhost":
            return True
        try:
            return self.is_ip_allowed(host)
        except ValueError:
            pass
        return any(_match_domain(host, pattern) for pattern in self.domains)

    def is_url_allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        host = parsed.hostname
        if not host:
            return False
        if self._denied_domain(host) or self._denied_ip_safe(host):
            return False
        normalized = url.rstrip("/")
        if any(normalized == allowed or normalized.startswith(allowed + "/") for allowed in self.urls):
            return True
        return self.is_domain_allowed(host)

    def _denied_ip_safe(self, host: str) -> bool:
        try:
            return self._denied_ip(ipaddress.ip_address(host))
        except ValueError:
            return False

    def is_target_allowed(self, target: str) -> bool:
        target = target.strip()
        if not target:
            return False
        if "://" in target:
            return self.is_url_allowed(target)
        if "/" in target:
            return self.is_network_allowed(target)
        try:
            return self.is_ip_allowed(target)
        except ValueError:
            return self.is_domain_allowed(target)


def _match_domain(host: str, pattern: str) -> bool:
    host = host.lower().rstrip(".")
    pattern = pattern.lower().rstrip(".")
    if not pattern:
        return False
    if pattern == "*":
        return True
    if pattern.startswith("*."):
        suffix = pattern[1:]  # ".htb"
        return host.endswith(suffix) and host != suffix.lstrip(".")
    return host == pattern or host.endswith("." + pattern)


def extract_targets(text: str) -> list[str]:
    """Extract URLs, CIDRs, IPs and domains from a shell command.

    Domains that look like filenames (``payloads.txt``) are ignored.
    """
    targets: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        value = value.strip().rstrip(".,;:)]}")
        if value and value not in seen:
            seen.add(value)
            targets.append(value)

    for url in URL_RE.findall(text):
        add(url)
    for cidr in CIDR_RE.findall(text):
        try:
            ipaddress.ip_network(cidr, strict=False)
            add(cidr)
        except ValueError:
            pass
    for ip in IPV4_RE.findall(text):
        try:
            ipaddress.ip_address(ip)
            add(ip)
        except ValueError:
            pass
    for domain in DOMAIN_RE.findall(text):
        lowered = domain.lower()
        if lowered.rsplit(".", 1)[-1] in FILE_EXTENSIONS:
            continue
        try:
            ipaddress.ip_address(lowered)
            continue
        except ValueError:
            pass
        add(lowered)
    return targets


def _max_risk(*risks: str) -> str:
    return max(risks, key=lambda r: RISK_ORDER.get(r, 0))


def risk_of_text(text: str) -> tuple[str, list[str]]:
    """Classify a command for dataset metadata (no scope enforcement)."""
    risk = "low"
    reasons: list[str] = []
    for pattern, level, reason in DESTRUCTIVE_RULES:
        if pattern.search(text):
            risk = _max_risk(risk, level)
            reasons.append(reason)
    if NETWORK_TOOL_RE.search(text):
        risk = _max_risk(risk, "medium")
        reasons.append("comando de red")
    if AGGRESSIVE_TOOL_RE.search(text):
        risk = _max_risk(risk, "high")
        reasons.append("herramienta ofensiva")
    return risk, sorted(set(reasons))


@dataclass
class Decision:
    allowed: bool
    needs_confirmation: bool
    risk: str
    reasons: list[str] = field(default_factory=list)
    targets: list[str] = field(default_factory=list)
    scope: str = ""

    @property
    def blocked(self) -> bool:
        return not self.allowed


class Guard:
    def __init__(self, scope: Scope | None = None, audit_path: str | Path | None = None):
        self.scope = scope or Scope.load()
        self.audit = AuditLog(audit_path)

    def check(
        self,
        *,
        tool: str = "shell",
        command: str | None = None,
        path: str | None = None,
        url: str | None = None,
    ) -> Decision:
        if tool == "shell":
            return self._check_shell(command or "")
        if tool == "http_get":
            return self._check_http(url or "")
        if tool == "read_file":
            return self._check_read(path or "")
        if tool == "write_file":
            return self._check_write(path or "")
        if tool == "recall":
            return Decision(True, False, "low", ["consulta local"], [], self.scope.summary())
        return Decision(False, False, "high", [f"herramienta desconocida: {tool}"], [], self.scope.summary())

    # -- per-tool checks -------------------------------------------------
    def _check_shell(self, command: str) -> Decision:
        if not command.strip():
            return Decision(False, False, "low", ["comando vacío"], [], self.scope.summary())

        risk = "low"
        reasons: list[str] = []
        allowed = True
        needs_confirmation = False

        for pattern, level, reason in DESTRUCTIVE_RULES:
            if pattern.search(command):
                risk = _max_risk(risk, level)
                reasons.append(reason)
                if level == "critical":
                    allowed = False
                else:
                    needs_confirmation = True

        if SENSITIVE_PATH_RE.search(command):
            risk = _max_risk(risk, "high")
            needs_confirmation = True
            reasons.append("lectura de ruta sensible")

        targets = extract_targets(command)
        is_network = bool(NETWORK_TOOL_RE.search(command)) or bool(URL_RE.search(command))
        if is_network:
            risk = _max_risk(risk, "high" if AGGRESSIVE_TOOL_RE.search(command) else "medium")
            needs_confirmation = True
            reasons.append("comando de red")
            if not self.scope.authorized:
                allowed = False
                reasons.append("scope.authorized no está en true")
            if not targets:
                allowed = False
                reasons.append("comando de red sin target explícito")
            for target in targets:
                if not self.scope.is_target_allowed(target):
                    allowed = False
                    reasons.append(f"target fuera de scope: {target}")

        if SERVICE_CHANGE_RE.search(command):
            risk = _max_risk(risk, "medium")
            needs_confirmation = True
            reasons.append("cambio de servicio/proceso")

        return Decision(
            allowed=allowed,
            needs_confirmation=needs_confirmation and allowed,
            risk=risk if allowed else _max_risk(risk, "high"),
            reasons=sorted(set(reasons)),
            targets=targets,
            scope=self.scope.summary(),
        )

    def _check_http(self, url: str) -> Decision:
        if not url:
            return Decision(False, False, "medium", ["URL vacía"], [], self.scope.summary())
        targets = extract_targets(url)
        reasons = ["GET HTTP"]
        allowed = self.scope.authorized
        if not allowed:
            reasons.append("scope.authorized no está en true")
        if not targets:
            allowed = False
            reasons.append("URL sin host")
        else:
            for target in targets:
                if not self.scope.is_target_allowed(target):
                    allowed = False
                    reasons.append(f"target fuera de scope: {target}")
        return Decision(allowed, allowed, "medium" if allowed else "high", reasons, targets, self.scope.summary())

    def _check_read(self, path: str) -> Decision:
        if not path:
            return Decision(False, False, "low", ["ruta vacía"], [], self.scope.summary())
        if SENSITIVE_PATH_RE.search(path):
            return Decision(
                True,
                True,
                "high",
                ["lectura de ruta sensible"],
                [],
                self.scope.summary(),
            )
        return Decision(True, False, "low", ["lectura local"], [], self.scope.summary())

    def _check_write(self, path: str) -> Decision:
        if not path:
            return Decision(False, False, "low", ["ruta vacía"], [], self.scope.summary())
        return Decision(
            True,
            True,
            "medium",
            ["escritura de archivo"],
            [],
            self.scope.summary(),
        )


class AuditLog:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else state_dir() / "audit.jsonl"

    def write(self, record: dict[str, Any]) -> None:
        ensure_parent(self.path)
        payload = {
            "ts": datetime.now(UTC).isoformat(),
            **record,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
