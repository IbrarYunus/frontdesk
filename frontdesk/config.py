import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

MODEL = os.environ.get("FRONTDESK_MODEL", "claude-opus-5")
JUDGE_MODEL = os.environ.get("FRONTDESK_JUDGE_MODEL", "claude-haiku-4-5")
EFFORT = os.environ.get("FRONTDESK_EFFORT", "medium")
DB_PATH = Path(os.environ.get("FRONTDESK_DB", ROOT / "data" / "store.db"))

# The demo data is dated, so "today" is pinned. Evals stay repeatable.
TODAY = date.fromisoformat(os.environ.get("FRONTDESK_TODAY", "2026-09-15"))

APPROVAL_THRESHOLD = float(os.environ.get("FRONTDESK_APPROVAL_THRESHOLD", "100"))
CHANGE_OF_MIND_DAYS = 30
DAMAGED_DAYS = 90
MAX_STEPS = 12

# USD per million tokens: input, output, cache read, cache write
PRICES = {
    "claude-opus-5": (5.0, 25.0, 0.5, 6.25),
    "claude-sonnet-5": (2.0, 10.0, 0.2, 2.5),
    "claude-haiku-4-5": (1.0, 5.0, 0.1, 1.25),
}


def cost_usd(model: str, usage: dict) -> float | None:
    if model not in PRICES:
        return None
    p_in, p_out, p_read, p_write = PRICES[model]
    return (
        usage.get("input_tokens", 0) * p_in
        + usage.get("output_tokens", 0) * p_out
        + usage.get("cache_read_input_tokens", 0) * p_read
        + usage.get("cache_creation_input_tokens", 0) * p_write
    ) / 1_000_000
