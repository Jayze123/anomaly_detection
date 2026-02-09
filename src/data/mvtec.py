from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterator, Optional

from PIL import Image


@dataclass(frozen=True)
class Sample:
    image_path: str
    mask_path: Optional[str]
    category: str
    split: str
    label: str


def _list_pngs(root: str) -> list[str]:
    return [
        os.path.join(root, f)
        for f in sorted(os.listdir(root))
        if f.lower().endswith(".png")
    ]


def iter_mvtec_samples(root: str, category: str, split: str) -> Iterator[Sample]:
    """
    Yields samples from MVTec AD folder structure:
    root/category/{train,test}/...
    root/category/ground_truth/...
    """
    base = os.path.join(root, category, split)
    if not os.path.isdir(base):
        raise FileNotFoundError(f"Missing split folder: {base}")

    for label in sorted(os.listdir(base)):
        label_dir = os.path.join(base, label)
        if not os.path.isdir(label_dir):
            continue
        for img_path in _list_pngs(label_dir):
            mask_path = None
            if split == "test" and label != "good":
                gt_dir = os.path.join(root, category, "ground_truth", label)
                mask_name = os.path.basename(img_path).replace(".png", "_mask.png")
                candidate = os.path.join(gt_dir, mask_name)
                if os.path.isfile(candidate):
                    mask_path = candidate
            yield Sample(
                image_path=img_path,
                mask_path=mask_path,
                category=category,
                split=split,
                label=label,
            )


def load_image_rgb(path: str) -> Image.Image:
    return Image.open(path).convert("RGB")

