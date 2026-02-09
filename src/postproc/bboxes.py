from __future__ import annotations

import numpy as np

try:
    from skimage.measure import label, regionprops
except Exception as exc:  # pragma: no cover
    label = None
    regionprops = None
    _import_error = exc
else:
    _import_error = None


def mask_to_bboxes(mask: np.ndarray, min_area: int = 20) -> list[list[int]]:
    if label is None or regionprops is None:
        raise ImportError(
            "scikit-image is required for connected components. "
            f"Import error: {_import_error}"
        )
    labeled = label(mask > 0)
    bboxes: list[list[int]] = []
    for region in regionprops(labeled):
        if region.area < min_area:
            continue
        minr, minc, maxr, maxc = region.bbox
        bboxes.append([int(minc), int(minr), int(maxc), int(maxr)])
    return bboxes

