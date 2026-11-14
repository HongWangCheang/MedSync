"""Fine-tune bge-small on generated questions with in-label hard negatives; pick the epoch on the validation set."""

import json
import random
import sys
from pathlib import Path

import numpy as np
from datasets import Dataset
from sentence_transformers import SentenceTransformer, SentenceTransformerTrainer, SentenceTransformerTrainingArguments
from sentence_transformers.losses import MultipleNegativesRankingLoss
from sentence_transformers.training_args import BatchSamplers

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from finetune.dense_eval import answerable, load_index, metrics  # noqa: E402

BASE = "BAAI/bge-small-en-v1.5"
HERE = Path(__file__).resolve().parent
OUT = HERE / "models"
EPOCHS = (1, 2, 3, 4)


def encoder(model):
    return lambda texts: model.encode(texts, normalize_embeddings=True, batch_size=64, show_progress_bar=False)


def main():
    random.seed(0)
    rows = [json.loads(line) for line in (HERE / "data" / "train.jsonl").read_text().splitlines()]
    index = load_index()
    base = SentenceTransformer(BASE, device="cpu")
    # Hard negative: the passage from the same label that the *base* model ranks highest but is wrong.
    by_label = {}
    for p in index.passages:
        by_label.setdefault((p.label_id, p.version), []).append(p)
    triples = []
    for row in rows:
        others = [p for p in by_label[(row["label_id"], row["version"])] if p.id != row["passage_id"]]
        if not others:
            continue
        sims = base.encode([p.searchable for p in others], normalize_embeddings=True) @ \
            base.encode([row["question"]], normalize_embeddings=True)[0]
        triples.append({"anchor": row["question"], "positive": row["positive"],
                        "negative": others[int(np.argmax(sims))].searchable})
    print(f"{len(triples)} training triples")
    data = Dataset.from_list(triples).shuffle(seed=0)

    validation = answerable("validation.json")
    results = {0: metrics(encoder(base), index, validation)}
    print("epoch 0 (base) validation:", results[0])
    best_epoch, best_mrr = 0, results[0]["mrr"]
    for epochs in EPOCHS:
        model = SentenceTransformer(BASE, device="cpu")
        args = SentenceTransformerTrainingArguments(
            output_dir=str(OUT / "checkpoints"), num_train_epochs=epochs, per_device_train_batch_size=32,
            learning_rate=2e-5, warmup_ratio=0.1, seed=0, save_strategy="no", logging_steps=50, report_to=[],
            batch_sampler=BatchSamplers.NO_DUPLICATES,  # three questions share a passage: keep them out of one batch
            use_cpu=True)  # PyTorch MPS deadlocked in backward() here; a 33M model trains fine on CPU
        SentenceTransformerTrainer(model=model, args=args, train_dataset=data,
                                   loss=MultipleNegativesRankingLoss(model)).train()
        results[epochs] = metrics(encoder(model), index, validation)
        print(f"epoch {epochs} validation:", results[epochs])
        if results[epochs]["mrr"] > best_mrr:
            best_epoch, best_mrr = epochs, results[epochs]["mrr"]
            model.save(str(OUT / "bge-small-medtrack"))
    (HERE / "data" / "epoch_selection.json").write_text(json.dumps(
        {"validation": results, "chosen_epochs": best_epoch}, indent=2) + "\n")
    print("chosen epochs:", best_epoch)


if __name__ == "__main__":
    main()
