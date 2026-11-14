"""Export the fine-tuned model to ONNX for fastembed and check it embeds like the PyTorch model."""

import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

HERE = Path(__file__).resolve().parent
SOURCE = HERE / "models" / "bge-small-medtrack"
TARGET = HERE / "models" / "bge-small-medtrack-onnx"


class Encoder(torch.nn.Module):
    def __init__(self, bert):
        super().__init__()
        self.bert = bert

    def forward(self, input_ids, attention_mask, token_type_ids):
        return self.bert(input_ids=input_ids, attention_mask=attention_mask,
                         token_type_ids=token_type_ids).last_hidden_state


def main():
    model = SentenceTransformer(str(SOURCE), device="cpu")
    TARGET.mkdir(parents=True, exist_ok=True)
    bert = model[0].auto_model.eval()
    tokenizer = model[0].tokenizer
    sample = tokenizer(["export sample"], return_tensors="pt")
    axes = {0: "batch", 1: "sequence"}
    torch.onnx.export(Encoder(bert), (sample["input_ids"], sample["attention_mask"], sample["token_type_ids"]),
                      str(TARGET / "model.onnx"), input_names=["input_ids", "attention_mask", "token_type_ids"],
                      output_names=["last_hidden_state"], opset_version=17, dynamo=False,
                      dynamic_axes={"input_ids": axes, "attention_mask": axes, "token_type_ids": axes,
                                    "last_hidden_state": axes})
    tokenizer.save_pretrained(str(TARGET))
    bert.config.save_pretrained(str(TARGET))
    for extra in ("config_sentence_transformers.json", "modules.json"):
        if (SOURCE / extra).exists():
            shutil.copy(SOURCE / extra, TARGET / extra)

    # Parity check in the serving venv (fastembed + onnxruntime) against the PyTorch model.
    texts = ["Can I take this with warfarin?", "Store between 20-25C (68-77F). Keep the carton."]
    expected = model.encode(texts, normalize_embeddings=True)
    np.save(HERE / "models" / "parity_expected.npy", expected)
    check = f"""
import os, sys, numpy as np
os.environ["MEDTRACK_EMBED_MODEL_PATH"] = {str(TARGET)!r}
sys.path.insert(0, {str(HERE.parent)!r})
from label_retrieval import load_model
got = np.array(list(load_model().embed({texts!r})))
want = np.load({str(HERE / "models" / "parity_expected.npy")!r})
print("min cosine ONNX vs PyTorch:", float(min((got * want).sum(1))))
"""
    subprocess.run([str(HERE.parent / ".venv" / "bin" / "python"), "-I", "-c", check], check=True)


if __name__ == "__main__":
    main()
