"""Minimal Runway API client (used by runway_gen.py).

API key: the environment variable RUNWAYML_API_SECRET, otherwise the .env file the environment
variable RUNWAY_ENV_FILE points to, otherwise .env in this folder (format: RUNWAYML_API_SECRET=...).
Never commit .env (it is in .gitignore).
"""
import base64
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

API = "https://api.dev.runwayml.com/v1"
API_VERSION = "2024-11-06"
HERE = Path(__file__).resolve().parent

# credits (1 credit = $0.01). docs.dev.runwayml.com/guides/pricing, as of 2026-10
IMAGE_MODEL, IMAGE_RATIO = "gpt_image_2_5_flare", "2560:1440"
IMAGE_RATES = {"low": 1, "medium": 5, "high": 20}         # per image (1K/2K)
VIDEO_MODEL = "h3_max"
VIDEO_RATES = {"480p": 5, "768p": 8}                       # per second


def api_key():
    key = os.environ.get("RUNWAYML_API_SECRET")
    if key:
        return key
    for env in (os.environ.get("RUNWAY_ENV_FILE"), HERE / ".env"):
        if env and Path(env).exists():
            for line in Path(env).read_text().splitlines():
                name, _, value = line.partition("=")
                if name.strip() == "RUNWAYML_API_SECRET":
                    return value.strip().strip("'\"")
    sys.exit("RUNWAYML_API_SECRET not found (set the environment variable or put it in .env)")


def request(method, path, body=None):
    req = urllib.request.Request(
        API + path,
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {api_key()}",
            "X-Runway-Version": API_VERSION,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP {e.code} {path}: {e.read().decode(errors='replace')}")


def wait(task_id):
    while True:
        t = request("GET", f"/tasks/{task_id}")
        if t["status"] == "SUCCEEDED":
            return t
        if t["status"] in ("FAILED", "CANCELLED"):
            raise RuntimeError(f"{t['status']}: {t.get('failure')} ({t.get('failureCode')})")
        prog = t.get("progress")
        print(f"    {t['status']}" + (f" {prog:.0%}" if isinstance(prog, (int, float)) else ""), flush=True)
        time.sleep(10)


def submit(path, body, dst, note):
    """Submit, wait for completion, save the output to dst, and record the task and cost in dst.json (not the image data)"""
    print(f"start {dst.name}", flush=True)
    task = request("POST", path, body)
    try:
        done = wait(task["id"])
    except RuntimeError as e:
        print(f"  failed: {e}")
        return None
    outs = done["output"]
    paths = [dst] if len(outs) == 1 else [dst.with_name(f"{dst.stem}__{i}{dst.suffix}") for i in range(1, len(outs) + 1)]
    for url, p in zip(outs, paths):
        urllib.request.urlretrieve(url, p)
        print(f"  saved {p.name}")
    slim = {k: v for k, v in body.items() if k != "promptImage"}
    dst.with_suffix(".json").write_text(json.dumps(
        {"task": done["id"], "cost": done.get("cost"), "request": {**slim, **note}}, ensure_ascii=False, indent=2))
    return paths


def image_uri(path):
    # turn it into a high-quality JPEG data URI so it fits the 5MB limit
    buf = io.BytesIO()
    Image.open(path).convert("RGB").save(buf, "JPEG", quality=92)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
