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


def _parse_response(text: str, unknown_label: str) -> VLMResult:
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


def infer_defect_label(
    category: str,
    label_set: list[str],
    unknown_label: str,
    roi_note: str,
    image: Optional[Image.Image] = None,
    model_id: str = "llava-hf/llava-1.6-mistral-7b-hf",
    device: str = "cuda" if (torch and torch.cuda.is_available()) else "cpu",
) -> VLMResult:
    """
    LLaVA-1.6 (Mistral) inference. Requires transformers + torch and a GPU for practical speed.
    If no image provided or deps missing, returns Unknown with a note.
    """
    if image is None:
        return VLMResult(
            defect_label=unknown_label,
            evidence=[f"No image provided. ROI note: {roi_note}"],
            confidence=0.0,
        )
    if AutoProcessor is None or LlavaForConditionalGeneration is None or torch is None:
        return VLMResult(
            defect_label=unknown_label,
            evidence=["VLM dependencies not installed."],
            confidence=0.0,
        )

    prompt = _build_prompt(category, label_set, unknown_label)
    processor, model, device = _get_model(model_id, device)

    inputs = processor(text=prompt, images=image, return_tensors="pt").to(device)
    with torch.no_grad():
        output = model.generate(**inputs, max_new_tokens=200)
    text = processor.batch_decode(output, skip_special_tokens=True)[0]
    return _parse_response(text, unknown_label)
