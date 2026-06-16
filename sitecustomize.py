from pathlib import Path
import sys

vendor = Path(__file__).resolve().parent / ".vendor"
if vendor.exists():
    sys.path.insert(0, str(vendor))
