from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer


def _load_max_seq_length(model_dir: Path) -> int:
    config_path = model_dir / "sentence_bert_config.json"
    if not config_path.exists():
        return 256
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    return int(payload.get("max_seq_length", 256))


@dataclass(slots=True)
class MiniLMEmbedder:
    model_dir: Path
    tokenizer: Tokenizer
    session: ort.InferenceSession
    max_seq_length: int
    dimension: int

    @classmethod
    def from_model_dir(cls, model_dir: Path) -> "MiniLMEmbedder":
        tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
        max_seq_length = _load_max_seq_length(model_dir)
        tokenizer.enable_truncation(max_length=max_seq_length)
        tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        session = ort.InferenceSession(str(model_dir / "onnx" / "model.onnx"), providers=["CPUExecutionProvider"])
        output_shape = session.get_outputs()[0].shape
        dimension = int(output_shape[-1])
        return cls(
            model_dir=model_dir,
            tokenizer=tokenizer,
            session=session,
            max_seq_length=max_seq_length,
            dimension=dimension,
        )

    def encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)

        encodings = self.tokenizer.encode_batch(texts)
        input_ids = np.asarray([encoding.ids for encoding in encodings], dtype=np.int64)
        attention_mask = np.asarray([encoding.attention_mask for encoding in encodings], dtype=np.int64)
        token_type_ids = np.asarray([encoding.type_ids for encoding in encodings], dtype=np.int64)

        token_embeddings = self.session.run(
            None,
            {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "token_type_ids": token_type_ids,
            },
        )[0]
        return _mean_pool_and_normalize(token_embeddings, attention_mask)


def _mean_pool_and_normalize(token_embeddings: np.ndarray, attention_mask: np.ndarray) -> np.ndarray:
    mask = attention_mask[..., None].astype(np.float32)
    pooled = (token_embeddings * mask).sum(axis=1)
    pooled /= np.clip(mask.sum(axis=1), 1e-9, None)
    norms = np.linalg.norm(pooled, axis=1, keepdims=True)
    return (pooled / np.clip(norms, 1e-12, None)).astype(np.float32)
