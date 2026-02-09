from __future__ import annotations

import os
from dataclasses import asdict

import numpy as np
from PIL import Image

from src.data.mvtec import iter_mvtec_samples, load_image_rgb
from src.models.mean_diff import MeanDiffModel
from src.postproc.heatmap import normalize_heatmap
from src.postproc.mask import threshold_heatmap
from src.postproc.bboxes import mask_to_bboxes
from src.vlm.semantics import infer_defect_label
from src.risk.rpm import lookup_risk
from src.risk.policy import action_from_risk
from src.uncertainty.confidence import combine_confidence
from src.uncertainty.rules import requires_human_review


def _save_uint8(path: str, arr: np.ndarray) -> None:
    img = Image.fromarray(arr.astype(np.uint8))
    img.save(path)


def run_pipeline(cfg: dict) -> dict:
    data_root = cfg["data"]["root"]
    category = cfg["data"]["category"]
    artifacts_dir = cfg["paths"]["artifacts"]
    os.makedirs(artifacts_dir, exist_ok=True)
    heatmap_dir = os.path.join(artifacts_dir, "heatmaps")
    mask_dir = os.path.join(artifacts_dir, "masks")
    os.makedirs(heatmap_dir, exist_ok=True)
    os.makedirs(mask_dir, exist_ok=True)

    train_images = [
        load_image_rgb(s.image_path)
        for s in iter_mvtec_samples(data_root, category, "train")
        if s.label == "good"
    ]

    model = MeanDiffModel()
    model.fit(train_images)

    label_sets = cfg["labels"]["labels"]
    unknown_label = cfg["labels"]["unknown_label"]
    rpm_table = cfg["risk"]["rpm"]
    risk_to_action = cfg["risk"]["risk_to_action"]

    results = []
    for sample in iter_mvtec_samples(data_root, category, "test"):
        image = load_image_rgb(sample.image_path)
        score, heatmap = model.infer(image)
        heatmap_n = normalize_heatmap(heatmap, method=cfg["postproc"]["heatmap_normalize"])
        mask = threshold_heatmap(
            heatmap_n,
            method=cfg["postproc"]["threshold_method"],
            value=cfg["postproc"]["threshold_value"],
            percentile=cfg["postproc"]["threshold_percentile"],
        )
        bboxes = mask_to_bboxes(mask, min_area=cfg["postproc"]["min_area"])

        base = os.path.splitext(os.path.basename(sample.image_path))[0]
        heatmap_path = os.path.join(heatmap_dir, f"{base}_hm.png")
        mask_path = os.path.join(mask_dir, f"{base}_mask.png")
        _save_uint8(heatmap_path, (heatmap_n * 255.0).clip(0, 255))
        _save_uint8(mask_path, (mask * 255))

        image_decision = "anomalous" if score >= cfg["postproc"]["image_threshold"] else "normal"

        vlm_result = infer_defect_label(
            category=category,
            label_set=label_sets.get(category, []),
            unknown_label=unknown_label,
            roi_note="NEEDED FROM USER: ROI selection not implemented.",
            image=image,
        )

        risk_score, risk_class = lookup_risk(
            rpm_table,
            severity=cfg["risk"].get("severity"),
            occurrence=cfg["risk"].get("occurrence"),
            detection=cfg["risk"].get("detection"),
        )
        action = action_from_risk(risk_class, risk_to_action)

        anomaly_conf = float(min(1.0, score / cfg["postproc"]["image_threshold"])) if cfg["postproc"]["image_threshold"] > 0 else 0.0
        confidence = combine_confidence(anomaly_conf, vlm_result.confidence, method=cfg["uncertainty"]["combine_method"])
        human_review = requires_human_review(
            confidence=confidence,
            label=vlm_result.defect_label,
            unknown_label=unknown_label,
            threshold=cfg["uncertainty"]["review_threshold"],
        )

        results.append(
            {
                "image_id": base,
                "category": category,
                "image_decision": image_decision,
                "anomaly_score": float(score),
                "anomaly_heatmap_path": heatmap_path,
                "anomaly_mask_path": mask_path,
                "bboxes": bboxes,
                "defect_label": vlm_result.defect_label,
                "evidence": vlm_result.evidence,
                "risk_score": risk_score,
                "risk_class": risk_class,
                "action": action,
                "confidence": confidence,
                "human_review_required": human_review,
            }
        )

    return {"results": results}
