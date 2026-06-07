# LLM Service

`llm-service` is the private text-generation wrapper used by the F1 fact-checking stack. It runs a local `llama-server` instance over a Gemma GGUF model, exposes a small HTTP API, and provides the prompt-execution layer for the fact-check pipeline.

## Purpose

This service does not implement fact-checking logic itself. Its job is to:

- start or attach to `llama-server`
- forward chat-completion style requests to the local model
- apply the current thinking-mode policy
- return answer text, optional reasoning text, token usage, and timing metadata

In the current F1 system, `fact-check-service` uses this block as the LLM backend for prompt workflows such as:

- F1 relevance classification
- claim extraction
- claim classification and routing
- search-query generation for web claims
- verdict generation from structured and/or web evidence

## Runtime Role

At startup, the service either:

- launches `llama-server` locally with the configured GGUF model, or
- connects to an already running external `llama-server` when `LLM_EXTERNAL_LLAMA_SERVER=1`

On readiness, it exposes a small HTTP surface for other services to call. The F1 stack currently uses the non-streaming answer endpoint for strict JSON prompt workflows.

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

Returns:

- `answer`
- `reasoning_text` when the model emits separate reasoning
- `model`
- `elapsed_ms`
- token usage fields when available
- OCR context metadata such as `ocr_chars` and `ocr_truncated`

### `POST /v1/answer/stream`

Streams completion chunks and usage metadata. This is available for interactive consumers, but the current fact-check pipeline uses the non-streaming endpoint.

## Prompt Workflow Support

`fact-check-service` stores the F1-specific prompts and sends them to `llm-service` as plain text. The prompts are strict JSON extraction/classification/verdict tasks, and `llm-service` is responsible only for executing them against the model.

Current prompt categories:

- `claim_extraction.md`
- `claim_classification.md`
- `search_query_generation.md`
- `verdict_generation.md`
- `f1_relevance_classification.md`

The service itself is prompt-agnostic. It simply forwards the request text to `llama-server` and returns the generated answer. The JSON parsing, routing, and evidence logic live in `fact-check-service`.

## Thinking Mode

`thinking_mode` is a per-request toggle with two behaviors:

- `fast`: disables template thinking and instructs the model to provide only the final answer
- `thinking`: allows concise reasoning output when the global thinking-disable flag is not set

High-level behavior:

- fast requests always set `chat_template_kwargs={"enable_thinking": false}`
- thinking requests omit that override unless `LLM_DISABLE_THINKING=1`
- if thinking is globally disabled, the service falls back to fast-mode behavior

This matters for the F1 pipeline because the downstream JSON prompts are executed in fast mode and should return compact, parseable answers.

## Configuration

Key environment variables:

- `LLM_MODEL_PATH`: path to the GGUF model file
- `LLAMA_SERVER_BIN`: binary used to launch `llama-server`
- `LLAMA_HOST` / `LLAMA_PORT`: bind address for the local model server
- `LLAMA_SERVER_URL`: base URL when connecting to an existing server
- `LLM_HOST` / `LLM_PORT`: bind address for the FastAPI wrapper
- `LLM_MODEL_ALIAS`: model label returned in responses
- `LLM_CTX_SIZE`: context window size passed to `llama-server`
- `LLM_MAX_TOKENS`: default output cap for fast mode
- `LLM_THINKING_MAX_TOKENS` or `LLM_MAX_TOKENS_THINKING`: default output cap for thinking mode
- `LLM_TEMPERATURE`, `LLM_TOP_P`, `LLM_TOP_K`: generation controls
- `LLM_PARALLEL`, `LLM_GPU_LAYERS`, `LLM_DEVICE`, `LLM_FLASH_ATTN`, `LLM_FIT`: runtime tuning knobs for the local model server
- `LLM_KV_OFFLOAD`, `LLM_OP_OFFLOAD`: offload toggles
- `LLM_STARTUP_TIMEOUT_SECONDS`, `LLM_REQUEST_TIMEOUT_SECONDS`: startup and request timeouts
- `LLM_DISABLE_THINKING`: forces non-thinking behavior at the server level
- `LLM_EXTERNAL_LLAMA_SERVER`: skips local process startup and waits for an existing server
- `LLM_WARMUP_ON_STARTUP`: controls the startup warmup call

## Integration Points

`fact-check-service` depends on this service through `LLM_SERVICE_URL` and expects:

- stable JSON-oriented answers for extraction/classification prompts
- predictable fast-mode behavior for parsing
- optional `reasoning_text` support without breaking the final `answer`

The service does not know anything about structured facts, Brave Search, or F1 routing. Those decisions are made in `fact-check-service`, which supplies the prompts and interprets the responses.

## Limitations

- This block is not a fact-check engine by itself.
- It does not validate prompt output shape beyond forwarding model responses.
- JSON reliability depends on the prompt discipline enforced by `fact-check-service`.
- URL and image handling are not part of this service; they are normalized upstream before prompt execution.

