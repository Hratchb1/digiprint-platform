"""
border_processor.py
-------------------
Applies a clean film-scan style border to JPG and TIFF images.

Border style:
  - Thin uniform black border (~1.2-1.5% of image dimension)
  - Smooth organic edge with soft feathered transition
  - Very subtle curvature — barely visible wave
  - No halation
  - Each image seeded from filename for reproducible but unique variation

Input:  JPG or TIFF (any size)
Output: Same format as input, maximum quality
"""

import hashlib
import logging
import numpy as np
from pathlib import Path
from PIL import Image, ImageFilter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def process_folder(source_dir: str, output_dir: str) -> dict:
    source_path = Path(source_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    processed = []
    failed = []

    image_files = [
        f for f in source_path.iterdir()
        if f.is_file() and f.suffix.lower() in (".jpg", ".jpeg", ".tif", ".tiff")
    ]

    if not image_files:
        logger.warning(f"No image files found in {source_dir}")
        return {"processed": [], "failed": []}

    logger.info(f"Border processor: found {len(image_files)} images in {source_dir}")

    for img_path in image_files:
        try:
            out_path = output_path / img_path.name
            apply_border(str(img_path), str(out_path))
            processed.append(img_path.name)
            logger.info(f"  ✓ Bordered: {img_path.name}")
        except Exception as e:
            logger.error(f"  ✗ Failed: {img_path.name} — {e}")
            failed.append((img_path.name, str(e)))

    logger.info(f"Border processor complete: {len(processed)} ok, {len(failed)} failed")
    return {"processed": processed, "failed": failed}


# ---------------------------------------------------------------------------
# Core border function
# ---------------------------------------------------------------------------

def apply_border(input_path: str, output_path: str) -> None:
    input_path = Path(input_path)
    output_path = Path(output_path)

    seed = int(hashlib.md5(input_path.name.encode()).hexdigest(), 16) % (2**32)
    rng = np.random.default_rng(seed)

    with Image.open(input_path) as img:
        original_mode = img.mode
        original_format = input_path.suffix.lower()

        img_rgb = img.convert("RGB")
        width, height = img_rgb.size

        # --- Border widths --- thinner than before, less image crop
        base_lr = 0.013
        base_t  = 0.011
        base_b  = 0.015

        var = rng.uniform(-0.001, 0.001)

        border_l = max(int((base_lr + var) * width), 3)
        border_r = max(int((base_lr + var) * width), 3)
        border_t = max(int((base_t  + var) * height), 3)
        border_b = max(int((base_b  + var) * height), 3)

        inner_left   = border_l
        inner_right  = width - border_r
        inner_top    = border_t
        inner_bottom = height - border_b

        # --- Build smooth organic mask ---
        mask = _build_smooth_mask(width, height, inner_left, inner_right,
                                   inner_top, inner_bottom, border_l, border_r,
                                   border_t, border_b, rng)

        # --- Pure black border background ---
        border_bg = Image.new("RGB", (width, height), (0, 0, 0))

        # --- Composite ---
        result = Image.composite(img_rgb, border_bg, mask)

        if original_mode == "L":
            result = result.convert("L")

        _save_image(result, output_path, original_format)


# ---------------------------------------------------------------------------
# Smooth organic mask
# ---------------------------------------------------------------------------

def _build_smooth_mask(width, height, inner_left, inner_right,
                        inner_top, inner_bottom, border_l, border_r,
                        border_t, border_b, rng) -> Image.Image:
    mask = np.zeros((height, width), dtype=np.uint8)
    mask[inner_top:inner_bottom, inner_left:inner_right] = 255

    ctrl = 8

    # LEFT
    disp = _make_smooth_displacement(inner_bottom - inner_top, ctrl, border_l, 0.05, 0.12, rng)
    for i, d in enumerate(disp):
        y = inner_top + i
        x = max(0, min(width - 1, inner_left + d))
        mask[y, :x] = 0

    # RIGHT
    disp = _make_smooth_displacement(inner_bottom - inner_top, ctrl, border_r, 0.05, 0.12, rng)
    for i, d in enumerate(disp):
        y = inner_top + i
        x = max(0, min(width - 1, inner_right + d))
        mask[y, x:] = 0

    # TOP
    disp = _make_smooth_displacement(inner_right - inner_left, ctrl, border_t, 0.05, 0.12, rng)
    for i, d in enumerate(disp):
        x = inner_left + i
        y = max(0, min(height - 1, inner_top + d))
        mask[:y, x] = 0

    # BOTTOM
    disp = _make_smooth_displacement(inner_right - inner_left, ctrl, border_b, 0.05, 0.12, rng)
    for i, d in enumerate(disp):
        x = inner_left + i
        y = max(0, min(height - 1, inner_bottom + d))
        mask[y:, x] = 0

    mask_img = Image.fromarray(mask, mode="L")
    mask_img = mask_img.filter(ImageFilter.GaussianBlur(radius=1.2))
    return mask_img


def _make_smooth_displacement(length: int, ctrl: int, border_size: int,
                               min_scale: float, max_scale: float, rng) -> np.ndarray:
    ctrl_pts = rng.normal(0, 1, ctrl)
    ctrl_pts = np.convolve(ctrl_pts, np.ones(3) / 3, mode='same')
    x_ctrl = np.linspace(0, length - 1, ctrl)
    x_full = np.arange(length)
    disp = np.interp(x_full, x_ctrl, ctrl_pts)

    window = max(length // 6, 10)
    kernel = np.ones(window) / window
    disp = np.convolve(disp, kernel, mode='same')

    std = np.std(disp)
    if std > 0:
        disp = disp / std

    # Fixed: min_scale always less than max_scale
    scale = border_size * rng.uniform(min_scale, max_scale)
    return (disp * scale).astype(int)


# ---------------------------------------------------------------------------
# Save helper
# ---------------------------------------------------------------------------

def _save_image(result: Image.Image, output_path: Path, original_format: str) -> None:
    if original_format in (".tif", ".tiff"):
        result.save(str(output_path), format="TIFF", compression="tiff_lzw")
    elif original_format in (".jpg", ".jpeg"):
        if result.mode == "RGBA":
            result = result.convert("RGB")
        result.save(str(output_path), format="JPEG", quality=97,
                    subsampling=0, optimize=False)
    else:
        result.save(str(output_path))