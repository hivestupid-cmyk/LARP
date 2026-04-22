"""
bot/detector.py — YOLO11n (Nano) inference with explicit coordinate un-mapping.

Model: YOLO11n — superior feature extraction vs YOLOv8 at lower latency.

Model priority:
    1. best.engine  (TensorRT FP16 — fastest, 10–20 ms on RTX)
    2. best.pt      (PyTorch CUDA FP16 — good fallback)
    3. best.pt      (CPU — last resort, slow)

Post-load optimisations:
    • model.fuse()  — fuses Conv2d + BatchNorm layers (~5% speed boost)
    • model.half()  — FP16 weights on CUDA (uses Tensor Cores)

Inference flags:
    • stream=True   — generator output; avoids building a large result list in RAM

Coordinate unmapping formula
-----------------------------
Given a 640×640 letterboxed frame with known scale, pad_x, pad_y:

    X_screen = (X_yolo - pad_x) / scale
    Y_screen = (Y_yolo - pad_y) / scale
    W_screen = W_yolo / scale
    H_screen = H_yolo / scale

For 2560×1440 → 640×640:
    scale  = 640 / 2560 = 0.25
    pad_x  = 0   (width already fills 640 after scale)
    pad_y  = 140 (top + bottom black bars, 140 px each)

All values are clamped to valid screen bounds.
"""

import os
import logging
from dataclasses import dataclass
from typing import List

import cv2
import numpy as np
import torch
import easyocr  # PENDING: pip install easyocr
from ultralytics import YOLO

from bot.config import config

logger = logging.getLogger(__name__)


@dataclass
class Detection:
    """A single detection in SCREEN-space coordinates."""
    label: str
    confidence: float
    # Centre point in screen pixels
    x_screen: int
    y_screen: int
    # Bounding box dimensions in screen pixels
    w_screen: int
    h_screen: int


class Detector:
    """
    Loads the best available YOLO11n model and runs inference on
    already-letterboxed 640×640 BGR frames, returning detections
    mapped back to the original screen resolution.
    """

    def __init__(self):
        # Resolve absolute path to models_dir so it works regardless of CWD
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        models_dir_rel: str = config.get("assets", "models_dir", "assets/models")
        models_dir = os.path.join(root_dir, models_dir_rel)

        self.conf_threshold: float = config.get("detection", "confidence_threshold", 0.45)
        self.img_size: int = config.get("detection", "image_size", 640)
        self.screen_w: int = config.get("screen", "width", 2560)
        self.screen_h: int = config.get("screen", "height", 1440)

        # ── Auto-Latest Logic ──────────────────────────────────────────
        self.trt_path  = ""
        self.onnx_path = ""
        self.pt_path   = ""

        custom_model = config.get("bot", "model_path", "").strip()
        if custom_model and os.path.exists(custom_model):
            logger.info("Auto-Latest: OVERRIDDEN. Using user-selected model -> %s", custom_model)
            
            # Sibling Discovery: Look for other formats in the SAME folder as the custom model
            custom_dir = os.path.dirname(custom_model)
            base_name  = os.path.splitext(os.path.basename(custom_model))[0] # usually 'best'
            
            self.trt_path  = os.path.join(custom_dir, f"{base_name}.engine")
            self.onnx_path = os.path.join(custom_dir, f"{base_name}.onnx")
            self.pt_path   = os.path.join(custom_dir, f"{base_name}.pt")
            
            # Ensure the explicitly selected path is forced for its type 
            # (in case it's named something else)
            lower_custom = custom_model.lower()
            if lower_custom.endswith(".engine"):
                self.trt_path = custom_model
            elif lower_custom.endswith(".onnx"):
                self.onnx_path = custom_model
            else:
                self.pt_path = custom_model
        else:
            latest_folder = self._get_latest_train_folder(models_dir)
            effective_models_dir = latest_folder if latest_folder else models_dir
            
            if latest_folder:
                logger.info(f"Auto-Latest: Using most recent training folder -> {os.path.basename(latest_folder)}")
            else:
                logger.info("Auto-Latest: No timestamped train folders found, using default assets/models root.")

            self.trt_path  = os.path.join(effective_models_dir, "best.engine")
            self.onnx_path = os.path.join(effective_models_dir, "best.onnx") 
            self.pt_path   = os.path.join(effective_models_dir, "best.pt")

        self.cuda: bool = torch.cuda.is_available()
        self.device = 0 if self.cuda else "cpu"
        self.model: YOLO | None = None
        self._use_half: bool = False

        self._load_model()
        
        # ── V5.2: Resource Optimization (Class Filtering) ────────────────
        self.ignored_labels = {"tree", "ground", "player", "annie"}
        self.active_ids = []
        if self.model:
            for idx, name in self.model.names.items():
                if name.lower() not in self.ignored_labels:
                    self.active_ids.append(idx)
            logger.info(f"[Detector] Optimization Active: Ignoring {list(self.ignored_labels)}. Active class count: {len(self.active_ids)}")

        # ── EasyOCR Disabled (Phase 2417) ──
        # EasyOCR was used for OCR distance detection which was cancelled.
        # Running it caused ~50% FPS drop due to GPU competition with YOLO + Roblox.
        self.ocr_reader = None
        logger.info("[Detector] EasyOCR disabled (project cancelled). Full GPU budget restored to YOLO.")

    # ── Model Path Discovery ──────────────────────────────────────────

    def _get_latest_train_folder(self, base_models_dir: str) -> str | None:
        """
        Scans base_models_dir for folders named 'train_YYYYMMDD_HHMM' 
        and returns the full path to the latest one (alphabetically/chronologically).
        """
        if not os.path.exists(base_models_dir):
            return None
            
        import re
        # Pattern matching 'train_20240101_1200'
        pattern = re.compile(r"^train_\d{8}_\d{4}$")
        
        folders = [
            f for f in os.listdir(base_models_dir) 
            if os.path.isdir(os.path.join(base_models_dir, f)) and pattern.match(f)
        ]
        
        if not folders:
            return None
            
        # Due to YYYYMMDD_HHMM format, a string sort is a chronological sort
        folders.sort()
        latest_folder_name = folders[-1]
        return os.path.join(base_models_dir, latest_folder_name)

    # ------------------------------------------------------------------
    # Model loading
    # ------------------------------------------------------------------

    def _load_model(self) -> None:
        # Priority 1: ONNX (Portable, faster than PT on most GPUs, and supports older hardware)
        if os.path.exists(self.onnx_path):
            if self._try_load("ONNX", self.onnx_path, half=False):
                return

        # Priority 2: PyTorch CUDA FP16
        if os.path.exists(self.pt_path) and self.cuda:
            if self._try_load("PyTorch CUDA", self.pt_path, half=False):
                return

        # Priority 3: TensorRT engine (RTX 30+ only)
        if os.path.exists(self.trt_path):
            if self._try_load("TensorRT", self.trt_path, half=False):
                return

        # Priority 4: PyTorch CPU fallback
        if os.path.exists(self.pt_path):
            if self._try_load("PyTorch CPU", self.pt_path, half=False):
                return

        logger.error(
            "FATAL: No valid YOLO11 model found. "
            "Place best.pt or best.engine in assets/models/"
        )

    def _try_load(self, fmt: str, path: str, half: bool) -> bool:
        try:
            logger.info(f"Loading {fmt} model: {path}")

            # task='detect' prevents ultralytics guessing wrong task for .engine files
            model = YOLO(path, task="detect")
            
            # --- Phase 105: Smoke Test ---
            # Some models (especially TensorRT) might load but crash on first inference
            # if the hardware/drivers are incompatible. 
            logger.info(f"Performing Phase 105 Smoke Test for {fmt}...")
            dummy_frame = np.zeros((640, 640, 3), dtype=np.uint8)
            # Run one sync inference (no generator) to force full initialization
            list(model(dummy_frame, device=self.device, verbose=False, imgsz=640))
            logger.info(f"Smoke Test SUCCESS for {fmt}.")

            # Fuse and Half precision casts
            # ONLY apply to PyTorch (.pt) weights. Skip for TensorRT (.engine)
            # to avoid redundant overhead or build errors.
            if path.lower().endswith(".pt"):
                # Fuse Conv2d + BatchNorm layers — ~5% inference speedup
                if hasattr(model, "fuse"):
                    model.fuse()
                    logger.info("Model fused (Conv2d+BN fusion applied)")

                # Explicit FP16 cast — uses Tensor Cores on NVIDIA GPUs
                # REMOVED: Manual .half() on the raw model can cause 'Input type mismatch' 
                # errors in some environments. We will trust the YOLO call in detect() 
                # to handle 'half' parameter correctly.
                # if half and self.cuda:
                #     model.model.half()
                #     self._use_half = True
                pass
            else:
                logger.info("Skipping .fuse() and .half() for non-PyTorch model format.")

            self.model = model
            logger.info(
                f"Model loaded [{fmt}] | classes={len(model.names)} | "
                f"device={self.device} | half={self._use_half}"
            )
            return True
        except Exception as exc:
            logger.warning(f"Failed to load {fmt} model: {exc}")
            return False

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def detect(
        self,
        frame_640: np.ndarray,
        scale: float,
        pad_x: int,
        pad_y: int,
        full_frame: np.ndarray = None,
        roi_offset: tuple = (0, 0),
    ) -> tuple[List[Detection], tuple[float, float]]:
        """
        Run inference on a 640×640 frame (letterboxed full-screen OR ROI crop).

        Parameters
        ----------
        frame_640 : np.ndarray
            640×640 uint8 BGR frame for inference.
        scale : float
            screen→640 scale factor (0.25 for full 2560-wide; 1.0 for ROI crop).
        pad_x : int
            Horizontal letterbox padding (0 in ROI mode).
        pad_y : int
            Vertical letterbox padding (0 in ROI mode).
        full_frame : np.ndarray, optional
            Original full-resolution screen frame (used for OCR).
        roi_offset : tuple[int, int]
            (x_offset, y_offset) added to detected coords to convert ROI-local
            coordinates back to screen-global space. (0, 0) in full-screen mode.

        Returns
        -------
        List[Detection]
            Detections with coordinates already in screen space.
        """
        if self.model is None or frame_640 is None:
            return [], (-1.0, -1.0)

        try:
            # stream=True → returns a generator; avoids allocating a large list in RAM
            current_conf = config.get("detection", "confidence_threshold", self.conf_threshold)
            results = self.model(
                frame_640,
                conf=current_conf,
                device=self.device,
                imgsz=self.img_size,
                verbose=False,
                half=self._use_half,
                stream=True,
                classes=self.active_ids if self.active_ids else None,
            )
        except Exception as exc:
            logger.error(f"Inference error: {exc}")
            return [], (-1.0, -1.0)

        detections: List[Detection] = []

        # Consume the generator — for a single frame there is exactly one result item
        for result in results:
            if len(result.boxes) == 0:
                logger.debug(f"[Detector] Frame processed: 0 detections found.")
                continue

            # ── BULK GPU → CPU in one PCIe transfer (not once per box!) ──
            boxes_arr = result.boxes.xyxy.cpu().numpy()   # (N, 4)
            confs_arr = result.boxes.conf.cpu().numpy()   # (N,)
            cls_arr   = result.boxes.cls.cpu().numpy()    # (N,)
            
            # Instance Segmentation Check
            has_masks = result.masks is not None
            polygons = result.masks.xy if has_masks else None

            logger.debug(f"[Detector] Frame processed: {len(boxes_arr)} detections found. Masks: {has_masks}")

            for i in range(len(boxes_arr)):
                raw_label   = self.model.names[int(cls_arr[i])]
                clean_label = raw_label.replace("_", " ").title()
                conf        = float(confs_arr[i])
                
                # Default to Box Center
                x1, y1, x2, y2 = boxes_arr[i]
                w_yolo  = x2 - x1
                h_yolo  = y2 - y1
                target_x, target_y = (x1 + x2) / 2.0, (y1 + y2) / 2.0

                # ── High-Precision Polygon Logic ──
                if has_masks and i < len(polygons) and len(polygons[i]) > 0:
                    poly = polygons[i] # Array of (N, 2)
                    
                    if "nape" in raw_label.lower():
                        # NAPE LOGIC: Find topmost point (argmin Y)
                        top_idx = np.argmin(poly[:, 1])
                        target_x, target_y = poly[top_idx]
                    else:
                        # CENTROID LOGIC: Center of Mass using cv2.moments
                        m = cv2.moments(poly)
                        if m["m00"] != 0:
                            target_x = m["m10"] / m["m00"]
                            target_y = m["m01"] / m["m00"]
                
                # Map to screen space, then apply ROI global offset
                cx_s = int((target_x - pad_x) / scale) + roi_offset[0]
                cy_s = int((target_y - pad_y) / scale) + roi_offset[1]
                w_s  = int(w_yolo / scale)
                h_s  = int(h_yolo / scale)

                # Clamp to screen bounds
                cx_s = max(0, min(cx_s, self.screen_w))
                cy_s = max(0, min(cy_s, self.screen_h))
                w_s  = max(1, min(w_s,  self.screen_w))
                h_s  = max(1, min(h_s,  self.screen_h))

                detections.append(Detection(clean_label, conf, cx_s, cy_s, w_s, h_s))

        # ── Dual-Distance OCR Pass (Phase 500) ──
        dist_yellow, dist_white = -1.0, -1.0
        ocr_frame = full_frame if full_frame is not None else frame_640
        
        if self.ocr_reader and ocr_frame is not None:
             # USER COORDINATES (2560x1440): Yellow=1262,738 | White=1301,734
             # We take a small crop around these points
             try:
                 h, w = ocr_frame.shape[:2]
                 if w == 2560: # High Res Path
                     roi_l = ocr_frame[710:765, 1210:1285] # Left (Yellow/Green)
                     roi_r = ocr_frame[710:765, 1285:1360] # Right (White)
                 else: # Scaled Fallback
                     roi_l = ocr_frame[310:340, 260:310] 
                     roi_r = ocr_frame[310:340, 330:380]
                 
                 # Projectile Filter (Covers Lime-Green to Warm Orange)
                 hsv_l = cv2.cvtColor(roi_l, cv2.COLOR_BGR2HSV)
                 mask_y = cv2.inRange(hsv_l, (5, 50, 50), (90, 255, 255))
                 
                 # White Filter (BGR)
                 mask_w = cv2.inRange(roi_r, (200, 200, 200), (255, 255, 255))
                 
                 # Resizing for OCR accuracy
                 mask_y = cv2.resize(mask_y, (0,0), fx=2, fy=2, interpolation=cv2.INTER_LINEAR)
                 mask_w = cv2.resize(mask_w, (0,0), fx=2, fy=2, interpolation=cv2.INTER_LINEAR)
                 
                 # OCR Execution
                 res_y = self.ocr_reader.readtext(mask_y, allowlist='0123456789.')
                 res_w = self.ocr_reader.readtext(mask_w, allowlist='0123456789.')
                 
                 if res_y: dist_yellow = float(res_y[0][1]) if res_y[0][1].replace('.','',1).isdigit() else -1.0
                 if res_w: dist_white = float(res_w[0][1]) if res_w[0][1].replace('.','',1).isdigit() else -1.0
                 
                 if dist_yellow != -1 or dist_white != -1:
                     logger.debug(f"[OCR] Yellow: {dist_yellow} | White: {dist_white}")
             except Exception as e:
                 logger.error(f"[OCR] Pass failed: {e}")

        return detections, (dist_yellow, dist_white)
