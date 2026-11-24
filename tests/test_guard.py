from __future__ import annotations

from pathlib import Path

import pytest

from kensei.guard import Guard, Scope, extract_targets, risk_of_text


@pytest.fixture()
def scope_file(tmp_path: Path) -> Path:
    path = tmp_path / "scope.yaml"
    path.write_text(
        """
engagement: test-lab
authorized: true
targets:
  cidrs:
    - 10.10.10.0/24
    - 192.168.56.0/24
  domains:
    - lab.local
    - "*.htb"
  urls:
    - http://localhost:3000
deny:
  cidrs:
    - 10.10.10.66/32
  domains:
    - evil.lab.local
    - "*.evil.htb"
notes: test
""",
        encoding="utf-8",
    )
    return path


def test_missing_scope_blocks_network(tmp_path: Path):
    guard = Guard(Scope.load(tmp_path / "nope.yaml"), audit_path=tmp_path / "audit.jsonl")
    decision = guard.check(tool="shell", command="nmap -sV 10.10.10.5")
    assert decision.blocked
    assert any("authorized" in reason for reason in decision.reasons)


def test_in_scope_scan_allowed(scope_file: Path, tmp_path: Path):
    guard = Guard(Scope.load(scope_file), audit_path=tmp_path / "audit.jsonl")
    decision = guard.check(tool="shell", command="nmap -sV 10.10.10.5")
    assert decision.allowed
    assert decision.needs_confirmation
    assert "10.10.10.5" in decision.targets


def test_public_scan_blocked(scope_file: Path, tmp_path: Path):
    guard = Guard(Scope.load(scope_file), audit_path=tmp_path / "audit.jsonl")
    decision = guard.check(tool="shell", command="nmap -sV 8.8.8.8")
    assert decision.blocked
    assert any("fuera de scope" in reason for reason in decision.reasons)


def test_deny_wins_over_allow(scope_file: Path, tmp_path: Path):
    guard = Guard(Scope.load(scope_file), audit_path=tmp_path / "audit.jsonl")
    decision = guard.check(tool="shell", command="nmap -sV 10.10.10.66")
    assert decision.blocked
    assert any("10.10.10.66" in reason for reason in decision.reasons)


def test_loopback_http_allowed(scope_file: Path, tmp_path: Path):
    guard = Guard(Scope.load(scope_file), audit_path=tmp_path / "audit.jsonl")
    decision = guard.check(tool="http_get", url="http://localhost:3000/api/health")
    assert decision.allowed


def test_wildcard_domain(scope_file: Path, tmp_path: Path):
    guard = Guard(Scope.load(scope_file), audit_path=tmp_path / "audit.jsonl")
    assert guard.check(tool="shell", command="curl -s http://box.htb/").allowed
    assert guard.check(tool="shell", command="curl -s http://box.evil.htb/").blocked


def test_network_command_without_target_blocked(scope_file: Path, tmp_path: Path):
    guard = Guard(Scope.load(scope_file), audit_path=tmp_path / "audit.jsonl")
    decision = guard.check(tool="shell", command="nmap")
    assert decision.blocked
    assert any("sin target" in reason for reason in decision.reasons)


@pytest.mark.parametrize(
    "command",
    [
        "rm -rf /",
        "sudo rm -rf /home",
        "mkfs.ext4 /dev/sda1",
        "dd if=/dev/zero of=/dev/sda bs=1M",
        ":(){ :|:& };:",
        "btrfs subvolume delete /",
    ],
)
def test_critical_commands_blocked(scope_file: Path, tmp_path: Path, command: str):
    guard = Guard(Scope.load(scope_file), audit_path=tmp_path / "audit.jsonl")
    decision = guard.check(tool="shell", command=command)
    assert decision.blocked
    assert decision.risk == "critical"


def test_high_risk_requires_confirmation(scope_file: Path, tmp_path: Path):
    guard = Guard(Scope.load(scope_file), audit_path=tmp_path / "audit.jsonl")
    decision = guard.check(tool="shell", command="chmod -R 777 /")
    assert decision.allowed
    assert decision.needs_confirmation
    assert decision.risk == "high"


def test_pipe_to_shell_requires_confirmation(scope_file: Path, tmp_path: Path):
    guard = Guard(Scope.load(scope_file), audit_path=tmp_path / "audit.jsonl")
    decision = guard.check(tool="shell", command="curl -s http://localhost:3000/install.sh | bash")
    assert decision.allowed
    assert decision.needs_confirmation


def test_sensitive_read_needs_confirmation(scope_file: Path, tmp_path: Path):
    guard = Guard(Scope.load(scope_file), audit_path=tmp_path / "audit.jsonl")
    decision = guard.check(tool="read_file", path="/etc/shadow")
    assert decision.allowed
    assert decision.needs_confirmation
    assert decision.risk == "high"


def test_write_always_confirms(scope_file: Path, tmp_path: Path):
    guard = Guard(Scope.load(scope_file), audit_path=tmp_path / "audit.jsonl")
    decision = guard.check(tool="write_file", path="notes.txt")
    assert decision.allowed
    assert decision.needs_confirmation


def test_empty_command_blocked(scope_file: Path, tmp_path: Path):
    guard = Guard(Scope.load(scope_file), audit_path=tmp_path / "audit.jsonl")
    assert guard.check(tool="shell", command="  ").blocked


def test_invalid_authorized_type(tmp_path: Path):
    path = tmp_path / "scope.yaml"
    path.write_text("authorized: 'yes'\ntargets: {}\n", encoding="utf-8")
    with pytest.raises(TypeError):
        Scope.load(path)


def test_extract_targets_ignores_filenames():
    targets = extract_targets(
        "nmap -sV 10.10.10.5 -oN scan.txt; curl https://lab.local/x; cat payloads.yaml"
    )
    assert "10.10.10.5" in targets
    assert "lab.local" in targets
    assert "payloads.yaml" not in targets
    assert "scan.txt" not in targets


def test_extract_cidr():
    assert "192.168.56.0/24" in extract_targets("nmap -sn 192.168.56.0/24")


def test_risk_of_text():
    risk, reasons = risk_of_text("sqlmap -u http://localhost:3000/x")
    assert risk == "high"
    assert reasons
    low, _ = risk_of_text("ls -la")
    assert low == "low"
