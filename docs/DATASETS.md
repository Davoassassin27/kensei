# Datasets y fuentes

## Fuentes

| Fuente | Repo / origen | Ruta incluida | Licencia | Uso en Kensei |
| --- | --- | --- | --- | --- |
| Arch Wiki | `arch-wiki-docs` o API `wiki.archlinux.org` | páginas curadas en `config/archwiki-pages.txt` | GFDL-1.3-or-later | Administración Arch/CachyOS, systemd, red, seguridad |
| HackTricks | `HackTricks-wiki/hacktricks` | `src/**/*.md` (sin traducciones) | **CC BY-NC 4.0** | Metodología ofensiva y privesc |
| PayloadsAllTheThings | `swisskyrepo/PayloadsAllTheThings` | `**/*.md` (sin `Files/`) | MIT | Payloads y bypasses de laboratorio |
| The Hacker Recipes | `The-Hacker-Recipes/The-Hacker-Recipes` | `docs/src/**/*.md` | GPL-3.0-only | AD, infraestructura, web |
| tldr | `tldr-pages/tldr` | `pages/common/*.md`, `pages/linux/*.md` | CC-BY-4.0 | Sintaxis y ejemplos de comandos |
| GTFOBins | `GTFOBins/GTFOBins.github.io` | `_gtfobins/*` | GPL-3.0-only | Escapes SUID/sudo en laboratorio |
| Manual Ronin / seguridad | `data/manual/` | YAML propio | MIT (propio) | Arquitectura de Ronin, alcance y negativas |

> **HackTricks es no comercial.** El dataset combinado y cualquier peso derivado se mantienen **privados**. Publicar el harness y los scripts es seguro; publicar el corpus o el adapter requiere revisión legal de GFDL, GPL, CC BY-NC y CC BY.

## Estado del corpus (2026-11-23)

| Fuente | Documentos | Chunks | Texto |
| --- | ---: | ---: | ---: |
| Arch Wiki | 81 | 2.609 | 2,24 MB |
| HackTricks | 1.146 | 16.722 | 17,49 MB |
| PayloadsAllTheThings | 139 | 1.290 | 1,01 MB |
| The Hacker Recipes | 235 | 1.074 | 1,20 MB |
| tldr | 6.857 | 6.857 | 3,58 MB |
| GTFOBins | 457 | 816 | 0,15 MB |
| Manual Ronin + seguridad | 37 | 37 | 0,02 MB |
| **Total** | **8.952** | **29.403** | **25,7 MB** |

- 6 duplicados exactos descartados.
- 2 páginas de Arch Wiki faltantes/redirect (`Master_boot_record`, `Btrfs/Subvolumes`).
- HackTricks se clona con **sparse checkout** (`src/**/*.md`) y `core.longpaths=true`: el checkout completo falla en Windows por nombres de imágenes >260 caracteres.
- En Windows, Defender puede bloquear `_gtfobins/node`; el normalizador lo omite y sigue. En Linux se incluye.

## Pipeline

```
fetch_sources.py
      │  data/raw/<source>/
      ▼
normalize_corpus.py
      │  documents.jsonl  (texto limpio, metadata, licencia, riesgo)
      │  chunks.jsonl     (secciones <= 6.000 chars para RAG)
      │  commands.jsonl   (tldr parseado)
      │  gtfobins.jsonl   (funciones + contextos + código)
      ▼
build_tool_traces.py ──► tool_traces.jsonl
      │
build_sft.py
      │  sft.jsonl / sft.val.jsonl / sft.stats.json
      ▼
validate_dataset.py ──► reports/dataset-validation.json
```

## Normalización

- **Markdown genérico:** se quita front matter, HTML, badges, imágenes y comentarios. Se preservan bloques de código y tablas.
- **Arch Wiki:** la API devuelve `explaintext` (texto plano). Se prefija `# Título`. Se descartan páginas < 300 caracteres.
- **tldr:** parser propio de `# comando`, `> descripción`, `- ejemplo:` y `` `comando` ``. Se separa `commands.jsonl` para generar SFT de sintaxis.
- **GTFOBins:** el archivo no tiene extensión y usa YAML front matter. Se aplana `functions.<fn>[].contexts.<ctx>` a documentos con bloques `bash` y se guarda una estructura `gtfobins.jsonl` para SFT.
- **Duplicados:** hash SHA-256 del texto del documento y hash del ejemplo completo.
- **Riesgo:** cada documento y ejemplo se clasifica con `kensei.guard.risk_of_text` (`low`, `medium`, `high`, `critical`).

## Composición del SFT

| Tipo | Generador | Volumen objetivo | Qué enseña |
| --- | --- | --- | --- |
| `doc-section` | `build_sft.generate_docs` | 40 % | Explicar una sección con comandos y cita |
| `doc-summary` | `generate_docs` | 10 % | Resumir una técnica completa |
| `command-overview` | `generate_tldr` | 15 % | Sintaxis, placeholders y ejemplos |
| `command-example` | `generate_tldr` | 10 % | Un comando para una intención |
| `gtfobins-functions` | `generate_gtfobins` | 10 % | Contexto SUID/sudo y verificación |
| `tool-trace` | sintético | 3 % | Bucle observar → actuar → verificar |
| `manual` | `data/manual/*.yaml` | 1 % | Ronin, seguridad, alcance y negativas |

Reglas:

- El system prompt de entrenamiento es estable y corto; el harness inyecta el scope real en inferencia.
- Las respuestas ofensivas incluyen una línea de alcance y la fuente.
- Los `tool-trace` usan `<tool_call>` JSON y respuestas `tool` reales (Qwen las envuelve en `<tool_response>`).
- Los ejemplos de seguridad no son sermones: niegan, explican por qué y ofrecen alternativa de laboratorio.

## Validación

`validate_dataset.py` verifica:

- roles y orden (`system`, `user`, …, `assistant`),
- contenido no vacío,
- JSON de cada `<tool_call>` y herramienta conocida,
- longitud estimada <= `--max-tokens`,
- duplicados exactos,
- licencia declarada,
- balance por fuente (warning si una supera 70 %),
- presencia de `manual:safety` y `tool-trace`.

## Contaminación y evaluación

- El Dojo (`eval/cases.yaml`) es **independiente** del dataset: no se genera desde las mismas secciones.
- Antes de entrenar, buscá solapamiento entre `sft.jsonl` y los prompts del Dojo; si aparece, reescribí el caso.
- No agregues al dataset las respuestas del Dojo ni las salidas de la evaluación.
- Mantené un set de 30–50 comandos reales de Ronin como prueba de aceptación manual.

## Actualización

| Fuente | Frecuencia | Nota |
| --- | --- | --- |
| Arch Wiki | mensual | La API cambia; pinear fecha en `stats.json` |
| HackTricks | mensual | Revisar cambios de licencia |
| Payloads | mensual | Descartar archivos binarios |
| THR | trimestral | GPL: mantener atribución |
| tldr | mensual | Barato y de alta señal |
| GTFOBins | trimestral | Revisar nuevos contextos |

```bash
# refresco completo
uv run python scripts/fetch_sources.py --force
uv run python scripts/normalize_corpus.py
uv run python scripts/build_tool_traces.py --manual-variants 2
uv run python scripts/build_sft.py --repeat-safety 3
uv run python scripts/validate_dataset.py --strict
uv run kensei index
```

## Licencias y atribución

- Guardá `license` en cada documento, chunk y ejemplo.
- Si publicás el código, incluí `NOTICE` con las fuentes y sus licencias.
- No publiques el corpus ni el adapter sin revisar:
  - **CC BY-NC 4.0** (HackTricks): prohíbe uso comercial.
  - **GPL-3.0** (THR, GTFOBins): obligaciones de copyleft sobre obras derivadas.
  - **GFDL-1.3** (Arch Wiki): atribución y licencia de las modificaciones.
  - **CC BY 4.0** (tldr): atribución.
- El código del harness es MIT; el modelo base Qwen2.5-Coder es Apache-2.0.
