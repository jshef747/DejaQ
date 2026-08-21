import json
import logging
import numpy as np
import torch
import torch.nn as nn
from huggingface_hub import PyTorchModelHubMixin, hf_hub_download
from transformers import AutoModel, AutoTokenizer

from app import config

logger = logging.getLogger("dejaq.services.classifier")

MODEL_ID = "nvidia/prompt-task-and-complexity-classifier"


def _probe_device() -> torch.device:
    """Capability probe, not an OS/machine check: CUDA, then Apple Metal, then CPU."""
    if torch.cuda.is_available():
        return torch.device("cuda")
    # torch.backends.mps may not exist on older torch builds at all, and even
    # when present, "available" (macOS/device supports Metal) and "built"
    # (this torch wheel was compiled with MPS support) are separate checks.
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available() and mps.is_built():
        return torch.device("mps")
    return torch.device("cpu")


def _select_device() -> torch.device:
    override = config.TORCH_DEVICE
    if override == "auto":
        return _probe_device()
    if override in ("cpu", "cuda", "mps"):
        if override == "cuda" and not torch.cuda.is_available():
            logger.warning("DEJAQ_TORCH_DEVICE=cuda but CUDA is unavailable; falling back to probe")
            return _probe_device()
        if override == "mps":
            mps = getattr(torch.backends, "mps", None)
            if mps is None or not mps.is_available() or not mps.is_built():
                logger.warning("DEJAQ_TORCH_DEVICE=mps but Metal is unavailable; falling back to probe")
                return _probe_device()
        return torch.device(override)
    logger.warning("Unrecognised DEJAQ_TORCH_DEVICE=%r; falling back to probe", override)
    return _probe_device()


# --- NVIDIA model architecture (required for loading) ---

class MeanPooling(nn.Module):
    def __init__(self):
        super(MeanPooling, self).__init__()

    def forward(self, last_hidden_state, attention_mask):
        input_mask_expanded = (
            attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
        )
        sum_embeddings = torch.sum(last_hidden_state * input_mask_expanded, 1)
        sum_mask = input_mask_expanded.sum(1)
        sum_mask = torch.clamp(sum_mask, min=1e-9)
        mean_embeddings = sum_embeddings / sum_mask
        return mean_embeddings


class MulticlassHead(nn.Module):
    def __init__(self, input_size, num_classes):
        super(MulticlassHead, self).__init__()
        self.fc = nn.Linear(input_size, num_classes)

    def forward(self, x):
        return self.fc(x)


class CustomModel(nn.Module, PyTorchModelHubMixin):
    def __init__(self, target_sizes, task_type_map, weights_map, divisor_map):
        super(CustomModel, self).__init__()
        self.backbone = AutoModel.from_pretrained("microsoft/DeBERTa-v3-base")
        self.target_sizes = target_sizes.values()
        self.task_type_map = task_type_map
        self.weights_map = weights_map
        self.divisor_map = divisor_map

        self.heads = [
            MulticlassHead(self.backbone.config.hidden_size, sz)
            for sz in self.target_sizes
        ]
        for i, head in enumerate(self.heads):
            self.add_module(f"head_{i}", head)

        self.pool = MeanPooling()

    def compute_results(self, preds, target, decimal=4):
        if target == "task_type":
            top2_indices = torch.topk(preds, k=2, dim=1).indices
            softmax_probs = torch.softmax(preds, dim=1)
            top2_probs = softmax_probs.gather(1, top2_indices)
            top2 = top2_indices.detach().cpu().tolist()
            top2_prob = top2_probs.detach().cpu().tolist()

            top2_strings = [
                [self.task_type_map[str(idx)] for idx in sample] for sample in top2
            ]
            top2_prob_rounded = [
                [round(value, 3) for value in sublist] for sublist in top2_prob
            ]

            counter = 0
            for sublist in top2_prob_rounded:
                if sublist[1] < 0.1:
                    top2_strings[counter][1] = "NA"
                counter += 1

            task_type_1 = [sublist[0] for sublist in top2_strings]
            task_type_2 = [sublist[1] for sublist in top2_strings]
            task_type_prob = [sublist[0] for sublist in top2_prob_rounded]

            return (task_type_1, task_type_2, task_type_prob)
        else:
            preds = torch.softmax(preds, dim=1)
            weights = np.array(self.weights_map[target])
            weighted_sum = np.sum(np.array(preds.detach().cpu()) * weights, axis=1)
            scores = weighted_sum / self.divisor_map[target]
            scores = [round(value, decimal) for value in scores]
            if target == "number_of_few_shots":
                scores = [x if x >= 0.05 else 0 for x in scores]
            return scores

    def process_logits(self, logits):
        result = {}

        task_type_results = self.compute_results(logits[0], target="task_type")
        result["task_type_1"] = task_type_results[0]
        result["task_type_2"] = task_type_results[1]
        result["task_type_prob"] = task_type_results[2]

        for i, target in enumerate(
            ["creativity_scope", "reasoning", "contextual_knowledge",
             "number_of_few_shots", "domain_knowledge", "no_label_reason",
             "constraint_ct"],
            start=1,
        ):
            result[target] = self.compute_results(logits[i], target=target)

        # Weights re-derived by a 12,000-vector joint weight+threshold search
        # over a 122-item hand-labelled corpus (dejaq-routing-weights-hebrew),
        # replacing NVIDIA's published weights (0.35/0.25/0.15/0.15/0.05/0.05).
        # This point strictly dominates the old weights on that corpus - fewer
        # false positives AND fewer false negatives, no trade required - and
        # a 5-fold cross-validation held up: +5.7 points of accuracy over
        # baseline in every fold but one tie. It is free, not a fix for
        # everything: an independent 22-question proof-heavy check (firstmate,
        # 2026-08-21) found it changes NOTHING on that set (13/22 correct
        # either way, four proof questions score slightly LOWER) - the gain
        # lives in the broad middle of the corpus, not the hard-proof tail.
        # It also does not touch Hebrew: every Hebrew hard item still misses
        # under these weights (Hebrew previously routed around this classifier
        # entirely via a dedicated judge; that judge is gone as of the LaBSE
        # shadow classifier - see config.LABSE_CLASSIFIER_THRESHOLD - and
        # Hebrew now falls through to this classifier like every other
        # language until the captain cuts over). Must ship together with
        # DEJAQ_ROUTING_THRESHOLD's own move to 0.2986 - this weight vector
        # was searched jointly with that threshold, not independently.
        result["prompt_complexity_score"] = [
            round(
                0.155 * creativity
                + 0.258 * reasoning
                + 0.240 * constraint
                + 0.095 * domain_knowledge
                + 0.147 * contextual_knowledge
                + 0.106 * few_shots,
                5,
            )
            for creativity, reasoning, constraint, domain_knowledge, contextual_knowledge, few_shots in zip(
                result["creativity_scope"],
                result["reasoning"],
                result["constraint_ct"],
                result["domain_knowledge"],
                result["contextual_knowledge"],
                result["number_of_few_shots"],
            )
        ]

        return result

    def forward(self, batch):
        input_ids = batch["input_ids"]
        attention_mask = batch["attention_mask"]
        outputs = self.backbone(input_ids=input_ids, attention_mask=attention_mask)

        last_hidden_state = outputs.last_hidden_state
        mean_pooled = self.pool(last_hidden_state, attention_mask)

        logits = [head(mean_pooled) for head in self.heads]
        return self.process_logits(logits)


# --- Service class ---

class ClassifierService:
    _model = None
    _tokenizer = None
    _device = None

    def __init__(self):
        if ClassifierService._model is None:
            self._load_model()

    @classmethod
    def _load_model(cls):
        logger.info("Loading NVIDIA prompt-task-and-complexity-classifier...")
        cls._device = _select_device()
        # First few calls on a fresh "mps" device pay a one-time Metal
        # compilation cost (~1.8s first call, a few hundred ms for the next
        # several, then a stable ~48ms once warm). This is a singleton
        # loaded once in a long-lived process, so it's a startup cost only.
        logger.info("Classifier device: %s", cls._device)

        config_path = hf_hub_download(MODEL_ID, "config.json")
        with open(config_path) as f:
            config = json.load(f)
        cls._tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
        cls._model = CustomModel(
            target_sizes=config["target_sizes"],
            task_type_map=config["task_type_map"],
            weights_map=config["weights_map"],
            divisor_map=config["divisor_map"],
        ).from_pretrained(MODEL_ID)
        cls._model.to(cls._device)
        cls._model.eval()
        logger.info("Classifier loaded successfully.")

    def predict_complexity(self, query: str) -> dict:
        """
        Classify a query's complexity using NVIDIA's DeBERTa-based classifier.
        Returns dict with keys: complexity, score, task_type
        """
        encoded = self._tokenizer(
            [f"Prompt: {query}"],
            return_tensors="pt",
            add_special_tokens=True,
            max_length=512,
            padding=True,
            truncation=True,
        ).to(self._device)

        with torch.no_grad():
            result = self._model(encoded)

        score = result["prompt_complexity_score"][0]
        task_type = result["task_type_1"][0]
        # Descriptive label only, at the classifier's own fixed cut (matching
        # the re-derived weights' own threshold, 0.2986) - not used for real
        # request routing, which recomputes "complexity" from the workspace's
        # routing_threshold one line after this call returns
        # (app/routers/openai_compat.py). Kept for callers/tests that want a
        # quick label without a workspace config in hand.
        complexity = "hard" if score >= 0.2986 else "easy"

        logger.debug("Query classified as %s (score=%.4f, task=%s)", complexity, score, task_type)

        return {
            "complexity": complexity,
            "score": score,
            "task_type": task_type,
        }
