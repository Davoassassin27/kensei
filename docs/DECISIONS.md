# Decisiones de arquitectura de Kensei

Formato: contexto → decisión → consecuencias → estado. Estas decisiones son locales al subproyecto; las de Ronin viven en `../docs/05-ADRS.md`.

---

## ADR-K1: LoRA + RAG, no solo fine-tuning

**Fecha:** 2026-11-23
**Estado:** Accepted

### Contexto

Las seis fuentes suman cientos de MB y cambian todas las semanas. Un LoRA de 7B no puede memorizar ese corpus sin degradar razonamiento, y quedaría obsoleto rápido. Al mismo tiempo, el modelo base no conoce el protocolo de tool-calls de Kensei ni el estilo operativo de Ronin.

### Decisión

Separar responsabilidades:

- **LoRA:** conducta, formato `<tool_call>`, método de diagnóstico, estilo, negativas correctas.
- **RAG FTS5:** hechos, flags, rutas, procedimientos y citas actualizadas.

### Consecuencias

- (+) El modelo sigue siendo pequeño y portable.
- (+) El corpus se actualiza sin reentrenar.
- (+) Las citas son verificables.
- (−) Dos sistemas que mantener (adapter + índice).
- (−) El RAG puede recuperar contexto irrelevante o envenenado.
- (−) La latencia incluye búsqueda + generación.

### Mitigación

- Dojo con casos que requieren citas.
- `recall` como herramienta explícita.
- Reindexado mensual y revisión de fuentes.

---

## ADR-K2: Qwen2.5-Coder-7B-Instruct como base

**Fecha:** 2026-11-23
**Estado:** Accepted

### Contexto

Se necesita un modelo Apache-2.0, con buen rendimiento en código/terminal, disponible en GGUF, que quepa en una notebook con 16 GB de RAM en Q4 y permita QLoRA en 16–24 GB de VRAM. Se evaluaron Qwen2.5-Coder-7B, Qwen3-Coder-30B-A3B y variantes abliteradas.

### Decisión

Usar `Qwen/Qwen2.5-Coder-7B-Instruct` como default. Ofrecer la variante abliterada de `Goekdeniz-Guelmez` como opción, no como default. Mantener Qwen3-Coder-30B-A3B como upgrade path.

### Consecuencias

- (+) Licencia permisiva y ecosistema maduro (GGUF, Ollama, plantilla de tools).
- (+) Entrena y corre en hardware de consumo.
- (+) El template oficial soporta `<tool_call>` y `<tool_response>`.
- (−) Menos capaz que un 30B en razonamiento complejo.
- (−) La variante abliterada puede requerir más guardrails.

---

## ADR-K3: QLoRA con transformers + peft

**Fecha:** 2026-11-23
**Estado:** Accepted

### Contexto

Unsloth es rápido en CUDA pero no soporta ROCm de forma oficial. Axolotl es portable pero añade una dependencia grande. El entorno de entrenamiento aún no está definido.

### Decisión

Implementar `scripts/train_qlora.py` con `transformers` + `peft` + `bitsandbytes`, masking manual de turnos del assistant y un collator propio. Mantener `config/axolotl.yml` como alternativa ROCm.

### Consecuencias

- (+) portable CUDA/ROCm (con matices de bitsandbytes),
- (+) sin dependencia de TRL ni de versiones cambiantes de `SFTTrainer`,
- (+) control explícito del masking,
- (−) más código propio que mantener,
- (−) menos optimizaciones que Unsloth.

---

## ADR-K4: Guard de alcance con fallo cerrado

**Fecha:** 2026-11-23
**Estado:** Accepted

### Contexto

Un agente de terminal con herramientas puede causar daño local o atacar terceros. El modelo no es confiable para decidir límites legales.

### Decisión

Implementar un guard determinístico que:

- bloquea comandos críticos sin posibilidad de confirmación,
- exige confirmación para alto/medio riesgo,
- exige `scope.yaml` con `authorized: true` para red,
- valida targets (CIDR, IP, dominio, URL) y aplica deny,
- audita cada decisión.

### Consecuencias

- (+) El modelo no puede ejecutar red sin scope.
- (+) El operador ve el riesgo antes de ejecutar.
- (+) Hay trazabilidad.
- (−) Los regex pueden fallar con ofuscación.
- (−) Puede generar falsos positivos (ej. `mount` en una ISO de laboratorio).
- (−) No reemplaza un sandbox.

### Mitigación

- Lista negativa conservadora y revisable.
- `--execute` obligatorio + confirmación.
- VM/snapshot para pruebas.
- Tests de regresión del guard.

---

## ADR-K5: Protocolo textual `<tool_call>`

**Fecha:** 2026-11-23
**Estado:** Accepted

### Contexto

Ollama soporta tools nativas, pero el formato varía entre versiones y modelos. El fine-tune necesita un formato estable, parseable y fácil de enseñar. Qwen2.5 ya usa `<tool_call>` XML en su plantilla.

### Decisión

Adoptar:

```xml
<tool_call>{"name":"shell","arguments":{"cmd":"..."}}</tool_call>
```

con respuestas `tool` que Qwen envuelve en `<tool_response>...</tool_response>`. El parser acepta fences, uno o más bloques y devuelve errores explícitos.

### Consecuencias

- (+) Independiente de la API de tools de Ollama.
- (+) Fácil de entrenar y de testear.
- (+) El modelo puede emitir varias llamadas.
- (−) No usa el mecanismo nativo de function calling.
- (−) Un JSON malformado requiere un turno de corrección.

### Mitigación

- Parser tolerante + error explícito al modelo.
- Ejemplos de tool-traces con formato exacto.
- Tests de protocolo.

---

## ADR-K6: Corpus privado, código público

**Fecha:** 2026-11-23
**Estado:** Accepted

### Contexto

Las fuentes tienen licencias incompatibles para una distribución conjunta: HackTricks es CC BY-NC 4.0, THR y GTFOBins son GPL-3.0, Arch Wiki es GFDL-1.3, tldr es CC BY 4.0 y Payloads es MIT.

### Decisión

Versionar el código, configuraciones y documentación. Mantener `data/`, `models/` y los pesos fuera de git. No publicar el corpus combinado ni el adapter sin revisión legal.

### Consecuencias

- (+) El harness se puede compartir y auditar.
- (+) Se evita redistribuir material no comercial.
- (−) El proyecto no es reproducible desde cero sin volver a descargar las fuentes.
- (−) Los pesos quedan atados al entorno local.

### Mitigación

- `fetch_sources.py` reproduce el corpus desde los repos originales.
- `stats.json` registra commits/fechas y licencias.
- `NOTICE` con atribuciones si se publica.
