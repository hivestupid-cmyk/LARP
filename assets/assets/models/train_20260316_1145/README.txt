# ─────────────────────────────────────────────────────────────────
#  AOTR Bot — Model Directory
# ─────────────────────────────────────────────────────────────────
#  Place one of the following in this folder:
#    best.pt      — YOLO11n PyTorch weights  (CUDA FP16 or CPU)
#    best.engine  — TensorRT FP16 engine     (fastest, auto-preferred)
#
# ─── STEP 1: Train ───────────────────────────────────────────────
#
#  yolo train model=yolo11n.pt data=custom_data.yaml epochs=100 imgsz=640
#
#  The trained weights will be at:
#    runs/detect/train/weights/best.pt
#
#  Copy best.pt into this folder before exporting.
#
# ─── STEP 2: Export (.pt → .engine, NO intermediate ONNX kept) ──
#
#  Option A — ultralytics CLI (direct TensorRT, FP16):
#    yolo export model=best.pt format=engine half=True device=0 imgsz=640
#
#  Option B — project helper script:
#    python tools/export_model.py --pt assets/models/best.pt --workspace 4
#
#  Note: ultralytics uses ONNX *internally* as a transient build step
#  when compiling to TensorRT. The final artifact saved here is ONLY
#  best.engine — no .onnx file is retained or used for inference.
#
# ─── Auto-detection priority (bot/detector.py) ───────────────────
#  1. best.engine  ← TensorRT FP16 (preferred, ~10–20 ms inference)
#  2. best.pt      ← PyTorch CUDA FP16 fallback
#  3. best.pt      ← PyTorch CPU last resort
# ─────────────────────────────────────────────────────────────────
