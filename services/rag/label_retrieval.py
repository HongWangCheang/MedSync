"""Offline label retrieval and extractive, versioned answers."""

import hashlib
import json
import os
import re
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from urllib.parse import urlencode

import numpy as np
from fastembed import TextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder

from label_corpus import SECTIONS
from medtrack_server import FDA_URL, MedTrack, values

# A fine-tuned ONNX export can replace the stock model (see finetune/). MODEL_NAME then names the export and its
# directory hash, so cached passage vectors from a different model are never reused.
EMBED_MODEL_PATH = os.environ.get("MEDTRACK_EMBED_MODEL_PATH")
if EMBED_MODEL_PATH:
    _onnx = Path(EMBED_MODEL_PATH, "model.onnx")
    MODEL_NAME = "medtrack/bge-small-finetuned@" + hashlib.sha256(_onnx.read_bytes()).hexdigest()[:12]
else:
    MODEL_NAME = "BAAI/bge-small-en-v1.5"
RERANK_MODEL = os.environ.get("MEDTRACK_RERANK_MODEL", "Xenova/ms-marco-MiniLM-L-6-v2")
CACHE_DIR = Path(os.environ.get("MEDTRACK_CACHE_DIR", Path(__file__).with_name(".cache")))
WORD = re.compile(r"[a-z0-9]+")
STOP_WORDS = set("""
a about an and any are as at be by can could did do does for from had has have how i if in is it
its label me my of on or say show so that the their there these this to up was were what when where
which who will with would you your listed mentioned product medication medicine
""".split())
KEYWORD_WEIGHT = 0.42
RRF_K = 12
SEMANTIC_MIN_SCORE = float(os.environ.get("MEDTRACK_SEMANTIC_MIN_SCORE", "0.60"))
# Cross-encoder logit needed before rerank mode answers. Tuned on eval/validation.json only (tune_rerank.py).
RERANK_MIN_SCORE = float(os.environ.get("MEDTRACK_RERANK_MIN_SCORE", "-8.46"))
RERANK_POOL = int(os.environ.get("MEDTRACK_RERANK_POOL", "30"))


def words(text):
    return set(WORD.findall(text.lower())) - STOP_WORDS


def chunks(text, size=580):
    text = " ".join(text.split())
    while len(text) > size:
        end = max(text.rfind(mark, size // 2, size) for mark in (". ", "; ", "• ", "● "))
        end = end + 1 if end >= 0 else text.rfind(" ", 0, size)
        end = size if end <= 0 else end
        yield text[:end].strip()
        text = text[end:].strip()
    if text:
        yield text


def source_url(label_id, version):
    return FDA_URL + "?" + urlencode({"search": f'id:"{label_id}" AND version:"{version}"', "limit": 1})


@dataclass(frozen=True)
class Passage:
    id: str
    label_id: str
    version: str
    field: str
    text: str

    @property
    def section(self):
        return SECTIONS[self.field]

    @property
    def searchable(self):
        return self.section + "\n" + self.text

    def source(self):
        return {"id": self.id, "section": self.section, "text": self.text}


class LabelSnapshot:
    def __init__(self, records, public=True):
        self.records = {(r["id"], r["version"]): r for r in records}
        self.public = public

    def search(self, _query):
        return self.records.values()

    def get(self, label_id, version):
        return self.records.get((label_id, version))


class LabelIndex:
    def __init__(self, snapshot, model, reranker=None):
        self.snapshot = snapshot
        self.model = model
        self.reranker = reranker
        self.catalog = MedTrack(snapshot)
        self.lock = Lock()
        self.passages = []
        self.by_label = {}
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.execute("CREATE VIRTUAL TABLE passages USING fts5(label_key UNINDEXED, heading, excerpt, tokenize='porter unicode61')")
        rows = []
        for (label_id, version), record in sorted(snapshot.records.items()):
            scope = self.by_label[(label_id, version)] = []
            for field in SECTIONS:
                for entry, section in enumerate(values(record, field), 1):
                    for part, text in enumerate(chunks(section), 1):
                        passage = Passage(f"{field}:{entry}:{part}", label_id, version, field, text)
                        scope.append(len(self.passages))
                        self.passages.append(passage)
                        rows.append((len(self.passages), self.key(label_id, version), passage.section, text))
        self.db.executemany("INSERT INTO passages(rowid, label_key, heading, excerpt) VALUES (?, ?, ?, ?)", rows)
        self.matrix = None

    @staticmethod
    def key(label_id, version):
        return f"{label_id}/{version}"

    def prepare_vectors(self, cache_dir=CACHE_DIR):
        content = json.dumps([(p.label_id, p.version, p.id, p.searchable) for p in self.passages],
                             ensure_ascii=False).encode()
        digest = hashlib.sha256(MODEL_NAME.encode() + content).hexdigest()
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = cache_dir / f"passages-{digest}.npy"
        try:
            matrix = np.load(path, allow_pickle=False)
            if matrix.shape != (len(self.passages), 384) or not np.isfinite(matrix).all():
                raise ValueError("Unexpected embedding dimensions or invalid values")
        except (OSError, ValueError):
            matrix = np.asarray(list(self.model.passage_embed([p.searchable for p in self.passages], batch_size=32)),
                                dtype=np.float32)
            with tempfile.NamedTemporaryFile(dir=cache_dir, suffix=".npy", delete=False) as tmp:
                temporary = Path(tmp.name)
                try:
                    np.save(tmp, matrix, allow_pickle=False)
                    tmp.close()
                    temporary.replace(path)
                finally:
                    temporary.unlink(missing_ok=True)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        self.matrix = matrix / np.maximum(norms, 1e-12)

    def keyword(self, label_id, version, question):
        tokens = sorted(words(question))
        if not tokens:
            return []
        query = " OR ".join(f'"{token}"' for token in tokens)
        with self.lock:
            rows = self.db.execute(
                "SELECT rowid FROM passages WHERE passages MATCH ? AND label_key = ? "
                "ORDER BY bm25(passages, 0, 1.4, 1.0), rowid LIMIT 30",
                (query, self.key(label_id, version)),
            ).fetchall()
        return [row_id - 1 for (row_id,) in rows]

    def vector(self, label_id, version, question):
        scope = self.by_label[(label_id, version)]
        if not scope:
            return []
        query = next(iter(self.model.query_embed(question)))
        query = query / max(float(np.linalg.norm(query)), 1e-12)
        scores = self.matrix[scope] @ query
        return sorted(zip(scope, scores), key=lambda item: (-item[1], item[0]))[:30]

    def retrieve(self, label_id, version, question, mode):
        lexical = self.keyword(label_id, version, question)
        if mode == "keyword":
            return [(self.passages[i], None) for i in lexical[:5]]
        dense = dict(self.vector(label_id, version, question))
        rank = {i: KEYWORD_WEIGHT / (RRF_K + r) for r, i in enumerate(lexical, 1)}
        for r, i in enumerate(dense, 1):
            rank[i] = rank.get(i, 0) + (1 - KEYWORD_WEIGHT) / (RRF_K + r)
        ordered = sorted(rank, key=lambda i: (-rank[i], i))
        if mode == "rerank":
            return self.rerank(question, ordered[:RERANK_POOL])
        return [(self.passages[i], float(dense.get(i, -1))) for i in ordered[:5]]

    def rerank(self, question, candidates):
        """Re-score the fused candidate pool with a cross-encoder; scores are raw logits."""
        if not candidates:
            return []
        if self.reranker is None:
            raise RuntimeError("Rerank mode needs a cross-encoder; start the app with the reranker loaded.")
        scores = list(self.reranker.rerank(question, [self.passages[i].searchable for i in candidates]))
        ordered = sorted(zip(candidates, scores), key=lambda item: (-item[1], item[0]))
        return [(self.passages[i], float(score)) for i, score in ordered[:5]]

    def answer(self, question, mode, label_id=None, version=None, drug_name=None):
        result = {"status": "no_evidence", "sources": [], "selection_method": mode,
                  "source_url": None, "summary": None, "retrieved": [], "candidates": []}
        if drug_name is not None:
            candidates = self.catalog.search(drug_name)["labels"]
            if not candidates:
                return dict(result, status="no_match")
            if len(candidates) != 1:
                return dict(result, status="needs_selection", candidates=candidates)
            label_id, version = candidates[0]["id"], candidates[0]["version"]
        if self.snapshot.get(label_id, version) is None:
            return dict(result, status="no_match")
        tokens = words(question)
        if not tokens:
            return result
        hits = self.retrieve(label_id, version, question, mode)
        result["retrieved"] = [passage.source() for passage, _ in hits]
        if not hits:
            return result
        top, similarity = hits[0]
        if mode == "rerank":
            if similarity < RERANK_MIN_SCORE:
                return result
            return dict(result, status="answered", sources=[top.source()], summary=top.text,
                        source_url=source_url(label_id, version) if self.snapshot.public else None)
        matches = tokens & words(top.searchable)
        lexical_support = len(matches) >= min(2, len(tokens)) and len(matches) / len(tokens) >= 0.34
        if not (lexical_support or (similarity is not None and similarity >= SEMANTIC_MIN_SCORE)):
            return result
        excerpt = top.source()
        return dict(result, status="answered", sources=[excerpt], summary=top.text,
                    source_url=source_url(label_id, version) if self.snapshot.public else None)


def load_model():
    if EMBED_MODEL_PATH:
        from fastembed.common.model_description import ModelSource, PoolingType
        if MODEL_NAME not in {m["model"] for m in TextEmbedding.list_supported_models()}:
            # Same architecture and pooling as bge-small (CLS token, L2-normalised); weights come from the local export.
            TextEmbedding.add_custom_model(model=MODEL_NAME, pooling=PoolingType.CLS, normalization=True,
                                           sources=ModelSource(hf="local/bge-small-medtrack"), dim=384,
                                           model_file="model.onnx")
        return TextEmbedding(MODEL_NAME, specific_model_path=EMBED_MODEL_PATH, threads=2)
    return TextEmbedding(MODEL_NAME, cache_dir=str(CACHE_DIR / "model"), threads=2)


def load_reranker():
    return TextCrossEncoder(RERANK_MODEL, cache_dir=str(CACHE_DIR / "model"), threads=2)
