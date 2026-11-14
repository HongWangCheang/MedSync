"""Base vs fine-tuned: dense retrieval metrics on validation and the 50-question test set."""

import json
import sys
from pathlib import Path

from sentence_transformers import SentenceTransformer

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from finetune.dense_eval import answerable, load_index, metrics  # noqa: E402

HERE = Path(__file__).resolve().parent


def main():
    index = load_index()
    out = {}
    for name, path in (("base", "BAAI/bge-small-en-v1.5"), ("finetuned", str(HERE / "models" / "bge-small-medtrack"))):
        model = SentenceTransformer(path, device="cpu")
        encode = lambda texts: model.encode(texts, normalize_embeddings=True, batch_size=64,  # noqa: E731
                                            show_progress_bar=False)
        out[name] = {split: metrics(encode, index, answerable(f"{split}.json"))
                     for split in ("validation", "questions")}
        print(name, json.dumps(out[name]))
    (HERE / "data" / "dense_comparison.json").write_text(json.dumps(out, indent=2) + "\n")


if __name__ == "__main__":
    main()
