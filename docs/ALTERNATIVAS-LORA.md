# Alternativas a LoRA para Kensei

**Fecha:** 2026-11-23
**Contexto:** Qwen2.5-Coder-7B-Instruct, QLoRA 4-bit, GPU local incierta.
**Pregunta:** ¿qué métodos free/local dan un rendimiento igual o mejor que LoRA?

## TL;DR

1. **LoRA no es una sola cosa.** QLoRA, DoRA, PiSSA, rsLoRA y LoRA+ son variantes del mismo esquema. La ruta más práctica para Kensei es **QLoRA + una de {DoRA, PiSSA} + LoRA+**, no cambiar de familia.
2. **Mejor calidad sin salir de PEFT:** **DoRA** (magnitud + dirección) o **PiSSA/QPiSSA** (inicialización por SVD). Ambas mantienen la arquitectura LoRA, se mergean y se exportan a GGUF igual.
3. **Más rápido y barato:** **LoRA+** (learning rates distintos para A y B), **LoRA-FA** (freeze A, entrena B) y **rsLoRA** (ya está activado en Kensei).
4. **Si tenés 24 GB y querés acercarte a full fine-tuning:** **Spectrum** (entrena solo módulos de alto SNR) o **GaLore** (full-parameter con gradientes low-rank). Más potencia, más ingeniería y no hay adapter para mergear.
5. **Si el límite es el tamaño del adapter:** **VeRA**, **IA3**, **LoHa/LoKr**. Muy pocos parámetros, pero menor evidencia en tool-use complejo.
6. **Sin GPU:** no hay magia. RAG + few-shot + decoding restringido (GBNF/Outlines) + el guard. Un 7B no se entrena en CPU en un tiempo razonable.

## Comparativa

| Método | Qué cambia respecto de LoRA | Calidad vs LoRA | Memoria de entrenamiento | Inferencia | Soporte PEFT | Para Kensei |
| --- | --- | --- | --- | --- | --- | --- |
| **QLoRA** | Base 4-bit NF4 + LoRA | ~igual a LoRA 16-bit; el paper lo compara con full FT | Mucho menor (7B en 12–16 GB) | Igual; se mergea | Sí | **Base actual** |
| **DoRA** | Descompone peso en magnitud + dirección; LoRA solo la dirección | Paper: supera consistentemente a LoRA en LLaMA/LLaVA/VL-BART | Algo más que LoRA (parámetro de magnitud); compatible con 4-bit | Igual si se mergea; si no, algo más de overhead | Sí (`use_dora=True`) | **Mejor upgrade directo** |
| **PiSSA / QPiSSA** | Inicializa A/B con los componentes principales de W; el resto queda residual | Mistral-7B GSM8K: 72,86 vs 67,70 LoRA; QPiSSA 70B: 86,05 vs 81,73 QLoRA | Igual que LoRA; SVD inicial (segundos con `pissa_niter_16`) | Igual; se mergea | Sí (`init_lora_weights="pissa"` o `"pissa_niter_16"`) | **Mejor convergencia** |
| **rsLoRA** | Escala por `alpha/sqrt(r)` en vez de `alpha/r` | Mejor a rank alto; estabiliza | Igual | Igual | Sí (`use_rslora=True`) | **Ya activado** |
| **LoRA+** | LR distinto para A y B (ratio ~16) | +1–2 % y hasta 2× velocidad de convergencia | Igual | Igual | Sí (`create_loraplus_optimizer`) | **Ganancia barata** |
| **LoRA-FA** | Congela A, entrena B; corrige el gradiente | Comparable a PEFT/full FT en paper; menos memoria de activaciones | Menor; permite rank alto sin explotar | Igual | Sí (`create_lorafa_optimizer`) | Plan B si falta VRAM |
| **AdaLoRA** | Asigna rank adaptativo por importancia | Mejor en presupuestos bajos | Similar | Igual | Sí, pero requiere `update_and_allocate()` por step | Útil si rank bajo; más código |
| **VeRA** | Matrices A/B compartidas y congeladas; entrena vectores por capa | “Same performance” que LoRA en paper (GLUE/E2E, 7B/13B) | Mucho menos params; solo lineales | Se puede mergear; checkpoint chico | Sí (`VeraConfig`) | Si el adapter debe ser diminuto |
| **IA3** | Vectores que escalan activaciones | Comparable en tareas acotadas; 0,01 % params en T0 | Muy bajo | Se mergea | Sí (`IA3Config`) | Probablemente underfit para tool-use |
| **LoHa / LoKr** | Producto Hadamard/Kronecker de matrices low-rank | Mayor rank efectivo con mismos params; muy usado en difusión | Similar | Mergeable | Sí (`LoHaConfig`, `LoKrConfig`) | Experimental para LLM |
| **BOFT / OFT** | Transformación ortogonal por bloques/butterfly | Preserva mejor el modelo base; bueno para estilo/generación | Más cómputo que LoRA | Se mergea | Sí (`BOFTConfig`) | No es la prioridad |
| **LoRA-GA** | Inicializa con SVD de gradientes estimados | GLUE +5,69 %; Llama2-7B GSM8K +11,52 %, HumanEval +5,05 % | Requiere full precision; **no cuantizado** | Igual | Sí (`preprocess_loraga`) | No entra en 16 GB con QLoRA |
| **MiCA / NoRA / CorDA / Astra / EVA** | Inicializaciones nuevas (menores/ortogonales/task-aware) | Prometedoras; menos evidencia independiente | Similar a LoRA; algunas requieren calibración | Igual | Sí, según versión de PEFT | Experimentar después de DoRA/PiSSA |
| **Spectrum** | Full FT solo de módulos con alto SNR; congela el resto | Paper: iguala full FT y mejora VRAM vs QLoRA en distribuido | Menor que full FT; probablemente > QLoRA | Modelo completo, no adapter | Vía Axolotl | 24 GB+, si buscás máximo |
| **GaLore** | Proyecta gradientes a low-rank; entrena todos los pesos | Full-parameter; paper: 7B en 24 GB, 65,5 % menos optimizer states | 24 GB para 7B (8-bit GaLore, per-layer) | Modelo completo | No (librería propia) | Alternativa seria a QLoRA en 24 GB |
| **Full fine-tuning** | Todos los pesos | Techo de calidad | 7B: ~80 GB+ con Adam fp16; no local típico | Modelo completo | — | No para esta etapa |
| **RAG + prompt/few-shot** | No toca pesos | Excelente para hechos; no enseña protocolo | Cero | Sin cambios | — | **Ya implementado** |

## Recomendación para Kensei

### Opción A — la más segura y compatible con lo actual

**QLoRA + rsLoRA + LoRA+.** Es el menor cambio posible:

```yaml
lora:
  r: 32
  alpha: 64
  use_rslora: true
  use_dora: false
  init_lora_weights: true
```

```python
from peft.optimizers import create_loraplus_optimizer
optimizer = create_loraplus_optimizer(
    model=model,
    optimizer_cls=bnb.optim.Adam8bit,
    lr=5e-5,
    loraplus_lr_ratio=16,
)
```

Ganancia esperada: 1–2 % de calidad y hasta 2× velocidad de convergencia, sin cambiar la memoria ni el despliegue.

### Opción B — mejor calidad probable, mismo despliegue

**QLoRA + DoRA + rsLoRA.** Solo hay que agregar `use_dora=True`:

```python
from peft import LoraConfig

config = LoraConfig(
    r=32,
    lora_alpha=64,
    lora_dropout=0.05,
    target_modules="all-linear",
    use_rslora=True,
    use_dora=True,
    bias="none",
    task_type="CAUSAL_LM",
)
```

DoRA agrega el parámetro de magnitud y algo de overhead de entrenamiento; para inferencia se mergea. El paper reporta mejoras consistentes sobre LoRA, sobre todo a rank bajo. Es el cambio más directo para Kensei.

### Opción C — mejor convergencia, misma arquitectura

**QPiSSA + rsLoRA.** Inicialización por SVD principal:

```python
config = LoraConfig(
    r=32,
    lora_alpha=64,
    target_modules="all-linear",
    use_rslora=True,
    init_lora_weights="pissa_niter_16",  # rápido; o "pissa" para SVD completo
    bias="none",
    task_type="CAUSAL_LM",
)
```

En el paper, PiSSA supera a LoRA y QPiSSA a QLoRA en GSM8K. Para QLoRA, PEFT documenta que PiSSA reduce el error de cuantización. Requiere cargar el modelo full-precision para la SVD (o usar la ruta de reemplazo de PEFT); `pissa_niter_16` tarda segundos en 7B.

> **No combinar todo a ciegas.** DoRA + PiSSA + LoRA+ + QLoRA puede ser incompatible o inestable. Elegí **A**, **B** o **C**, medí con el Dojo y recién después combiná dos mejoras como máximo.

## Si tenés 24 GB y querés más que LoRA

### Spectrum

- Calcula el SNR de cada módulo y entrena solo el top N %, congelando el resto.
- El paper reporta calidad cercana a full FT y mejor uso de VRAM que QLoRA en entornos distribuidos.
- Se integra con Axolotl: genera un YAML de `unfrozen_parameters`.
- **Costo:** no hay adapter; el resultado es un modelo completo. Más difícil de versionar y de servir en la notebook.
- **Cuándo:** tenés 24 GB, querés máxima calidad y podés dedicar tiempo a tunear el % de capas.

### GaLore

- Entrena **todos** los pesos, pero proyecta gradientes a low-rank; el paper muestra 7B en una RTX 4090 de 24 GB con 8-bit GaLore y per-layer updates.
- Calidad más cercana a full FT que LoRA; 65,5 % menos optimizer states (82,5 % con 8-bit).
- **Costo:** librería propia, no PEFT; más lento por proyecciones; no hay adapter para mergear.
- **Cuándo:** 24 GB, querés full-parameter y aceptás más complejidad.

### Full fine-tuning

- 7B con Adam fp16: ~80–112 GB de VRAM. Con 8-bit optimizer y checkpointing baja, pero sigue lejos de 24 GB.
- No es una opción local realista para la notebook. En cloud, es la referencia de calidad.

## Si el límite es el tamaño del adapter

- **VeRA:** un par de matrices compartidas y vectores por capa. El paper dice “same performance” que LoRA en GLUE/E2E y instruction tuning 7B/13B. Bueno si vas a guardar muchos adapters; solo lineales.
- **IA3:** vectores, ~0,01 % de parámetros. Puede funcionar para estilo, pero para un agente con tool-calls y negativas complejas suele quedarse corto.
- **LoHa/LoKr:** más rank efectivo con los mismos parámetros; muy usados en difusión, menos probados en LLM de terminal.

Para Kensei, el adapter de 7B con r=32 ya pesa poco (<500 MB). No vale la pena sacrificar calidad para ahorrar 300 MB.

## Implementaciones free/local

| Herramienta | Qué aporta | Límite |
| --- | --- | --- |
| **PEFT** | DoRA, PiSSA, rsLoRA, LoRA+, LoRA-FA, VeRA, IA3, LoHa, BOFT, AdaLoRA | Es la base de `train_qlora.py`; no acelera por sí sola |
| **Unsloth** | Implementación optimizada de LoRA/QLoRA/full FT; 2× más rápido y hasta 70 % menos VRAM (claim del proyecto); NVIDIA/AMD/Intel/CPU | Sigue siendo LoRA/QLoRA; no cambia la calidad del método |
| **Axolotl** | Configuración de LoRA/QLoRA/DoRA/Spectrum, FSDP, ROCm | Más pesado; útil si Spectrum entra en juego |
| **torchtune** | Recetas nativas PyTorch para LoRA/QLoRA | Ecosistema más chico |
| **LLaMA-Factory** | UI/CLI para LoRA/QLoRA y variantes | Menos control fino del masking |
| **llama.cpp** | Inferencia GGUF; históricamente tuvo `llama-finetune` | El fine-tuning nativo es limitado y menos mantenido que PEFT; no lo usaría para el adapter final |

## Qué haría con Kensei

1. **Mantener QLoRA + rsLoRA** como baseline reproducible.
2. **Probar DoRA** en una corrida corta (500–1.000 ejemplos, 1 época) y comparar con el Dojo.
3. **Probar PiSSA (`pissa_niter_16`)** en otra corrida corta.
4. **Agregar LoRA+** al ganador; medir velocidad y calidad.
5. Recién si sobra VRAM (24 GB), evaluar **Spectrum** o **GaLore** como experimento aparte, no como reemplazo del pipeline actual.
6. **No entrenar 7B en CPU.** Si no hay GPU, el valor está en RAG + few-shot + decoding restringido, que ya funcionan.

## Fuentes

- DoRA: [arXiv:2402.09353](https://arxiv.org/abs/2402.09353), ICML 2024 Oral.
- PiSSA: [arXiv:2404.02948](https://arxiv.org/abs/2404.02948), NeurIPS 2024 Spotlight.
- LoRA+: [arXiv:2402.12354](https://arxiv.org/abs/2402.12354).
- AdaLoRA: [arXiv:2303.10512](https://arxiv.org/abs/2303.10512), ICLR 2023.
- LoRA-FA: [arXiv:2308.03303](https://arxiv.org/abs/2308.03303).
- LoRA-GA: [arXiv:2407.05000](https://arxiv.org/abs/2407.05000).
- VeRA: [arXiv:2310.11454](https://arxiv.org/abs/2310.11454), ICLR 2024.
- GaLore: [arXiv:2403.03507](https://arxiv.org/abs/2403.03507), ICML 2024 Oral; [repo](https://github.com/jiaweizzhao/GaLore).
- Spectrum: [arXiv:2406.06623](https://arxiv.org/abs/2406.06623); [repo](https://github.com/arcee-ai/spectrum).
- PEFT (DoRA, PiSSA, LoRA+, LoRA-FA, VeRA, IA3, AdaLoRA): [docs](https://huggingface.co/docs/peft/main/en/developer_guides/lora).
- Unsloth: [repo](https://github.com/unslothai/unsloth).
- LoRA vs full FT (olvido): [arXiv:2410.21228](https://huggingface.co/papers/2410.21228).
