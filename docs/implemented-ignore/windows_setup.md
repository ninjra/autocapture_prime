# Windows Setup (Capture + Models)

This project expects Windows 11 + RTX 4090 and local models stored under `D:\autocapture\models`.

## Dependencies
Install Python deps:
```powershell
pip install -e .
```

Optional native tools:
- `ffmpeg` with NVENC for GPU encoding (if used).

## Model paths
Place local models under:
- `D:\autocapture\models\ocr`
- `D:\autocapture\models\vlm`
- `D:\autocapture\models\embeddings`
- `D:\autocapture\models\reranker`

## Windows-only tests
Run:
```powershell
PYTHONPATH=. python -m unittest discover -s tests -q
```
