import os
import urllib.request
import sys

# Placeholder URL - Change this to your actual GitHub Release URL once you upload the model!
MODEL_URL = "https://github.com/hivestupid-cmyk/LARP-Models/releases/download/v1.0/best.pt"
MODEL_FILENAME = "best.pt"

def _progress_hook(count, block_size, total_size):
    """Callback function for urlretrieve to show a progress bar."""
    if total_size == -1:
        # If the server doesn't provide a content-length
        downloaded = count * block_size
        sys.stdout.write(f"\rDownloading... {downloaded / (1024 * 1024):.2f} MB")
        sys.stdout.flush()
        return

    percent = int(count * block_size * 100 / total_size)
    # Clamp percent to 100 max
    percent = min(100, percent)
    
    bar_length = 40
    filled_length = int(bar_length * percent // 100)
    bar = '=' * filled_length + '-' * (bar_length - filled_length)
    
    sys.stdout.write(f"\rDownloading {MODEL_FILENAME}: [{bar}] {percent}% ")
    sys.stdout.flush()

def ensure_model_exists():
    """Checks if the model exists in assets/models/. If not, downloads it."""
    # Resolve the root directory of the project (parent of 'bot' folder)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    
    models_dir = os.path.join(project_root, "assets", "models")
    model_path = os.path.join(models_dir, MODEL_FILENAME)

    if os.path.exists(model_path):
        print(f"[ModelDownloader] Model {MODEL_FILENAME} is already present.")
        return True

    print(f"[ModelDownloader] AI Model not found at {model_path}.")
    print(f"[ModelDownloader] Starting download from {MODEL_URL} ...")
    
    # Create directory if it doesn't exist
    os.makedirs(models_dir, exist_ok=True)

    try:
        urllib.request.urlretrieve(MODEL_URL, model_path, reporthook=_progress_hook)
        print("\n[ModelDownloader] Download completed successfully!")
        return True
    except Exception as e:
        print(f"\n[ModelDownloader] ERROR: Failed to download the model. {e}")
        # Clean up partial file if it exists
        if os.path.exists(model_path):
            os.remove(model_path)
        return False

if __name__ == "__main__":
    success = ensure_model_exists()
    if not success:
        sys.exit(1)
