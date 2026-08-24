# -*- coding: utf-8 -*-
"""Rebuild the LaBSE routing classifier head from the in-repo training corpus.

Reads app/services/model_artifacts/classifier_corpus.jsonl, embeds every item
with LaBSE (mean-pool + L2-normalize, matching app/services/labse_classifier.py
exactly), fits a LogisticRegression head on the full corpus, and overwrites
app/services/model_artifacts/head_full_labse.joblib.

Deterministic: fixed random_state, no train/test split, no evaluation
scaffolding - this only rebuilds the shipped artifact. See
tests/test_classifier_eval_set.py for the fixed-set regression check.

Run with: uv run python scripts/rebuild_classifier_head.py
"""
import json
import os

import joblib
import numpy as np
import torch
from sklearn.linear_model import LogisticRegression
from transformers import AutoModel, AutoTokenizer

BASE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.path.join(BASE, "..", "app", "services", "model_artifacts", "classifier_corpus.jsonl")
HEAD_PATH = os.path.join(BASE, "..", "app", "services", "model_artifacts", "head_full_labse.joblib")

MODEL_ID = "sentence-transformers/LaBSE"
MAX_LENGTH = 256  # must match labse_classifier.py's serving-time embedding
RANDOM_STATE = 0


def load_corpus():
    items = []
    with open(CORPUS, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items


def mean_pool(last_hidden_state, attention_mask):
    mask = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
    summed = torch.sum(last_hidden_state * mask, 1)
    counts = torch.clamp(mask.sum(1), min=1e-9)
    return summed / counts


def embed(texts, tokenizer, model, device, batch_size=16):
    out = []
    with torch.no_grad():
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            enc = tokenizer(
                batch, padding=True, truncation=True, max_length=MAX_LENGTH,
                return_tensors="pt",
            ).to(device)
            hidden = model(**enc).last_hidden_state
            pooled = mean_pool(hidden, enc["attention_mask"])
            normed = torch.nn.functional.normalize(pooled, p=2, dim=1)
            out.append(normed.cpu().numpy())
    return np.concatenate(out, axis=0)


def main():
    items = load_corpus()
    print(f"Loaded {len(items)} corpus items from {CORPUS}")
    texts = [it["text"] for it in items]
    y = np.array([1 if it["label"] == "hard" else 0 for it in items])

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    model = AutoModel.from_pretrained(MODEL_ID).to(device)
    model.eval()

    X = embed(texts, tokenizer, model, device)

    clf = LogisticRegression(class_weight="balanced", max_iter=2000, random_state=RANDOM_STATE)
    clf.fit(X, y)

    joblib.dump(clf, HEAD_PATH)
    print(f"Wrote head to {HEAD_PATH}")


if __name__ == "__main__":
    main()
