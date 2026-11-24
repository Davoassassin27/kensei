# Entrenamiento y despliegue

## Estado del entrenamiento

- Dataset listo: **6.061 ejemplos** (5.940 train / 121 val), 0 errores de validación.
- `train_qlora.py --check-only` ya se ejecutó en Windows: 400 ejemplos, 450 tokens promedio, p95 770, 54,3 % de tokens en turnos `assistant`.
- **Modelo actual en Ollama:** `kensei` = Qwen2.5-Coder-7B-Instruct **abliterado** (bartowski Q4_K_M) + system prompt, **sin LoRA**. Ya funciona con RAG, guard y fallback de tool-calls.
- **Hardware detectado:** desktop Ryzen 7 5700X, **32 GB RAM**, **AMD Radeon RX 6700 XT 12 GB** (Vulkan, ~11 GB libres). Ollama corre el 7B Q4 a ~33 tok/s.
- **K3 ahora es viable en el desktop, no en Windows directamente:** 12 GB alcanza para QLoRA 7B con `seq=2048`, batch 1, `r=16`, gradient checkpointing, usando **Linux + ROCm**. En Windows AMD no hay una ruta estable de QLoRA; la notebook no tiene GPU discreta.
- **Modelo listo hoy:** el `kensei` prompt-only ya está servido en Ollama; el fine-tune es el siguiente paso, no un requisito para usar el CLI.

## Variantes de LoRA

Antes de entrenar, leé [ALTERNATIVAS-LORA.md](ALTERNATIVAS-LORA.md). Resumen:

- **DoRA:** mejor calidad a igual rank; `use_dora=True`.
- **PiSSA/QPiSSA:** inicialización por SVD; mejor convergencia.
- **LoRA+:** 1–2 % de mejora y hasta 2× velocidad; `create_loraplus_optimizer`.
- **LoRA-FA / VeRA / IA3:** menos memoria o adapter; menor evidencia en tool-use.
- **Spectrum / GaLore:** full-parameter con 24 GB; más complejidad y sin adapter para mergear.

La recomendación para Kensei es **QLoRA + rsLoRA + (DoRA o PiSSA) + LoRA+**, midiendo cada variante con el Dojo. No combines todas a ciegas.

Para el desktop con RX 6700 XT (12 GB), usá la receta conservadora:

```bash
uv run python scripts/train_qlora.py --config config/train_qlora_12gb.yaml
```

Empieza con `--limit 1000 --max-steps 100` para validar ROCm y el masking antes de la corrida completa.

## Hardware

QLoRA 4-bit para 7B, con `max_seq_length=4096`, batch 2 y grad accum 8:

| VRAM | Viabilidad | Ajustes |
| --- | --- | --- |
| 8 GB | solo 1.5B | base `Qwen/Qwen2.5-Coder-1.5B-Instruct`, r=16 |
| **12 GB (RX 6700 XT)** | **7B muy justo, pero posible** | **batch 1, seq 2048, r=16, grad accum 16, gradient checkpointing, Linux + ROCm** |
| 16 GB | 7B aceptable | batch 1–2, seq 4096 |
| 24 GB | 7B cómodo | batch 2–4, seq 4096–8192 |
| 48 GB+ | 7B + eval | batch 4–8, seq 8192 |

**Hardware confirmado (dev host):**

- Desktop: Ryzen 7 5700X, 32 GB RAM, **AMD Radeon RX 6700 XT 12 GB**. Ollama usa Vulkan para inferencia (7B Q4, 8k contexto, ~33 tok/s).
- Notebook Dell Inspiron 15 3525: sin GPU discreta; sirve para inferencia, no para entrenar 7B.
- Windows + AMD no es una ruta estable para QLoRA (PyTorch/ROCm es Linux; bitsandbytes en ROCm es experimental). Para entrenar local: **CachyOS/Ronin en el desktop con ROCm**, o WSL2 si tu versión de ROCm soporta `gfx1031`.
- Si ROCm no coopera, la alternativa free es una GPU cloud (Colab/Kaggle/RunPod) solo para la corrida de entrenamiento; la inferencia sigue local.

> El script `train_qlora.py` exige GPU. En Windows sin CUDA/ROCm podés correr `--check-only` para validar tokenización y longitudes.

## Stack

| Componente | Versión sugerida | Nota |
| --- | --- | --- |
| Python | 3.11 | 3.12/3.13 suelen funcionar |
| PyTorch | 2.5–2.7 | CUDA 12.x o ROCm 6.x |
| transformers | >= 4.46 | `apply_chat_template` estable |
| peft | >= 0.13 | LoRA + `use_rslora` |
| bitsandbytes | >= 0.44 | CUDA; en ROCm puede requerir build propio |
| datasets | >= 3.0 | solo para utilidades |
| accelerate | >= 1.0 | `device_map="auto"` |

### CUDA

```bash
cd kensei
uv venv --python 3.11
source .venv/bin/activate
uv pip install torch --index-url https://download.pytorch.org/whl/cu124
uv pip install transformers datasets peft accelerate bitsandbytes pyyaml rich httpx
```

### ROCm (AMD)

```bash
uv pip install torch --index-url https://download.pytorch.org/whl/rocm6.2
uv pip install transformers datasets peft accelerate pyyaml
# bitsandbytes ROCm: seguir el build oficial; si falla, usar Axolotl con ROCm.
```

En ROCm, `torch.cuda.is_available()` devuelve `True` (HIP emula CUDA). Si `bitsandbytes` no funciona, usá `config/axolotl.yml` con Axolotl en Linux.

## Preparar el dataset

```bash
uv run python scripts/build_tool_traces.py --manual-variants 2
uv run python scripts/build_sft.py --repeat-safety 3
uv run python scripts/validate_dataset.py --strict
uv run --extra check python scripts/train_qlora.py --check-only
```

`--check-only` solo necesita el extra `check` (transformers + jinja2, no torch):

```bash
uv sync --extra check
```

Imprime:

- ejemplos tokenizados,
- tokens promedio / p95 / máximo,
- proporción de tokens del assistant.

Si `assistant_token_ratio` es < 0.1, el masking no está funcionando: revisá el template y `normalize_messages`.

## Entrenar

```bash
uv run python scripts/train_qlora.py --config config/train_qlora.yaml
```

Para un smoke test de 50 pasos:

```bash
uv run python scripts/train_qlora.py --max-steps 50 --limit 200
```

Hiperparámetros de referencia (`config/train_qlora.yaml`):

| Parámetro | Valor | Por qué |
| --- | --- | --- |
| `r` | 32 | suficiente para estilo/protocolo sin sobreajustar |
| `alpha` | 64 | escala 2× el rank |
| `dropout` | 0.05 | regularización suave |
| `target_modules` | todas las lineales | Qwen2.5 responde bien a cobertura completa |
| `epochs` | 2 | más epochs memorizan y empeoran el base |
| `lr` | 1e-4 | QLoRA estable con cosine |
| `batch` | 2 × grad accum 8 | 16 efectivo |
| `max_seq_length` | 4096 | cubre tool-traces y secciones |

### Si hay OOM

1. `--max-seq-length 2048`.
2. `batch_size: 1`.
3. `gradient_accumulation_steps: 16`.
4. `r: 16`, `alpha: 32`.
5. `optim: paged_adamw_8bit`.
6. Reducir `max_per_source` y descartar ejemplos largos en `build_sft.py`.

### Señales de un mal entrenamiento

- Loss de validación sube mientras train baja: sobreajuste; menos epochs o más dropout.
- El modelo repite la misma introducción en todos los comandos: dataset demasiado homogéneo; revisar `doc-summary`.
- Deja de emitir `<tool_call>`: el formato se perdió; subir ejemplos `tool-trace` y bajar `doc-section`.
- Se niega a todo: exceso de `manual:safety`; balancear con casos autorizados.
- Copia URLs y licencias en cada respuesta: es aceptable, pero si domina, acortar el sufijo de fuente.

## Monitoreo

```bash
# loss y learning rate
tensorboard --logdir models/kensei-qwen2.5-coder-7b-lora/runs

# métricas rápidas
grep -E "loss|eval_loss" models/kensei-qwen2.5-coder-7b-lora/trainer_state.json | tail
```

Guardá por corrida:

- `kensei_train_meta.json` (lo escribe el script),
- commit del repo,
- hash del dataset,
- versión de torch/CUDA,
- GPU y VRAM.

## Merge y GGUF

```bash
uv run python scripts/export_gguf.py \
  --adapter models/kensei-qwen2.5-coder-7b-lora \
  --merged models/kensei-merged \
  --gguf models/kensei-f16.gguf \
  --quant Q4_K_M \
  --llama-cpp ~/src/llama.cpp
```

Requiere `llama.cpp` compilado:

```bash
git clone https://github.com/ggml-org/llama.cpp ~/src/llama.cpp
cd ~/src/llama.cpp
cmake -B build -DGGML_NATIVE=ON
cmake --build build -j
```

El script:

1. Carga el base en CPU (fp16/bf16), aplica `PeftModel.merge_and_unload()` y guarda el modelo mergeado.
2. Convierte a GGUF F16 con `convert_hf_to_gguf.py`.
3. Cuantiza con `llama-quantize` (por defecto `Q4_K_M`).
4. Genera `modelfiles/Kensei.Modelfile` apuntando al GGUF.

## Ollama

```bash
ollama create kensei -f modelfiles/Kensei.Modelfile
ollama run kensei
uv run kensei doctor --model kensei
```

Verificación mínima:

```bash
uv run kensei ask "¿Cómo listo los subvolúmenes Btrfs?" --model kensei
uv run kensei ask "systemctl no levanta nginx, diagnosticá" --model kensei --execute
uv run kensei recall "Kerberoasting" --k 5
```

En Ronin, Ollama escucha en `127.0.0.1:11434` y los modelos viven en `~/ai-models/ollama`. Si el servicio usa `ProtectHome=yes`, el modelo no se ve: Ronin ya lo reemplazó por `ProtectHome=read-only` + `ReadWritePaths`, pero verificá con `systemctl cat ollama`.

## Evaluación

```bash
# base
uv run python eval/run_eval.py --model qwen2.5-coder:7b --out reports/eval-base.json

# fine-tune
uv run python eval/run_eval.py --model kensei --out reports/eval-kensei.json

# con memoria local
uv run python eval/run_eval.py --model kensei --rag --out reports/eval-kensei-rag.json

# solo seguridad
uv run python eval/run_eval.py --model kensei --filter safety
```

El runner usa `config/scope.example.yaml` por defecto. Para evaluar contra otro scope:

```bash
uv run python eval/run_eval.py --model kensei --scope ~/.config/kensei/scope.yaml
```

En CPU (sin GPU), el primer caso carga el modelo y puede tardar; subí el timeout:

```bash
uv run python eval/run_eval.py --model qwen2.5-coder:7b --timeout 1200 --filter safety arch
```

## Costos de referencia (cloud)

| GPU | VRAM | Precio típico | Tiempo 7B/2 epochs |
| --- | --- | --- | --- |
| RTX 4090 | 24 GB | USD 0.40–0.80/h | 2–4 h |
| A100 40 GB | 40 GB | USD 1.00–2.00/h | 1–2 h |
| L40S | 48 GB | USD 1.00–1.50/h | 1–2 h |

El dataset de ~5.000 ejemplos con secuencias de ~1.500 tokens no debería costar más de USD 5–10.
