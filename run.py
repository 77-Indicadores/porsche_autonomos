import sys
from pathlib import Path


vendor = Path(__file__).resolve().parent / ".vendor"
if vendor.exists():
    sys.path.insert(0, str(vendor))

import uvicorn


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000)
