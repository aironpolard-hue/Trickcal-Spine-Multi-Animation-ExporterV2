from __future__ import annotations

import re

import numpy as np
from PIL import Image

_PMA_PATTERN = re.compile(r"pma\s*:\s*true", re.IGNORECASE)


def atlas_is_premultiplied(text: str) -> bool:
    return bool(_PMA_PATTERN.search(text))


def prepare_atlas_page(image: Image.Image, premultiplied: bool) -> Image.Image:
    """Normalize atlas pixels for GL_ONE / GL_ONE_MINUS_SRC_ALPHA blending.

    PMA atlases can contain RGB values above alpha (common at packed edges),
    which shows up as bright halos or spikes. Straight-alpha pages are
    premultiplied. Fully transparent pixels are cleared so linear filtering
    cannot pull stale colors into visible sprite edges.
    """
    source = image.convert("RGBA")
    arr = np.asarray(source, dtype=np.uint8).copy()
    alpha = arr[..., 3:4].astype(np.uint16)
    rgb = arr[..., :3].astype(np.uint16)
    if premultiplied:
        rgb = np.minimum(rgb, alpha)
    else:
        rgb = (rgb * alpha + 127) // 255
    rgb = np.where(alpha > 0, rgb, 0)
    arr[..., :3] = rgb.astype(np.uint8)
    return Image.fromarray(arr, "RGBA")
