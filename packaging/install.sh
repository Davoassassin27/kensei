#!/usr/bin/env bash
# Instala Kensei en un rootfs Linux (workOS/Ronin o host de desarrollo).
# Uso:
#   sudo bash packaging/install.sh --prefix /usr/local --source /ruta/a/kensei
set -Eeuo pipefail

PREFIX="/usr/local"
SOURCE=""
while (( $# )); do
  case "$1" in
    --prefix) PREFIX="${2:?}"; shift 2 ;;
    --source) SOURCE="${2:?}"; shift 2 ;;
    -h|--help)
      echo "Uso: $0 [--prefix /usr/local] [--source /ruta/a/kensei]"
      exit 0
      ;;
    *) echo "Argumento desconocido: $1" >&2; exit 2 ;;
  esac
done

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SOURCE="${SOURCE:-$(cd -- "$SCRIPT_DIR/.." && pwd)}"
LIB="$PREFIX/lib/kensei"
SHARE="$PREFIX/share/kensei"

[[ -f "$SOURCE/src/kensei/cli.py" ]] || {
  echo "No encuentro el paquete Kensei en $SOURCE/src/kensei" >&2
  exit 1
}

install -d -m 755 "$LIB" "$SHARE" "$SHARE/zsh" "$PREFIX/bin"
for item in src prompts config scripts eval modelfiles pyproject.toml README.md LICENSE NOTICE; do
  [[ -e "$SOURCE/$item" ]] || continue
  cp -a "$SOURCE/$item" "$LIB/"
done
install -d -m 755 "$LIB/data"
[[ -d "$SOURCE/data/manual" ]] && cp -a "$SOURCE/data/manual" "$LIB/data/"

install -m 755 "$SOURCE/packaging/usr/local/bin/kensei" "$PREFIX/bin/kensei"
install -m 755 "$SOURCE/packaging/usr/local/bin/kensei-cli" "$PREFIX/bin/kensei-cli"
install -m 755 "$SOURCE/packaging/usr/local/bin/kensei-model" "$PREFIX/bin/kensei-model"
install -m 644 "$SOURCE/packaging/etc/kensei/kensei.zsh" "$SHARE/kensei.zsh"
install -m 644 "$SOURCE/packaging/etc/kensei/logo.txt" "$SHARE/logo.txt"
install -m 644 "$SOURCE/packaging/etc/kensei/zsh/.zshrc" "$SHARE/zsh/.zshrc"

if ! python3 -c 'import rich, httpx, yaml, platformdirs' >/dev/null 2>&1; then
  echo "[kensei] WARN: faltan dependencias Python (rich/httpx/pyyaml/platformdirs)." >&2
  echo "[kensei]       En Arch: pacman -S python-rich python-httpx python-pyyaml python-platformdirs" >&2
fi
if ! command -v zsh >/dev/null 2>&1; then
  echo "[kensei] WARN: zsh no está instalado; el comando 'kensei' no abrirá la TUI." >&2
  echo "[kensei]       En Arch: pacman -S zsh zsh-autosuggestions zsh-syntax-highlighting zsh-completions" >&2
fi

echo "[kensei] instalado en $PREFIX"
echo "[kensei] shell:  $PREFIX/bin/kensei"
echo "[kensei] CLI:    $PREFIX/bin/kensei-cli"
echo "[kensei] config: $SHARE/kensei.zsh"
