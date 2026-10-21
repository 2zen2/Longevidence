"""Local embedding model (no API). BAAI/bge-small-en-v1.5 via fastembed/ONNX, 384 dimensions, cached under data/models."""
import numpy as np

from ..config import settings

MODEL = "BAAI/bge-small-en-v1.5"
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "   # bge's recommended instruction for short queries
_model = None


def _get():
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        _model = TextEmbedding(MODEL, cache_dir=str(settings.data_dir / "models"))
    return _model


def embed_docs(texts: list[str]) -> np.ndarray:
    v = np.array(list(_get().embed(texts)), dtype=np.float32)
    return v / np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-9)


def embed_query(q: str) -> np.ndarray:
    return embed_docs([QUERY_PREFIX + q])[0]
