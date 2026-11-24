# Shell TUI de Kensei

`kensei` no es un REPL de Python: abre una **zsh real** con ghost autocomplete, historial, job control y soporte para vim/htop/ssh. El modelo se consulta desde esa shell.

## Instalación

En un Linux con Python 3.11+:

```bash
sudo bash packaging/install.sh --prefix /usr/local --source /ruta/a/kensei
```

Dependencias en Arch/CachyOS:

```bash
sudo pacman -S zsh zsh-autosuggestions zsh-syntax-highlighting zsh-completions \
  python-rich python-httpx python-pyyaml python-platformdirs
```

Opcional, para animaciones:

```bash
uv tool install terminaltexteffects
```

## Uso

```bash
kensei
```

Abre la shell con:

- Banner low-tech, modelo, scope y usuario.
- Animación `tte print` del logo ASCII `KENSEI` (si `tte` está instalado).
- Prompt `kensei›` (rojo si es root).
- Ghost autocomplete desde historial y completion.
- Tab acepta el fantasma; si no hay fantasma, Tab completa rutas normalmente.
- `Ctrl-D` o `exit` para salir.

Dentro de la shell:

```bash
kensei "¿Cómo veo los subvolúmenes Btrfs?"
kensei --auto "enumerá SMB en 192.168.56.10"
kensei --help
```

| Comando | Qué hace |
| --- | --- |
| `kensei` | Chat interactivo con confirmación por comando |
| `kensei <prompt>` | Respuesta única, dry-run |
| `kensei --auto <prompt>` | Agente con menú: ejecutar / editar / dry-run / cancelar |
| `kensei --root` | Shell root (el guard sigue activo) |
| `kensei --no-anim` | Sin `tte` |
| `kensei --help` | Ayuda del CLI |

Fuera de la shell, el binario `/usr/local/bin/kensei` acepta los mismos modos; sin argumentos abre la zsh.

## Ghost autocomplete

- Plugin: `zsh-autosuggestions`.
- Estrategia: `history` + `completion`.
- Color: gris (`fg=240`).
- Tab: `_kensei_tab` acepta `$POSTDISPLAY` si existe; si no, `expand-or-complete`.
- Para desactivar el fantasma: `unset ZSH_AUTOSUGGEST_STRATEGY` o no cargar el plugin.

No se usa `zsh-autosuggestions` para ejecutar nada: solo sugiere. La ejecución pasa por el CLI, el guard y la confirmación.

## Modo `--auto`

El modelo propone una tool-call; el harness muestra:

```text
[1] ejecutar   [2] editar   [3] dry-run   [4] cancelar
```

- **Editar** permite cambiar el comando y vuelve a pasar por el guard.
- **Dry-run** devuelve la propuesta sin ejecutar.
- **Cancelar** devuelve el control al modelo con “Cancelado por el operador”.
- `--yes` salta el menú; usalo solo en entornos controlados.

El guard bloquea comandos críticos y targets fuera de scope antes del menú. Si el modelo insiste, no hay forma de saltarlo desde `--auto`.

## Branding

- Banner ASCII con el wordmark `KENSEI` y `RONIN // 07`.
- `tte print` con gradiente ámbar para el logo; fallback a `cat` si no está.
- Paleta: verde, gris y ámbar; sin degradados ni emojis.
- Prompt root en rojo.
- `kensei --no-anim` imprime el logo sin animación.

## Windows dev host

La shell zsh no corre en Windows. Para el host de desarrollo hay un shim PowerShell en `packaging/windows/`:

```powershell
# copiar a un directorio del PATH
copy kensei\packaging\windows\kensei.cmd  $env:USERPROFILE\.local\bin\
copy kensei\packaging\windows\kensei.ps1  $env:USERPROFILE\.local\bin\
# indicar el repo si no está en kensei/packaging/windows
setx KENSEI_ROOT "C:\src\kensei"
```

Uso:

```powershell
kensei                         # chat interactivo
kensei "¿cómo listo Btrfs?"    # dry-run
kensei --auto "enumerá SMB"    # HITL
```

En Windows no hay `--root` ni ghost autocomplete: eso es la shell Linux de Ronin/workOS.

## WorkOS / Ronin

`build/guest/65-kensei.sh`:

- Instala `zsh` y plugins, Python deps y `tte` (best effort).
- Copia Kensei a `/usr/local/lib/kensei` y los lanzadores a `/usr/local/bin`.
- Construye un RAG manual (Ronin + seguridad) en `~/.local/share/kensei`.
- Crea `~/.config/kensei/scope.yaml` con `authorized: false`.
- Instala `kensei-model.service`, que en el primer boot descarga el GGUF abliterado y ejecuta `ollama create kensei`.
- `KENSEI_PRELOAD_MODEL=yes` en `build.env` descarga durante el provisioning (build más lento).

El modelo por defecto es **Qwen2.5-Coder-7B-Instruct abliterado** (bartowski Q4_K_M). No es el LoRA; el adapter fine-tune se genera después con `config/train_qlora_12gb.yaml`.

## Troubleshooting

| Síntoma | Causa / fix |
| --- | --- |
| No hay fantasma | Verificá `echo $ZDOTDIR`: debe ser `/usr/local/share/kensei/zsh`. El wrapper viejo seteaba `KENSEI_ZDOTDIR` y zsh cargaba el rc default. Si está vacío, reinstalá el wrapper o ejecutá `ZDOTDIR=/usr/local/share/kensei/zsh zsh -d -i`. |
| Tab no acepta | El widget `autosuggest-accept` no existe; revisá que el plugin esté cargado y que `ZDOTDIR` sea correcto. |
| `kensei: falta zsh` | `pacman -S zsh zsh-autosuggestions zsh-syntax-highlighting zsh-completions`. |
| No hay animación | `tte` no está en PATH; `uv tool install terminaltexteffects` o `kensei --no-anim`. |
| `kensei` no responde | `systemctl status ollama`; `ollama list`; el modelo debe llamarse `kensei`. |
| Modelo no creado en workOS | `systemctl status kensei-model`; `journalctl -u kensei-model -b`; `/var/log/ronin/kensei-model.log`. |
| Scope no autorizado | Editá `~/.config/kensei/scope.yaml`; el ejemplo trae `authorized: false` en la imagen. |
