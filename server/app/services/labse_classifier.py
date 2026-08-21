import logging
import os

import joblib
import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

from app import config
from app.services.classifier import _select_device

logger = logging.getLogger("dejaq.services.labse_classifier")

MODEL_ID = "sentence-transformers/LaBSE"
HEAD_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model_artifacts", "head_full_labse.joblib")

# Matches dejaq-classifier-probe-multilang/scripts/embed_train_eval.py exactly
# (max_length, mean-pool, L2-normalize) - the head was trained on embeddings
# produced this way, so serving must reproduce it bit-for-bit or predictions
# drift from what the report measured.
_MAX_LENGTH = 256


def _mean_pool(last_hidden_state: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    mask = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
    summed = torch.sum(last_hidden_state * mask, 1)
    counts = torch.clamp(mask.sum(1), min=1e-9)
    return summed / counts


class LabseClassifierService:
    """Shadow-mode difficulty classifier: LaBSE embedding + a LogisticRegression
    head trained on 770 labelled items across seven languages
    (dejaq-classifier-probe-multilang/report.md). Computes and logs a decision
    on every text request but is never used to route one - see
    config.LABSE_SHADOW_ENABLED and openai_compat.py's "classify" step.
    """

    _model = None
    _tokenizer = None
    _head = None
    _device = None

    def __init__(self):
        if LabseClassifierService._model is None:
            self._load_model()

    @classmethod
    def _load_model(cls):
        logger.info("Loading LaBSE shadow classifier...")
        cls._device = _select_device()
        logger.info("LaBSE shadow classifier device: %s", cls._device)
        cls._tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
        cls._model = AutoModel.from_pretrained(MODEL_ID).to(cls._device)
        cls._model.eval()
        cls._head = joblib.load(HEAD_PATH)
        logger.info("LaBSE shadow classifier loaded successfully.")

    def _embed(self, query: str) -> np.ndarray:
        encoded = self._tokenizer(
            [query],
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=_MAX_LENGTH,
        ).to(self._device)
        with torch.no_grad():
            hidden = self._model(**encoded).last_hidden_state
            pooled = _mean_pool(hidden, encoded["attention_mask"])
            normed = torch.nn.functional.normalize(pooled, p=2, dim=1)
        return normed.cpu().numpy()

    def predict_complexity(self, query: str) -> dict:
        """Returns dict with keys: complexity, score, task_type - same shape
        as ClassifierService.predict_complexity, so callers can log/compare
        the two uniformly. Threshold: config.LABSE_CLASSIFIER_THRESHOLD.
        """
        embedding = self._embed(query)
        score = float(self._head.predict_proba(embedding)[0][1])
        complexity = "hard" if score >= config.LABSE_CLASSIFIER_THRESHOLD else "easy"
        return {
            "complexity": complexity,
            "score": score,
            "task_type": "labse_shadow",
        }
