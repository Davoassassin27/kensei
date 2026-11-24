# Plan de Kensei

Kensei es el SLM de terminal de Ronin. El objetivo no es "un modelo que sabe comandos", sino un operador local que:

1. **Observa** antes de cambiar.
2. **Propone un paso** atómico y verificable.
3. **Ejecuta** solo con `--execute`, guard de alcance y confirmación.
4. **Verifica** la salida y corrige.
5. **Cita** la fuente documental cuando usa memoria.

## Arquitectura

```
                    ┌──────────────────────────────┐
                    │  Ronin: CachyOS + Omarchy    │
                    │  Ollama en 127.0.0.1:11434   │
                    └──────────────┬───────────────┘
                                   │
              ┌────────────────────┴────────────────────┐
              │              Kensei Core                 │
              │  Qwen2.5-Coder-7B + LoRA (conducta)     │
              └────────────────────┬────────────────────┘
                                   │
     ┌─────────────────────────────┼─────────────────────────────┐
     │                             │                             │
┌────┴─────┐                 ┌─────┴──────┐               ┌──────┴──────┐
│ Memory   │                 │ Hands      │               │ Dojo        │
│ SQLite   │                 │ CLI + guard│               │ eval cases  │
│ FTS5     │                 │ audit log  │               │ base vs FT  │
└──────────┘                 └────────────┘               └─────────────┘
```

**LoRA enseña conducta; RAG aporta hechos.** El corpus completo (Arch Wiki + HackTricks + Payloads + THR + tldr + GTFOBins) es demasiado grande y cambiante para memorizarlo en un adaptador de 7B. Forzar memorización degradaría el razonamiento y quedaría obsoleto en semanas.

## Fases

| Fase | Entregable | Criterio de aceptación | Estado |
| --- | --- | --- | --- |
| **K0** | Scaffold ejecutable | `doctor`, `index`, `recall`, `ask --execute`, tests y pipeline corren | ✅ |
| **K1** | Corpus real | fetch + normalize de las seis fuentes; `stats.json` con conteos y licencias | ✅ |
| **K2** | Dataset curado | `sft.jsonl` validado, sin duplicados, con tool-traces y seguridad | 🟡 |
| **K3** | LoRA | QLoRA termina, loss baja, adapter guardado y reproducible | 🟡 |
| **K4** | Dojo | el fine-tune supera al base en tool-calls, formato y rechazos | 🟡 |
| **K5** | Deployment | GGUF Q4_K_M + Ollama `kensei` + `doctor` PASS en Ronin | 🟡 |
| **K6** | Memoria viva | RAG actualizable y citas correctas en >= 90 % de los casos | 🟡 |

## K0 — Scaffold (hecho)

Incluye:

- `config/sources.yaml` con las seis fuentes y sus licencias.
- `scripts/fetch_sources.py` (git shallow + API de Arch Wiki).
- `scripts/normalize_corpus.py` (markdown/tldr/GTFOBins → documentos y chunks).
- `scripts/build_sft.py` (SFT desde secciones, comandos y manuales).
- `scripts/build_tool_traces.py` (trayectorias sintéticas de terminal).
- `scripts/validate_dataset.py` (schema, duplicados, licencias, balance).
- `scripts/train_qlora.py` (QLoRA con transformers + peft + bitsandbytes).
- `scripts/export_gguf.py` (merge + llama.cpp + Modelfile).
- `src/kensei/` (CLI, guard, tools, Ollama, RAG FTS5).
- `eval/` (casos determinísticos + runner del Dojo).
- `tests/` (protocolo, guard, RAG, tools, pipeline, eval, CLI).

## K1 — Corpus real

Comandos:

```bash
uv run python scripts/fetch_sources.py
uv run python scripts/normalize_corpus.py
```

Primera pasada recomendada (rápida, sin clonar todo):

```bash
uv run python scripts/fetch_sources.py --only tldr gtfobins archwiki --limit 40
uv run python scripts/normalize_corpus.py --only tldr gtfobins archwiki
```

Criterios:

- `data/derived/stats.json` con `documents`, `chunks`, `per_source`.
- Ninguna fuente con 0 documentos.
- Revisar que HackTricks no haya incluido traducciones ni imágenes.
- Confirmar que GTFOBins tiene `functions` parseadas (no YAML vacío).

**Resultado actual:** 8.952 documentos, 29.403 chunks, 25,7 MB de texto. Reparto: HackTricks 1.146 docs, tldr 6.857, GTFOBins 457, THR 235, Payloads 139, Arch Wiki 81, manual Ronin 20 y seguridad 17. GTFOBins tiene 457 entradas parseadas; 6 duplicados exactos descartados. El clone de HackTricks usa sparse checkout (`src/**/*.md`) para evitar rutas >260 caracteres en Windows.

## K2 — Dataset curado

```bash
uv run python scripts/build_tool_traces.py --manual-variants 2
uv run python scripts/build_sft.py --repeat-safety 3
uv run python scripts/validate_dataset.py --strict
```

Criterios:

- >= 2.000 ejemplos (ideal 5.000–15.000), con mezcla de fuentes.
- `manual:safety` presente y con negativas correctas.
- `tool-trace` presente y con `<tool_call>` parseable.
- 0 errores de schema; warnings justificados.
- Revisión manual de 50 ejemplos aleatorios: precisión de comandos y citas.

**Resultado actual:** 6.061 ejemplos (5.940 train / 121 val), 0 errores, 0 duplicados. Reparto: tldr 2.776, HackTricks 1.518, GTFOBins 458, THR 448, Payloads 313, Arch Wiki 302, tool-traces 175, manual Ronin 20, seguridad 51. Tokens: promedio 383, p95 670, máximo 1.372. Falta la revisión humana de 50 ejemplos y decidir si se sube `--max-per-source` para dar más peso a Arch Wiki/GTFOBins.

## K3 — LoRA

Ver [TRAINING.md](TRAINING.md). Hardware mínimo realista:

| Base | VRAM | Contexto | Nota |
| --- | --- | --- | --- |
| 7B QLoRA | 16 GB | 4096 | ajustado; batch 1 + grad accum |
| 7B QLoRA | 24 GB | 4096–8192 | cómodo |
| 1.5B QLoRA | 8 GB | 4096 | fallback para notebook |
| 7B full fine-tune | 80 GB+ | — | no es el objetivo |

Criterios:

- Entrenamiento completa 2 épocas sin OOM.
- Loss de validación no sube al final.
- Adapter <= 500 MB; metadata con base, dataset y GPU.

## K4 — Dojo

```bash
uv run python eval/run_eval.py --model qwen2.5-coder:7b --out reports/eval-base.json
uv run python eval/run_eval.py --model kensei --out reports/eval-kensei.json

# variante con memoria local
uv run python eval/run_eval.py --model kensei --rag --out reports/eval-kensei-rag.json
```

Línea base medida: **1/4 en el smoke** (ver [EVAL-BASELINE.md](EVAL-BASELINE.md)). El base no emite tool-calls, no se niega al scan público y alucina Ronin. La comparación completa queda pendiente de GPU/timeout.

Criterios:

- `kensei` >= base + 20 puntos en tool-calls correctas.
- 100 % de los casos `safety-*` sin tool-call ofensiva.
- 0 comandos bloqueados en casos `blocked: false`.
- Revisión cualitativa: menos prosa, comandos más cortos, citas presentes.

## K5 — Deployment

```bash
# modelo actual (sin LoRA): abliterado Q4_K_M + prompt
uv run python scripts/create_base_model.py \
  --gguf models/kensei-abliterated-bartowski-Q4_K_M.gguf \
  --name kensei

# cuando exista el adapter fine-tune
uv run python scripts/export_gguf.py \
  --adapter models/kensei-qwen2.5-coder-7b-lora \
  --quant Q4_K_M
ollama create kensei -f modelfiles/Kensei.Modelfile

uv run kensei doctor --model kensei
```

Estado actual: **K5 parcial**. `kensei` ya existe en Ollama con el abliterado + prompt, y la shell/TUI está empaquetada (`packaging/`, `65-kensei.sh`). Falta reemplazarlo por el GGUF fine-tune.

Criterios:

- `ollama run kensei` responde y respeta el protocolo.
- `kensei ask "..."` responde; `kensei --auto "..."` ejecuta con human-in-the-loop.
- `doctor` sin FAIL en Ronin.
- Tiempo de primera respuesta aceptable en la notebook (objetivo < 10 s con Q4).

## K6 — Memoria viva

- Refrescar fuentes mensualmente o antes de un engagement.
- Reindexar `kensei index` después de cada refresh.
- Medir citas correctas en el Dojo.
- Versionar el corpus por commit/fecha en `data/derived/stats.json`.

## Riesgos

| Riesgo | Impacto | Mitigación |
| --- | --- | --- |
| Corpus no cabe en el LoRA | Alucinaciones | RAG obligatorio para hechos; LoRA solo conducta |
| Licencias incompatibles | No publicable | Uso privado; revisión legal antes de distribuir |
| 7B alucina flags | Comandos rotos | `--help`, `man`, verificación y Dojo |
| Prompt injection vía RAG | Ejecución maliciosa | Tratar contexto como no confiable; guard y confirmación |
| Guard incompleto | Daño local | Lista negativa + confirmación + VM/snapshot |
| Hardware insuficiente | K3 bloqueado | Cloud GPU o base 1.5B |

## No objetivos

- Entrenar un modelo generalista desde cero.
- Competir con GPT/Claude en conocimiento general.
- Automatizar ataques sin operador.
- Saltar el guard con "modo dios".
- Publicar pesos derivados de HackTricks (CC BY-NC) sin revisión.
