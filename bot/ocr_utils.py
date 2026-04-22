"""
bot/ocr_utils.py — ROI-Based OCR Reward Detection Pipeline
============================================================
Extracts EXP, Gold, EXP-Battlepass, Gems, and Perks from mission result
screens using config-driven Region of Interest (ROI) cropping.

Reward UI Layout (left -> right, horizontal row):
  [ EXP ] [ GOLD ] [ EXP_BP ] [ GEMS ] [ PERK ] [ PERK ] [ PERK ] [ PERK ]

Root-cause fix (v3):
  EasyOCR's default width_ths=0.5 was merging adjacent reward boxes whose
  horizontal gap (after 2.5x upscale) was smaller than 50% of text height.
  Fix: width_ths=0.1 + scale=2.0 keeps gap >> merge threshold.
  Bonus: split each OCR result on whitespace BEFORE digit extraction so
  a partially-merged string like "12600 65340" can't become one big number.
"""

import cv2
import numpy as np
import logging
import os
import re
from collections import deque
from statistics import median
from typing import Tuple, Optional, List

import easyocr
from bot.config import config

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
_DEFAULT_REWARD_BOX    = [847, 807, 912, 119]   # Full horizontal reward bar
_DEFAULT_BUFFER_SIZE   = 5
_DEFAULT_SANITY_MAX    = 9_999_999
_DEFAULT_DEBUG_DIR     = "debug_ocr"



# ── Pure utility functions ────────────────────────────────────────────────────

def crop_region(frame: np.ndarray, region: List[int]) -> np.ndarray:
    """
    Crop a Region of Interest from a full-resolution frame.

    Args:
        frame  : BGR numpy array (full screen, e.g. 2560x1440)
        region : [x, y, w, h] in screen pixels

    Returns:
        Cropped BGR image.
    """
    x, y, w, h = region
    fh, fw = frame.shape[:2]

    x1 = max(0, int(x))
    y1 = max(0, int(y))
    x2 = min(fw, int(x + w))
    y2 = min(fh, int(y + h))

    if x2 <= x1 or y2 <= y1:
        logger.warning(f"[OCR] crop_region: region {region} out-of-bounds for {fw}x{fh}")
        return np.zeros((10, 10, 3), dtype=np.uint8)

    return frame[y1:y2, x1:x2]


def preprocess_for_ocr(img: np.ndarray, scale: float = 2.0) -> np.ndarray:
    """
    Prepare a cropped image for OCR.

    Scaling note:
        scale=2.0 is deliberate.  At 2.5 the inter-box gap (~10px source)
        becomes ~25px processed, which is less than EasyOCR's default merge
        threshold (0.5 * text_height ~37px).  At 2.0 the gap ratio is
        better, and combined with width_ths=0.1 in read_numbers() the
        adjacent reward boxes are reliably kept separate.

    Pipeline:
        1. Grayscale
        2. Upscale (2.0x default)
        3. Light sharpen
        4. Gaussian denoise -> adaptive threshold
    """
    if img is None or img.size == 0:
        return np.zeros((10, 10), dtype=np.uint8)

    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        gray = img.copy()

    if scale != 1.0:
        gray = cv2.resize(gray, None, fx=scale, fy=scale,
                          interpolation=cv2.INTER_CUBIC)

    # No manual thresholding — return raw grayscale.
    #
    # Why: Every threshold method introduced specific failure modes:
    #   - Adaptive (blockSize=15)  → hollow outlines,  failed on solid UI
    #   - Otsu                     → bloated/merged,   picked up drop-shadows
    #   - Static 180 (BINARY_INV) → horizontal lines,  captured white box borders
    #
    # EasyOCR has its own well-tuned internal preprocessing pipeline that is
    # far more robust on raw grayscale than any hand-crafted threshold.
    # "Less pre-processing" wins here.
    return gray


def read_numbers(img: np.ndarray, reader: easyocr.Reader,
                 min_confidence: float = 0.25) -> List[dict]:
    """
    Run EasyOCR on a preprocessed image and extract all number tokens,
    sorted left-to-right by their horizontal center in the image.

    Critical parameters:
        width_ths=0.1  — EasyOCR merges text boxes whose horizontal gap is
                         smaller than (width_ths * text_height).  Default 0.5
                         was causing reward boxes to merge (gap ~25px < 0.5*75).
                         0.1 limits merging to gaps < 10% of text height.
        paragraph=False — no paragraph-level grouping.

    Whitespace handling:
        We split each OCR result on whitespace BEFORE cleaning digits, so if
        EasyOCR still returns "12600 65340" as one string the two numbers
        remain separate (instead of becoming "1260065340").
    """
    if img is None or img.size == 0:
        return []

    try:
        results = reader.readtext(
            img,
            detail=1,
            paragraph=False,
            min_size=5,
            width_ths=0.1,              # prevents adjacent reward boxes merging
            ycenter_ths=0.5,
            allowlist='0123456789.,',   # digits + separators only; no letters hallucinated
        )
    except Exception as e:
        logger.warning(f"[OCR] EasyOCR readtext error: {e}")
        return []

    extracted = []
    for (bbox, text, prob) in results:
        if prob < min_confidence:
            continue

        # Bounding box: [[x1,y1],[x2,y1],[x2,y2],[x1,y2]]
        x_center = (bbox[0][0] + bbox[2][0]) / 2.0
        y_center = (bbox[0][1] + bbox[2][1]) / 2.0

        # Split on whitespace FIRST to avoid merging adjacent numbers
        tokens = text.split()

        for token in tokens:
            clean = token.upper()
            clean = clean.replace(",", "").replace(".", "")
            clean = clean.replace("!", "1").replace("I", "1").replace("O", "0")
            clean = clean.replace("L", "1").replace("B", "8").replace("S", "5")
            clean = re.sub(r"[^0-9]", "", clean)

            if not clean:
                continue

            val = int(clean)
            if val > 0:
                extracted.append({
                    "val":        val,
                    "x_center":   x_center,
                    "y_center":   y_center,
                    "confidence": float(prob),
                    "raw":        text,
                })

    # Sort LEFT -> RIGHT (reward boxes arranged horizontally)
    extracted.sort(key=lambda x: x["x_center"])
    return extracted


def _sanity_check(val: int, sanity_max: int) -> bool:
    if val < 0:
        return False
    if val > sanity_max:
        logger.debug(f"[OCR] Sanity FAIL: {val} > max {sanity_max}")
        return False
    return True


def _save_debug_image(img: np.ndarray, name: str, debug_dir: str) -> None:
    try:
        os.makedirs(debug_dir, exist_ok=True)
        path = os.path.join(debug_dir, f"debug_{name}.png")
        cv2.imwrite(path, img)
        logger.debug(f"[OCR] Debug image saved: {path}")
    except Exception as e:
        logger.warning(f"[OCR] Could not save debug image '{name}': {e}")


# ── Main OCR class ────────────────────────────────────────────────────────────

class RewardOCR:
    """
    ROI-based reward extractor with multi-frame median stabilisation.

    Reward layout (left -> right):
        EXP | GOLD | EXP_BP | GEMS | PERK x4

    Usage:
        ocr = RewardOCR()
        exp, gold, exp_bp, gems, perks = ocr.extract_rewards(frame)
    """

    def __init__(self):
        logger.info("[OCR] Initializing EasyOCR (GPU preferred)...")
        try:
            self.reader = easyocr.Reader(["en"], gpu=True)
        except Exception:
            logger.warning("[OCR] GPU init failed, falling back to CPU.")
            self.reader = easyocr.Reader(["en"], gpu=False)
        logger.info("[OCR] EasyOCR ready.")

        buf_size = config.get("reward_regions", "ocr_buffer_size", _DEFAULT_BUFFER_SIZE)
        self._ocr_buffer: deque = deque(maxlen=buf_size)
        logger.info(
            f"[OCR] Pipeline ready | layout=EXP|GOLD|EXP_BP|GEMS|PERKS "
            f"| buffer={buf_size} | width_ths=0.1 | scale=2.0"
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def extract_rewards(self, frame: np.ndarray) -> Tuple[int, int, int, int, int]:
        """
        Extract EXP and Gold from a full-resolution frame.
        EXP_BP, Gems, Perks are returned as 0 for compatibility.
        
        Returns:
            (exp, gold, 0, 0, 0)
        """
        if frame is None or frame.size == 0:
            logger.warning("[OCR] Empty frame. Returning zeros.")
            return 0, 0, 0, 0, 0

        regions   = config.get("reward_regions", {}) or {}
        debug     = regions.get("debug_mode", False)
        debug_dir = regions.get("debug_dir", _DEFAULT_DEBUG_DIR)
        sanity    = regions.get("sanity_max_value", _DEFAULT_SANITY_MAX)

        exp, gold = self._extract_from_box(frame, regions, debug, debug_dir)
        exp_bp = gems = perks = 0

        logger.info(f"[OCR] Raw read -> Exp={exp}, Gold={gold}")

        exp  = exp  if _sanity_check(exp,  sanity) else 0
        gold = gold if _sanity_check(gold, sanity) else 0

        if not any([exp, gold]):
            logger.info("[OCR] All zeros — 0 titan kills or OCR miss.")

        self._ocr_buffer.append((exp, gold, exp_bp, gems, perks))
        stable = self._median_result()
        logger.info(
            f"[OCR] Stabilised (buf={len(self._ocr_buffer)}) -> "
            f"Exp={stable[0]}, Gold={stable[1]}, ExpBP={stable[2]}, "
            f"Gems={stable[3]}, Perks={stable[4]}"
        )
        return stable

    def reset_buffer(self) -> None:
        """Clear the rolling OCR buffer (call at start of each mission read)."""
        self._ocr_buffer.clear()
        logger.debug("[OCR] Buffer cleared.")

    # ── Private helpers ───────────────────────────────────────────────────────

    def _extract_from_box(self, frame, regions, debug, debug_dir) -> Tuple[int, int]:
        """
        Full-bar scan strategy:
          1. Crop reward_box, extract number strip (65-90%).
          2. OCR → list of (val, x_center_proc).
          3. Return left-most two numbers as EXP and GOLD.
        """
        box  = regions.get("reward_box", _DEFAULT_REWARD_BOX)
        crop = crop_region(frame, box)

        if debug:
            _save_debug_image(crop, "reward_box_raw", debug_dir)

        # ── Number strip ─────────────────────────────────────────────────────
        h          = crop.shape[0]
        num_strip  = crop[int(h * 0.65) : int(h * 0.90), :]    # 65-90%: numbers
        proc       = preprocess_for_ocr(num_strip, scale=2.5)

        if debug:
            _save_debug_image(num_strip, "reward_box_numstrip_raw",  debug_dir)
            _save_debug_image(proc,      "reward_box_numstrip_proc", debug_dir)

        numbers = read_numbers(proc, self.reader)
        for n in numbers:
            n["x_src"] = n["x_center"] / 2.5

        logger.debug(
            f"[OCR] reward_box: {len(numbers)} numbers detected "
            f"{[(n['val'], round(n['x_src'])) for n in numbers]}"
        )

        # ── Assignment strategy ──────────────────────────────────────────────
        # Only EXP and GOLD are tracked (always the first two boxes, index 0 and 1).
        exp = gold = 0
        nums = sorted(numbers, key=lambda n: n["x_src"])
        if len(nums) >= 1: exp  = nums[0]["val"]
        if len(nums) >= 2: gold = nums[1]["val"]

        return exp, gold



    def _median_result(self) -> Tuple[int, int, int, int, int]:
        """Return element-wise median of the 5-tuple OCR buffer."""
        if not self._ocr_buffer:
            return 0, 0, 0, 0, 0
        return (
            int(median(x[0] for x in self._ocr_buffer)),
            int(median(x[1] for x in self._ocr_buffer)),
            int(median(x[2] for x in self._ocr_buffer)),
            int(median(x[3] for x in self._ocr_buffer)),
            int(median(x[4] for x in self._ocr_buffer)),
        )


# ── Singleton accessor ────────────────────────────────────────────────────────

_reward_ocr: Optional[RewardOCR] = None


def get_reward_ocr() -> RewardOCR:
    """Lazy-initialise and return the global RewardOCR singleton."""
    global _reward_ocr
    if _reward_ocr is None:
        _reward_ocr = RewardOCR()
    return _reward_ocr
