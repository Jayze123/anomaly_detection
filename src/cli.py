from __future__ import annotations

import argparse
import os

from src.config import load_yaml
from src.pipeline import run_pipeline
from src.report.writer import write_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Anomaly inspection pipeline (MVP baseline).")
    parser.add_argument("--config", required=True, help="Path to config YAML.")
    args = parser.parse_args()

    cfg = load_yaml(args.config)
    outputs_dir = cfg["paths"]["outputs"]
    os.makedirs(outputs_dir, exist_ok=True)
    out_path = os.path.join(outputs_dir, cfg["paths"]["results_json"])

    payload = run_pipeline(cfg)
    write_json(out_path, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
