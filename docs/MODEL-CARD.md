# Model card — Kensei

## Resumen

| Campo | Valor |
| --- | --- |
| Nombre | Kensei |
| Versión | 0.1.0 (prompt-only abliterado; LoRA pendiente) |
| Tipo | SLM de terminal + agente con herramientas |
| Base de entrenamiento | `Qwen/Qwen2.5-Coder-7B-Instruct` (Apache-2.0, 7.6B) |
| Implementación actual | `bartowski/Qwen2.5-Coder-7B-Instruct-abliterated-GGUF` Q4_K_M + prompt de Kensei (Apache-2.0) |
| Variante abliterada | `Goekdeniz-Guelmez/Josiefied-...-abliterated-v1` (Apache-2.0; su GGUF puede traer template roto, usar bartowski) |
| Adaptación | Hoy: system prompt + RAG + guard. Después: QLoRA 4-bit (r=32/16) |
| Memoria | RAG local SQLite FTS5 sobre corpus documental + manual Ronin |
| Servido | Ollama `kensei` (abliterado Q4_K_M + prompt) |
| Idioma | Español rioplatense técnico (por defecto), inglés técnico |
| Licencia del código | MIT |
| Licencia del modelo base | Apache-2.0 |
| Licencia de datos | Mixta: CC BY-NC 4.0, GPL-3.0, GFDL-1.3, CC BY 4.0, MIT |

## Uso previsto

- Operar la terminal de **Ronin** (CachyOS + Omarchy): systemd, pacman, Btrfs/Snapper, red, Docker, SSH, firewall.
- Diagnosticar fallos con un bucle observar → proponer → ejecutar → verificar.
- Recordar procedimientos de Arch Wiki, HackTricks, PayloadsAllTheThings, The Hacker Recipes, tldr y GTFOBins mediante RAG y citarlos.
- Asistir en **laboratorios propios, CTFs y engagements autorizados** con scope explícito.
- Enseñar el *cómo* y el *por qué* de una técnica, incluyendo detección y mitigación.

## Uso fuera de alcance

- Atacar sistemas de terceros sin autorización escrita.
- Exfiltrar credenciales, cifrar archivos ajenos, persistir, evadir controles o causar denegación de servicio.
- Automatizar campañas de phishing, malware o abuso.
- Reemplazar juicio profesional, revisión legal o un sandbox.
- Operar infraestructura crítica o datos personales sin base legal.

El guard del harness bloquea comandos destructivos y targets fuera de scope, pero **no es un sandbox**. La responsabilidad final es del operador.

## Datos de entrenamiento

| Fuente | Licencia | Aporte |
| --- | --- | --- |
| Arch Wiki (páginas curadas) | GFDL-1.3+ | Administración Arch/CachyOS, systemd, red, seguridad |
| HackTricks | CC BY-NC 4.0 | Metodología ofensiva, AD, web, cloud, privesc |
| PayloadsAllTheThings | MIT | Payloads y bypasses de laboratorio |
| The Hacker Recipes | GPL-3.0 | AD, infraestructura, web |
| tldr | CC BY 4.0 | Sintaxis y ejemplos de comandos |
| GTFOBins | GPL-3.0 | Escapes SUID/sudo |
| Manual Ronin | MIT (propio) | Arquitectura, comandos y verificación de Ronin |
| Manual de seguridad | MIT (propio) | Alcance, negativas y alternativas |
| Tool-traces sintéticos | MIT (propio) | Protocolo `<tool_call>` y método |

El corpus completo **no se memoriza** en el LoRA: se indexa en RAG. El adaptador enseña formato, método, estilo y criterio.

## Entrenamiento

Receta de referencia (`config/train_qlora.yaml`):

- QLoRA 4-bit NF4, doble cuantización.
- LoRA r=32, alpha=64, dropout=0.05, `use_rslora=true`.
- Target modules: `q_proj`, `k_proj`, `v_proj`, `o_proj`, `gate_proj`, `up_proj`, `down_proj`.
- 2 épocas, lr=1e-4, cosine, warmup 3 %, batch 2 × grad accum 8.
- `max_seq_length=4096`.
- Masking solo en turnos `assistant`.

Estado: **K3 pendiente**. No hay pesos publicados ni métricas de entrenamiento todavía.

**Modelo actual en Ollama:** `kensei` es un build *prompt-only* de `qwen2.5-coder:7b` con el system prompt de Kensei, RAG y guard. No es el LoRA. Se recrea con `scripts/create_base_model.py` y se reemplaza cuando exista el GGUF fine-tune.

## Evaluación

El Dojo (`eval/cases.yaml`) mide:

- tool-call correcta y comando esperado,
- respeto del scope (target permitido/bloqueado),
- negativas correctas en casos de abuso,
- conocimiento de Ronin y de las fuentes,
- formato y brevedad.

Comparación prevista:

```bash
uv run python eval/run_eval.py --model qwen2.5-coder:7b --out reports/eval-base.json
uv run python eval/run_eval.py --model kensei --rag --out reports/eval-kensei.json
```

Estado: **K4 pendiente**. Los reportes se guardan en `reports/` y no se versionan.

## Limitaciones

- Un 7B alucina flags, rutas y versiones. Verificá con `--help`, `man` y la salida real.
- El RAG puede recuperar contexto irrelevante o envenenado; tratalo como no confiable.
- El guard usa regex y listas; no cubre todos los comandos destructivos ni ofuscaciones.
- El modelo no tiene memoria de sesión más allá de la ventana de contexto.
- La calidad en español rioplatense depende del dataset manual; puede degradarse en temas no cubiertos.
- La variante abliterada puede aumentar la obediencia a pedidos riesgosos; el guard y la política siguen siendo obligatorios.
- El entrenamiento local requiere GPU; 12 GB VRAM (RX 6700 XT) es el mínimo ajustado y necesita Linux/ROCm. En Windows AMD no hay una ruta estable de QLoRA.

## Consideraciones éticas y legales

- HackTricks es **no comercial**. Mantené el dataset y los pesos en privado; no los distribuyas sin revisión legal.
- GPL-3.0 y GFDL-1.3 imponen obligaciones de atribución/copyleft sobre obras derivadas.
- No uses el modelo para vigilancia masiva, discriminación, acoso o daño.
- Documentá autorización, alcance y evidencia en cualquier engagement.
- Si encontrás un secreto o una vulnerabilidad, seguí divulgación responsable.

## Cómo citar

```text
Kensei 0.1 — terminal-native security SLM for Ronin.
Base: Qwen2.5-Coder-7B-Instruct (Apache-2.0).
Adaptación: QLoRA + RAG local.
```
