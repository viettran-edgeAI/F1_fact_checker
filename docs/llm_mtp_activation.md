# LLM MTP Activation

This document records the local Gemma 4 MTP activation process for `llm-service`.

## Active Profile

Docker Compose runs the tested Jetson MTP profile:

- target model: `/models/llm/gemma-4-E2B-it-qat-UD-Q4_K_XL.gguf`
- MTP draft model: `/models/llm/mtp/gemma-4-E2B-it-Q4_0-MTP.gguf`
- llama.cpp runtime: version `9625` or newer
- context window: `LLM_CTX_SIZE=8192`
- batch buffers: `LLM_BATCH_SIZE=512`, `LLM_UBATCH_SIZE=128`
- draft depth: `LLM_SPEC_DRAFT_N_MAX=2`
- CUDA graph capture: disabled with `GGML_CUDA_DISABLE_GRAPHS=1`

The service uses llama.cpp speculative decoding arguments equivalent to:

```text
--ctx-size 8192
--batch-size 512
--ubatch-size 128
--spec-type draft-mtp
--spec-draft-n-max 2
--model-draft /models/llm/mtp/gemma-4-E2B-it-Q4_0-MTP.gguf
--gpu-layers-draft all
```

## Rebuild Process

Rebuild the llama.cpp backend when the bundled runtime cannot load the MTP draft architecture or when upstream MTP fixes are needed:

```bash
rtk git -C /home/viettran_orin/llama.cpp pull --ff-only
rtk cmake -S /home/viettran_orin/llama.cpp -B /home/viettran_orin/llama.cpp/build -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=87 -DGGML_CUDA_FORCE_MMQ=ON -DGGML_CUDA_FA=ON -DCMAKE_BUILD_TYPE=Release
rtk cmake --build /home/viettran_orin/llama.cpp/build --target llama-server -j 5
```

Copy the rebuilt server and shared libraries into the repository bundle used by `docker/Dockerfile.llm`:

```bash
rtk cp -a \
  /home/viettran_orin/llama.cpp/build/bin/llama-server \
  /home/viettran_orin/llama.cpp/build/bin/libllama-server-impl.so \
  /home/viettran_orin/llama.cpp/build/bin/libllama.so* \
  /home/viettran_orin/llama.cpp/build/bin/libllama-common.so* \
  /home/viettran_orin/llama.cpp/build/bin/libmtmd.so* \
  /home/viettran_orin/llama.cpp/build/bin/libggml.so* \
  /home/viettran_orin/llama.cpp/build/bin/libggml-base.so* \
  /home/viettran_orin/llama.cpp/build/bin/libggml-cpu.so* \
  /home/viettran_orin/llama.cpp/build/bin/libggml-cuda.so* \
  third_party/llama-bin/bin/
```

Verify the bundled binary before rebuilding the image:

```bash
rtk env LD_LIBRARY_PATH=third_party/llama-bin/bin third_party/llama-bin/bin/llama-server --version
rtk env LD_LIBRARY_PATH=third_party/llama-bin/bin third_party/llama-bin/bin/llama-server --help | rg "spec-type|model-draft|spec-draft-n-max"
```

Then rebuild the image:

```bash
rtk docker compose build llm-service
```

## Startup Process

Clear host caches before loading the model when doing a cold MTP boot:

```bash
sudo sync && echo 3 | sudo tee /proc/sys/vm/drop_caches
```

Start the service:

```bash
rtk docker compose up -d llm-service
```

For the full app, use `./start_app.sh --build` or `./start_app.sh --no-build`. The startup script intentionally starts `llm-service` first, waits for `http://localhost:8081/healthz`, and only then starts OCR, fact-check, and web services. This ordering matters on the shared Jetson GPU because OCR can reserve enough CUDA memory during its warmup to prevent the Gemma target or MTP draft model from loading.

Watch for these success markers in the logs:

```text
loading draft model '/models/llm/mtp/gemma-4-E2B-it-Q4_0-MTP.gguf'
common_speculative_impl_draft_mtp: adding speculative implementation 'draft-mtp'
load_model: speculative decoding context initialized
```

Verify health and a small request:

```bash
rtk docker compose ps llm-service
rtk docker compose exec llm-service python3 -c 'import json, urllib.request; payload={"user_request":"Return exactly this JSON: {\"ok\": true}","max_tokens":32,"enable_thinking":False}; req=urllib.request.Request("http://127.0.0.1:8081/v1/answer", data=json.dumps(payload).encode(), headers={"Content-Type":"application/json"}, method="POST"); print(urllib.request.urlopen(req, timeout=120).read().decode())'
```

## Failure Notes

- A bundled llama.cpp runtime without Gemma 4 assistant support fails with `unknown model architecture: 'gemma4-assistant'`.
- With the rebuilt runtime, `LLM_CTX_SIZE=12288` can exceed available Jetson CUDA memory when MTP is enabled.
- With `LLM_CTX_SIZE=8192`, leaving CUDA graphs enabled can still fail during slot initialization. Keep `GGML_CUDA_DISABLE_GRAPHS=1` for this profile.
- When the full app starts OCR and LLM together, default llama.cpp prompt-processing buffers can still exceed the shared GPU memory budget. Keep `LLM_BATCH_SIZE=512` and `LLM_UBATCH_SIZE=128` unless a full `./start_app.sh --build` run verifies larger values.
- Do not start OCR before LLM on the MTP profile. Load `llm-service` first, then OCR and the dependent services.
