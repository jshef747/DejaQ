import logging
import numpy as np
import torch
import torch.nn as nn
from huggingface_hub import PyTorchModelHubMixin
from transformers import AutoConfig, AutoModel, AutoTokenizer

logger = logging.getLogger("dejaq.services.classifier")

MODEL_ID = "nvidia/prompt-task-and-complexity-classifier"
COMPLEXITY_THRESHOLD = 0.2


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

        result["prompt_complexity_score"] = [
            round(
                0.35 * creativity
                + 0.25 * reasoning
                + 0.15 * constraint
                + 0.15 * domain_knowledge
                + 0.05 * contextual_knowledge
                + 0.05 * few_shots,
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
        cls._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logger.info("Classifier device: %s", cls._device)

        config = AutoConfig.from_pretrained(MODEL_ID)
        cls._tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
        cls._model = CustomModel(
            target_sizes=config.target_sizes,
            task_type_map=config.task_type_map,
            weights_map=config.weights_map,
            divisor_map=config.divisor_map,
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
        complexity = "hard" if score >= COMPLEXITY_THRESHOLD else "easy"

        logger.info(
            "Query classified as %s (score=%.4f, task=%s): %s",
            complexity, score, task_type, query[:80],
        )

        return {
            "complexity": complexity,
            "score": score,
            "task_type": task_type,
        }
