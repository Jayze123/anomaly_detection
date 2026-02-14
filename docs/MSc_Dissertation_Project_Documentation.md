# MSc Dissertation Project Documentation

## Title
Risk-Aware Vision Pipeline for Industrial Visual Inspection and Anomaly Detection

## 1. Project Summary
This project implements an end-to-end visual inspection system for anomaly detection with:
- image-level anomaly decision and continuous anomaly score,
- anomaly localization (heatmap, binary mask, bounding boxes),
- interpretable defect labeling with evidence (VLM or deterministic fallback),
- strict Risk Priority Matrix (RPM) lookup with no invented risk values,
- deterministic action recommendation from risk class,
- uncertainty estimation and human-review gating.

The implementation is split across:
- an operational web platform (`app/`, `ui/`) for factory/admin workflows, and
- a research pipeline (`src/`) for dataset-driven anomaly + risk experiments.

## 2. Research Objectives and Mapping to Implementation
### Objective O1: Detect anomalies (decision + score)
- Implemented in `src/models/mean_diff.py` and used by `src/pipeline.py` / `src/api.py`.
- Output fields: `image_decision`, `anomaly_score`.

### Objective O2: Localize anomalies
- Heatmap normalization: `src/postproc/heatmap.py`
- Binary mask generation: `src/postproc/mask.py`
- Bounding boxes: `src/postproc/bboxes.py`
- Output fields: `anomaly_heatmap_path`, `anomaly_mask_path`, `bboxes`, `localization`.

### Objective O3: Interpretable defect label + short evidence
- Implemented in `src/vlm/semantics.py`.
- Uses fixed label sets from `configs/base.yaml`.
- Produces `defect_label`, `evidence`, and `confidence`.
- Includes deterministic fallback when full VLM runtime is unavailable.

### Objective O4: Risk score/class from predefined RPM only
- Strict lookup in `src/risk/rpm.py` (`lookup_risk_strict`).
- If no exact RPM row exists, system returns `risk_class = REVIEW_REQUIRED` and `risk_score = null`.
- Prevents hallucinated or inferred risk values.

### Objective O5: Action recommendation from fixed policy
- Implemented in `src/risk/policy.py`.
- Maps risk classes to fixed actions from `configs/base.yaml`.

### Objective O6: Uncertainty and human-review recommendation
- Confidence fusion: `src/uncertainty/confidence.py`
- Review rules: `src/uncertainty/rules.py`
- Output fields: `confidence`, `human_review_required`.

## 3. System Architecture
## 3.1 Operational Application Layer
- Backend: FastAPI (`app/main.py`, `app/api/*.py`)
- UI: NiceGUI (`ui/*.py`)
- Database: PostgreSQL + SQLAlchemy + Alembic (`app/db/*`)
- Media storage: local filesystem (`/data` or configured storage root)
- Auth/RBAC: JWT and role-restricted routes (`ADMIN`, `USER`)

## 3.2 Research/Inference Layer
- Batch and API-style experimentation: `src/pipeline.py`, `src/api.py`
- Data source: MVTec-AD style structure under `data/`
- Artifacts output: `artifacts/heatmaps`, `artifacts/masks`, and JSON results.

## 4. Methodology
## 4.1 Anomaly Scoring
The baseline model computes a deviation score between input image and learned normal-image statistics.  
Decision rule:
- `anomalous` if `anomaly_score >= image_threshold`
- `normal` otherwise  
Threshold is configured in `configs/base.yaml` (`postproc.image_threshold`).

## 4.2 Localization
1. Produce anomaly heatmap.
2. Normalize heatmap (e.g., min-max).
3. Threshold (percentile or fixed value).
4. Extract connected components and convert to bounding boxes.

## 4.3 Defect Semantics (VLM + constrained labels)
The model receives:
- category,
- fixed label set,
- ROI/anomaly context.

Output is constrained to configured labels or `Unknown`. This supports explainability and consistency with quality taxonomies.

## 4.4 Risk Determination (RPM)
Risk is computed only from predefined tuples:
- Severity (S), Occurrence (O), Detection (D)
- Lookup `(S,O,D)` in RPM table
- Return `(risk_score, risk_class)` if exact match
- Otherwise return `REVIEW_REQUIRED`

This is deterministic and auditable.

## 4.5 Action Recommendation
Action is selected by fixed mapping:
- Low -> Continue and monitor
- Medium -> Rework and re-inspect
- High -> Quarantine lot and notify supervisor
- Critical -> Stop line and trigger CAPA escalation
- REVIEW_REQUIRED -> Hold for human review

## 4.6 Uncertainty Handling
Final confidence is fused from anomaly confidence and semantic confidence:
- `min` or `mean` strategy (configurable)
- Human review is required if:
  - confidence below threshold,
  - semantic label is unknown,
  - anomaly score is near decision boundary.

## 5. Data and Experiment Setup
## 5.1 Dataset Format
The project currently uses MVTec-style folders:
- `train/good`
- `test/<defect_type>`
- `ground_truth/<defect_type>`

Current category examples include `bottle`, with extensible support for `cable`, `wood`, `tile`, `leather`.

## 5.2 Configuration-Driven Reproducibility
All experiment behavior is set in `configs/base.yaml`, including:
- thresholds,
- category label sets,
- RPM table and policy,
- uncertainty rules.

## 6. Output Specification (Per Image)
Each processed image yields:
- `image_id`
- `image_decision`
- `anomaly_score`
- `anomaly_heatmap_path`
- `anomaly_mask_path`
- `bboxes`
- `defect_label`
- `evidence`
- `risk_score`
- `risk_class`
- `action`
- `confidence`
- `human_review_required`
- `rpm_inputs`

These outputs align with dissertation requirements for traceability, interpretability, and risk governance.

## 7. Validation Plan for Dissertation
Recommended evaluation protocol:
1. Split dataset by category and defect type.
2. Report anomaly detection metrics:
   - AUROC (image-level),
   - precision/recall/F1 at selected threshold.
3. Report localization metrics:
   - IoU/Dice for masks,
   - bbox IoU where applicable.
4. Report semantic classification metrics:
   - accuracy/F1 over fixed label set.
5. Report risk/action consistency:
   - % of outputs with valid strict RPM resolution,
   - % flagged for review.
6. Ablation:
   - confidence fusion method (`min` vs `mean`),
   - threshold sensitivity,
   - ambiguity margin sensitivity.

## 8. Threats to Validity
- Baseline anomaly model is lightweight and may underperform deep feature methods.
- VLM fallback heuristic is deterministic but less expressive than full multimodal LLM inference.
- Domain shift (factory lighting/camera changes) can affect score calibration.
- RPM quality depends on correctness of curated S/O/D profiles.

## 9. Ethical and Safety Considerations
- Human-in-the-loop is enforced for low-confidence or ambiguous outputs.
- Risk values are never hallucinated; only predefined matrix entries are accepted.
- Audit-friendly outputs preserve rationale (`evidence`, `rpm_inputs`).

## 10. Reproducibility Commands
## 10.1 Operational App
```bash
cp .env.example .env
python -m venv .venv
source .venv/bin/activate
pip install -e .
alembic -c app/db/migrations/alembic.ini upgrade head
python -m app.main
```

## 10.2 Research Pipeline
```bash
source .venv/bin/activate
python -m src.cli run --config configs/base.yaml
```

## 11. Suggested Dissertation Chapter Mapping
- Chapter 1: Introduction and problem motivation
- Chapter 2: Related work (AD, industrial CV, VLM explainability, risk-based QC)
- Chapter 3: System architecture and methods (Sections 2-6 of this document)
- Chapter 4: Experimental design and results (Section 7)
- Chapter 5: Discussion, limitations, and future work
- Chapter 6: Conclusion

## 12. Future Work
- Replace baseline model with patch-based/self-supervised industrial AD model.
- Add calibrated uncertainty (e.g., temperature scaling, conformal prediction).
- Integrate production-grade VLM inference service with latency budgeting.
- Add active learning loop for uncertain or high-risk samples.
