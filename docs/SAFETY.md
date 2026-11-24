# Seguridad y alcance

## Principio

Kensei puede ayudar con seguridad ofensiva **solo** en:

1. Sistemas propios.
2. Laboratorios, VMs, contenedores o CTFs con autorización.
3. Un engagement con `scope.yaml` que declare `authorized: true` y un alcance definido (global o acotado).

No es un arma autónoma. Es un operador con un guard que **falla cerrado**: si no hay scope, no hay red.

## Archivo de scope

Copiar `config/scope.example.yaml` a `~/.config/kensei/scope.yaml` (o pasar `--scope`). El ejemplo de Ronin usa alcance global:

```yaml
engagement: "global-authorized"
authorized: true

targets:
  cidrs:
    - "0.0.0.0/0"
    - "::/0"
  domains:
    - "*"
  urls: []

deny:
  cidrs: []
  domains: []
```

Para un laboratorio o CTF, usá `config/scope.lab.example.yaml`, que limita CIDRs y dominios.

Reglas:

- `authorized: false` u omitido ⇒ todo comando de red se bloquea.
- `deny` gana sobre `targets`.
- `loopback` (`127.0.0.0/8`, `::1`, `localhost`) se permite para desarrollo local, salvo deny explícito.
- Un comando de red **sin target explícito** se bloquea (evita `nmap` a ciegas).
- Los dominios que parecen archivos (`payloads.txt`) no se interpretan como targets.
- El alcance global **no** desactiva el guard destructivo ni el modo dry-run.

## Clasificación del guard

| Nivel | Ejemplos | Comportamiento |
| --- | --- | --- |
| `critical` | `rm -rf /`, `mkfs`, `dd of=/dev/sd*`, fork bomb, borrar subvolumen raíz | **Bloqueado**, no se puede confirmar |
| `high` | `chmod -R 777 /`, `snapper delete`, `ufw disable`, pipe-to-shell, reverse shell, `mount`, `iptables` | Requiere confirmación explícita |
| `medium` | comandos de red, `systemctl restart`, escritura de archivos | Requiere confirmación |
| `low` | lectura, `systemctl status`, `df`, `ss`, `pacman -Q` | Ejecuta si `--execute` |

Además:

- `read_file`/`write_file` sensibles (`/etc/shadow`, `~/.ssh`, `~/.aws`, `.env`) requieren confirmación.
- `write_file` solo puede escribir dentro del workspace actual.
- `http_get` pasa por el mismo scope que `shell`.
- Cada decisión se audita en `~/.local/state/kensei/audit.jsonl`.

## Flujo de ejecución

```
modelo propone <tool_call>
        │
        ▼
  parse_tool_calls
        │
        ▼
  Guard.check(tool, args)
        │
   ┌────┴─────┐
   │          │
bloqueado   permitido
   │          │
   ▼          ▼
tool_response  ¿--execute?
              │
        ┌─────┴─────┐
        │           │
       no          sí
        │           │
     dry-run    confirmación
                    │
                    ▼
                 ejecutar
                    │
                    ▼
              tool_response
```

Sin `--execute`, Kensei es **solo lectura**: muestra el comando y no lo corre. `--yes` salta la confirmación; usalo solo en entornos controlados y nunca en un engagement real sin revisar cada comando.

## Auditoría

Cada registro incluye:

```json
{
  "ts": "2026-11-23T14:02:11+00:00",
  "tool": "shell",
  "command": "nmap -sV 10.10.10.5",
  "decision": {"allowed": true, "needs_confirmation": true, "risk": "high"},
  "result": "ok",
  "exit_code": 0,
  "duration_ms": 4120
}
```

Revisar:

```bash
tail -n 50 ~/.local/state/kensei/audit.jsonl | jq
```

No borres la auditoría durante un engagement. Si necesitás limpiarla, archivá y documentá.

## Modelo de amenazas

| Amenaza | Realidad | Mitigación |
| --- | --- | --- |
| El modelo alucina un flag | Frecuente en 7B | `--help`, `man`, verificación, Dojo |
| Prompt injection desde una página | El RAG puede traer texto hostil | Tratar contexto como no confiable; guard; no ejecutar instrucciones embebidas |
| Envenenamiento del corpus | Un repo comprometido mete comandos | Pinear commits, revisar diffs, no indexar URLs arbitrarias |
| Escape del guard | Regex no es un sandbox | VM/snapshot, usuario sin privilegios, revisar comandos |
| Exfiltración de secretos | El modelo puede proponer `curl` con datos | Guard de red + revisión + no poner secretos en el prompt |
| Daño local | `rm`, `mkfs`, `dd` | Lista crítica bloqueada + confirmación + backup |
| Uso contra terceros | El operador ignora el scope | Política de uso, autorización escrita, auditoría |

**El guard no es un sandbox.** Es una capa de seguridad en profundidad. Para probar exploits, usá una VM aislada, snapshots y una red host-only.

## Modelo abliterado

La build actual de `kensei` usa un **Qwen2.5-Coder-7B-Instruct abliterado** (bartowski Q4_K_M). Eso reduce las negativas por reflejo del modelo base, pero **no elimina el guard**: el scope, la lista de comandos críticos y la confirmación siguen siendo la barrera real. No uses `--yes` en un sistema real y no cargues targets de terceros en `scope.yaml`.

## Uso responsable

- No escanees ni explotes sistemas de terceros sin autorización escrita.
- No uses Kensei para acosar, extorsionar, doxxear, exfiltrar datos, cifrar archivos ajenos ni denegar servicio.
- No publiques credenciales, hashes, tokens ni datos de clientes en prompts, issues o reportes.
- En un engagement: alcance firmado, ventana, contacto de emergencia, reglas de evidencia y plan de rollback.
- Si encontrás una vulnerabilidad en un tercero, seguí divulgación responsable; no la explotes.

## Negativas

Kensei debe negarse así:

> No puedo ayudarte a atacar `ejemplo.com`: no está en el scope autorizado. Si es tu lab, agregalo a `~/.config/kensei/scope.yaml` o usá una VM local. Si tenés autorización escrita, pasame el engagement y el target exacto.

Sin sermón, sin instrucciones de evasión, con alternativa segura.

## Datos y licencias

- El corpus combina CC BY-NC 4.0, GPL-3.0, GFDL-1.3, CC BY 4.0 y MIT. Mantené el dataset y los pesos en privado.
- No subas el corpus a servicios de terceros sin revisar licencias y privacidad.
- El código del harness es MIT; el modelo base es Apache-2.0.
- Si publicás resultados del Dojo, no incluyas texto propietario de un cliente ni payloads operativos.
