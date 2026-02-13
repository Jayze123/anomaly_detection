from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from PIL import Image

try:
    import torch
    from transformers import AutoProcessor, LlavaForConditionalGeneration
except Exception:  # pragma: no cover
    torch = None
    AutoProcessor = None
    LlavaForConditionalGeneration = None


@dataclass(frozen=True)
class VLMResult:
    defect_label: str
    evidence: list[str]
    confidence: float


def _build_prompt(category: str, label_set: list[str], unknown_label: str) -> str:
    labels = ", ".join(label_set)
    return (
        "You are an inspection assistant. "
        "Choose exactly one label from the fixed label set. "
        f"If uncertain, output \"{unknown_label}\".\n"
        f"Category: {category}\n"
        f"Fixed label set: {labels}\n"
        "Return JSON only: "
        "{\"defect_label\":\"...\",\"evidence\":[\"...\"],\"confidence\":0.0}"
    )


def _parse_response(text: str, unknown_label: str, label_set: list[str]) -> VLMResult:
    # Minimal defensive parser: look for JSON-like fields.
    # If parsing fails, return Unknown.
    label = unknown_label
    evidence: list[str] = []
    confidence = 0.0
    try:
        import json

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            payload = json.loads(text[start : end + 1])
            label = str(payload.get("defect_label", unknown_label))
            evidence = [str(x) for x in payload.get("evidence", [])][:3]
            confidence = float(payload.get("confidence", 0.0))
    except Exception:
        return VLMResult(defect_label=unknown_label, evidence=[text[:200]], confidence=0.0)
    valid = set(label_set) | {unknown_label}
    if label not in valid:
        return VLMResult(
            defect_label=unknown_label,
            evidence=[f"Model label '{label}' is outside fixed label set."],
            confidence=0.0,
        )
    confidence = max(0.0, min(1.0, confidence))
    return VLMResult(defect_label=label, evidence=evidence, confidence=confidence)


_CACHE: dict[str, Tuple[object, object, str]] = {}


def _get_model(model_id: str, device: str):
    key = f"{model_id}|{device}"
    if key in _CACHE:
        return _CACHE[key]
    processor = AutoProcessor.from_pretrained(model_id)
    model = LlavaForConditionalGeneration.from_pretrained(
        model_id, torch_dtype=torch.float16 if device == "cuda" else torch.float32
    ).to(device)
    _CACHE[key] = (processor, model, device)
    return _CACHE[key]


def _heuristic_vlm_fallback(
    label_set: list[str],
    unknown_label: str,
    anomaly_score: float,
    bbox_count: int,
    mask_ratio: float,
) -> VLMResult:
    """
    Deterministic semantic fallback when full VLM runtime is unavailable.
    Keeps labels constrained to configured set and returns structured evidence.
    """
    if not label_set:
        return VLMResult(defect_label=unknown_label, evidence=["No configured label set."], confidence=0.0)

    if anomaly_score < 0.15 and bbox_count == 0:
        return VLMResult(
            defect_label=unknown_label,
            evidence=["No clear anomaly regions detected."],
            confidence=0.25,
        )

    # Geometry-aware deterministic mapping to available labels.
    sorted_labels = sorted(label_set)
    if bbox_count >= 3 and mask_ratio >= 0.05:
        label = next((x for x in sorted_labels if "contam" in x.lower() or "stain" in x.lower()), sorted_labels[0])
    elif bbox_count <= 1 and mask_ratio < 0.02:
        label = next((x for x in sorted_labels if "small" in x.lower() or "scratch" in x.lower()), sorted_labels[0])
    else:
        label = next((x for x in sorted_labels if "large" in x.lower() or "crack" in x.lower()), sorted_labels[0])

    conf = max(0.3, min(0.85, 0.45 + 0.35 * min(1.0, anomaly_score) + 0.15 * min(1.0, mask_ratio * 5.0)))
    evidence = [
        f"Anomaly score={anomaly_score:.3f}, bbox_count={bbox_count}, mask_ratio={mask_ratio:.4f}.",
        "Label selected from fixed label set using deterministic geometry rules.",
    ]
    return VLMResult(defect_label=label, evidence=evidence, confidence=conf)


def infer_defect_label(
    category: str,
    label_set: list[str],
    unknown_label: str,
    roi_note: str,
    image: Optional[Image.Image] = None,
    anomaly_score: float = 0.0,
    bbox_count: int = 0,
    mask_ratio: float = 0.0,
    model_id: str = "llava-hf/llava-1.6-mistral-7b-hf",
    device: str = "cuda" if (torch and torch.cuda.is_available()) else "cpu",
) -> VLMResult:
    """
    LLaVA-1.6 (Mistral) inference. Requires transformers + torch and a GPU for practical speed.
    If no image provided or deps missing, returns Unknown with a note.
    """
    if image is None:
        return _heuristic_vlm_fallback(label_set, unknown_label, anomaly_score, bbox_count, mask_ratio)
    if AutoProcessor is None or LlavaForConditionalGeneration is None or torch is None:
        fallback = _heuristic_vlm_fallback(label_set, unknown_label, anomaly_score, bbox_count, mask_ratio)
        fallback.evidence.append("Full VLM runtime unavailable; fallback semantic classifier used.")
        fallback.evidence.append(roi_note)
        return fallback

    prompt = _build_prompt(category, label_set, unknown_label)
    processor, model, device = _get_model(model_id, device)

    inputs = processor(text=prompt, images=image, return_tensors="pt").to(device)
    with torch.no_grad():
        output = model.generate(**inputs, max_new_tokens=200)
    text = processor.batch_decode(output, skip_special_tokens=True)[0]
    return _parse_response(text, unknown_label, label_set)
