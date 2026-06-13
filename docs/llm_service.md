# LLM Service

`llm-service` is the private text-generation wrapper used by the F1 fact-checking stack. It runs a local `llama-server` instance over a Gemma GGUF model, exposes a small HTTP API, and provides the prompt-execution layer for the fact-check pipeline.

## Purpose

This service does not implement fact-checking logic itself. Its job is to:

- start or attach to `llama-server`
- forward chat-completion style requests to the local model
- apply the current thinking-mode policy
- return answer text, optional reasoning text, token usage, throughput, and timing metadata

In the current F1 system, `fact-check-service` uses this block as the LLM backend for prompt workflows such as:

- claim extraction
- claim classification and routing
- search-query generation for web claims
- verdict generation from structured and/or web evidence

## Runtime Role

At startup, the service either:

- launches `llama-server` locally with the configured GGUF model, or
- connects to an already running external `llama-server` when `LLM_EXTERNAL_LLAMA_SERVER=1`

On readiness, it exposes a small HTTP surface for other services to call. The F1 stack uses the non-streaming answer endpoint for strict JSON prompt workflows and the streaming answer endpoint for live verdict generation.

## Endpoints

### `GET /healthz`

Returns `200` only when `llama-server` is ready. This is used as a readiness check for the model runtime.

### `POST /v1/answer`

Accepts:

- `ocr_markdown`: optional OCR context
- `user_request`: the prompt text
- `conversation_history`: bounded chat history
- `max_tokens`: optional override
- `thinking_mode`: `fast` or `thinking`
- `enable_thinking`: optional explicit request-level override; when set, it takes precedence over legacy `thinking_mode`

Returns:

- `answer`
- `reasoning_text` when the model emits separate reasoning
- `model`
- `elapsed_ms`
- token usage fields when available
- `tokens_per_second` when the backend can compute it
- OCR context metadata such as `ocr_chars` and `ocr_truncated`

### `POST /v1/answer/stream`

Streams completion chunks and usage metadata. The final `done` event includes `tokens_per_second` when the backend can compute it. The fact-check pipeline uses this endpoint for live verdict generation, while the blocking endpoint remains available for strict JSON prompt workflows.

## Prompt Workflow Support

`fact-check-service` stores the F1-specific prompts and sends them to `llm-service` as plain text. The prompts are strict JSON extraction/classification/verdict tasks, and `llm-service` is responsible only for executing them against the model.

Current prompt categories:

- `claim_extraction.md`
- `claim_classification.md`
- `search_query_generation.md`
- `verdict_generation.md`

The service itself is prompt-agnostic. It simply forwards the request text to `llama-server` and returns the generated answer. The JSON parsing, routing, and evidence logic live in `fact-check-service`.

## Thinking Mode

Thinking control is request-level. New callers should send `enable_thinking` directly; the legacy `thinking_mode` field remains supported for compatibility.

`enable_thinking=false` / `thinking_mode=fast`:

- disables template thinking with `chat_template_kwargs={"enable_thinking": false}`
- instructs the model to return only the final answer

`enable_thinking=true` / `thinking_mode=thinking`:

- omits the template override so the model can use thinking when the global thinking-disable flag is not set
- uses the thinking token default unless `max_tokens` is explicitly supplied

If `LLM_DISABLE_THINKING=1`, all requests fall back to non-thinking behavior. The explicit `max_tokens` override accepts values up to 4096.

In the F1 pipeline, claim extraction, claim classification, web query generation, and verdict generation use non-thinking request mode. Verdict generation is intentionally compact so the final aggregation step does not spend context on unnecessary reasoning or evidence-by-evidence prose.

## Configuration

Key environment variables:

- `LLM_MODEL_PATH`: path to the GGUF model file
- `LLAMA_SERVER_BIN`: binary used to launch `llama-server`
- `LLAMA_HOST` / `LLAMA_PORT`: bind address for the local model server
- `LLAMA_SERVER_URL`: base URL when connecting to an existing server
- `LLM_HOST` / `LLM_PORT`: bind address for the FastAPI wrapper
- `LLM_MODEL_ALIAS`: model label returned in responses
- `LLM_CTX_SIZE`: context window size passed to `llama-server`; Docker Compose currently sets this to `8192` for the tested Jetson Gemma 4 MTP profile
- `LLM_MAX_TOKENS`: default output cap for fast mode
- `LLM_THINKING_MAX_TOKENS` or `LLM_MAX_TOKENS_THINKING`: default output cap for thinking mode
- `LLM_TEMPERATURE`, `LLM_TOP_P`, `LLM_TOP_K`: generation controls
- `LLM_PARALLEL`, `LLM_BATCH_SIZE`, `LLM_UBATCH_SIZE`, `LLM_GPU_LAYERS`, `LLM_DEVICE`, `LLM_FLASH_ATTN`, `LLM_FIT`: runtime tuning knobs for the local model server
- `LLM_MTP_ENABLED`: enables llama.cpp speculative decoding with Gemma 4 MTP when set to `1`, `true`, or `yes`
- `LLM_SPEC_TYPE`: speculative decoding type passed to llama.cpp; Docker Compose currently uses `draft-mtp`
- `LLM_SPEC_DRAFT_MODEL_PATH`: explicit local GGUF drafter path; Docker Compose uses `/models/llm/mtp/gemma-4-E2B-it-Q4_0-MTP.gguf`
- `LLM_SPEC_DRAFT_N_MAX`: maximum drafted tokens; Docker Compose currently uses `2`
- `LLM_SPEC_DRAFT_GPU_LAYERS` / `LLM_SPEC_DRAFT_DEVICE`: optional draft-model offload controls
- `GGML_CUDA_DISABLE_GRAPHS`: set to `1` in Docker Compose for the Jetson MTP profile to avoid CUDA graph allocation failures during slot initialization
- `LLM_KV_OFFLOAD`, `LLM_OP_OFFLOAD`: offload toggles
- `LLM_STARTUP_TIMEOUT_SECONDS`, `LLM_REQUEST_TIMEOUT_SECONDS`: startup and request timeouts
- `LLM_DISABLE_THINKING`: forces non-thinking behavior at the server level
- `LLM_EXTERNAL_LLAMA_SERVER`: skips local process startup and waits for an existing server
- `LLM_WARMUP_ON_STARTUP`: controls the startup warmup call

## MTP / Speculative Decoding

`llm-service` starts Gemma with llama.cpp MTP speculative decoding when `LLM_MTP_ENABLED=1`. Docker Compose enables the tested Jetson profile by default. The target model is `gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf`, and the local MTP drafter is `models/llm/mtp/gemma-4-E2B-it-Q4_0-MTP.gguf`:

```text
--ctx-size 8192 --batch-size 512 --ubatch-size 128 --spec-type draft-mtp --spec-draft-n-max 2 --model-draft <drafter>
```

The Unsloth Gemma 4 QAT model card notes that MTP drafts are verified by the target model, so the acceleration path should not change generated output. The bundled llama.cpp runtime was rebuilt to version `9625` so it can load the Gemma 4 assistant draft architecture. On the current Jetson profile, the service also sets `GGML_CUDA_DISABLE_GRAPHS=1`; without that setting, the target and draft model load but slot initialization can fail during CUDA graph capture. The full stack also uses reduced llama.cpp batch buffers because OCR and LLM share the same 8 GB GPU memory budget. See [llm_mtp_activation.md](/home/viettran_orin/Documents/F1_fact_checker/docs/llm_mtp_activation.md) for the activation and verification process.

## Integration Points

`fact-check-service` depends on this service through `LLM_SERVICE_URL` and expects:

- stable JSON-oriented answers for extraction/classification prompts
- predictable fast-mode behavior for parsing
- optional `reasoning_text` support without breaking the final `answer`
- optional throughput metadata such as `tokens_per_second` for runtime reporting, including streamed verdict generation

The service does not know anything about structured facts, Brave Search, or F1 routing. Those decisions are made in `fact-check-service`, which supplies the prompts and interprets the responses.

## GPU Runtime

Docker Compose runs `llm-service` with the NVIDIA runtime and `NVIDIA_VISIBLE_DEVICES=all`. `LLM_GPU_LAYERS` must be greater than zero for Gemma inference to use CUDA offload. The current Compose profile uses `LLM_GPU_LAYERS=all`, `LLM_FIT=on`, `LLM_CTX_SIZE=8192`, `LLM_BATCH_SIZE=512`, `LLM_UBATCH_SIZE=128`, Gemma 4 MTP, and `GGML_CUDA_DISABLE_GRAPHS=1`.

## Limitations

- This block is not a fact-check engine by itself.
- It does not validate prompt output shape beyond forwarding model responses.
- JSON reliability depends on the prompt discipline enforced by `fact-check-service`.
- URL and image handling are not part of this service; they are normalized upstream before prompt execution.
