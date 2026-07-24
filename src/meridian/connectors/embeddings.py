"""News embeddings.

Pluggable provider: ``sentence-transformers/all-MiniLM-L6-v2`` when installed (the plan's
choice — fast on Apple Silicon, zero cost), otherwise a deterministic hashing embedding
so clustering/dedup still work with zero heavy deps (docs/DECISIONS.md D-005). Vectors are
stored as little-endian float32 BLOBs in ``news_items.embedding`` and compared by cosine.
"""

from __future__ import annotations

import hashlib
import math
import re

import numpy as np
from loguru import logger

_DIM_HASH = 256
_model = None
_provider: str | None = None
_TOKEN = re.compile(r"[a-z0-9]+")


def _load_model():
    global _model, _provider
    if _provider is not None:
        return _model
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore

        _model = SentenceTransformer("all-MiniLM-L6-v2")
        _provider = "sentence-transformers"
        logger.info("embeddings: using sentence-transformers/all-MiniLM-L6-v2 (384d)")
    except Exception:  # noqa: BLE001
        _model = None
        _provider = "hashing"
        logger.info("embeddings: sentence-transformers unavailable → hashing fallback (256d)")
    return _model


def provider() -> str:
    _load_model()
    return _provider or "hashing"


def _hash_embed(text: str) -> np.ndarray:
    """Deterministic bag-of-hashed-tokens embedding, L2-normalised."""
    vec = np.zeros(_DIM_HASH, dtype=np.float32)
    for tok in _TOKEN.findall((text or "").lower()):
        h = int.from_bytes(hashlib.blake2b(tok.encode(), digest_size=4).digest(), "little")
        idx = h % _DIM_HASH
        sign = 1.0 if (h >> 31) & 1 else -1.0
        vec[idx] += sign
    n = np.linalg.norm(vec)
    return vec / n if n > 0 else vec


def embed(texts: list[str]) -> list[np.ndarray]:
    model = _load_model()
    if model is not None:
        arr = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [np.asarray(v, dtype=np.float32) for v in arr]
    return [_hash_embed(t) for t in texts]


def embed_one(text: str) -> np.ndarray:
    return embed([text])[0]


def to_blob(vec: np.ndarray) -> bytes:
    return np.asarray(vec, dtype="<f4").tobytes()


def from_blob(blob: bytes | None) -> np.ndarray | None:
    if not blob:
        return None
    return np.frombuffer(blob, dtype="<f4")


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    if a is None or b is None or a.size == 0 or b.size == 0 or a.size != b.size:
        return 0.0
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    v = float(np.dot(a, b) / (na * nb))
    return 0.0 if math.isnan(v) else v
