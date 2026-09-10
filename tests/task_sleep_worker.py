"""Disposable process for cancellation regression tests."""
import json
import sys
import time
from pathlib import Path

payload = json.load(sys.stdin)
Path(payload["started"]).touch()
time.sleep(30)
Path(payload["finished"]).touch()
