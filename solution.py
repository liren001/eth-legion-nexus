"""BOUNTY-002: frozen causal local-field predictor.

The model treats each symbol as a short-lived activity impulse.  Activity
persists exponentially and is scored through a bounded, forward-shifted
numeric neighbourhood.  Parameters were frozen from the first half of the
published prefix; no future row is read by predict_next().

This file is deliberately standalone: Python 3 + NumPy, no network access.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

ALPHABET = 33
DRAW_SIZE = 6
HALF_LIFE = 0.5
RADIUS = 7
DRIFT = 2
SELF_WEIGHT = 0.25


def _rows(history: Any) -> list[list[int]]:
    """Normalize and validate the published object or a list of draws."""
    if isinstance(history, dict):
        history = history.get("data", history.get("history"))
    if not isinstance(history, (list, tuple)) or not history:
        raise ValueError("non-empty ordered history is required")

    result: list[list[int]] = []
    for index, row in enumerate(history, start=1):
        if isinstance(row, dict):
            if "t" in row and row["t"] != index:
                raise ValueError("tick labels must be consecutive and one-based")
            row = row.get("reds", row.get("values"))
        if not isinstance(row, (list, tuple, np.ndarray)):
            raise ValueError("each tick must contain six integers")
        if len(row) != DRAW_SIZE:
            raise ValueError("each tick must contain six integers")
        if any(
            isinstance(value, (bool, np.bool_))
            or not isinstance(value, (int, np.integer))
            or not 1 <= int(value) <= ALPHABET
            for value in row
        ):
            raise ValueError("symbols must be distinct integers in 1..33")
        values = [int(value) for value in row]
        if len(set(values)) != DRAW_SIZE:
            raise ValueError("each tick must contain six distinct symbols")
        result.append(values)
    return result


def _matrix(history: Any) -> np.ndarray:
    rows = _rows(history)
    matrix = np.zeros((len(rows), ALPHABET), dtype=float)
    for index, row in enumerate(rows):
        matrix[index, np.asarray(row, dtype=int) - 1] = 1.0
    return matrix


def _activity(matrix: np.ndarray) -> np.ndarray:
    """Return activity immediately after the last observed tick."""
    decay = 2.0 ** (-1.0 / HALF_LIFE)
    state = np.zeros(ALPHABET, dtype=float)
    for observed in matrix:
        state = decay * state + (1.0 - decay) * observed
    return state


def _score(state: np.ndarray) -> np.ndarray:
    """Apply the fixed non-circular local field on the numeric alphabet."""
    scores = SELF_WEIGHT * state.copy()
    for offset in range(-RADIUS, RADIUS + 1):
        shift = offset + DRIFT
        if shift >= 0:
            scores[shift:] += state[: ALPHABET - shift] if shift else state
        else:
            scores[:shift] += state[-shift:]
    return scores


def predict_next(history: Any) -> list[int]:
    """Predict six unique symbols using only the supplied past history."""
    state = _activity(_matrix(history))
    best = np.argsort(-_score(state), kind="stable")[:DRAW_SIZE]
    return sorted((best + 1).astype(int).tolist())


def replay(history: Any, first_tick: int = 2, last_tick: int | None = None) -> dict[str, float | int]:
    """Causal walk-forward diagnostic on an already published sequence."""
    rows = _rows(history)
    matrix = _matrix(rows)
    end = len(rows) if last_tick is None else last_tick
    if not 2 <= first_tick <= end <= len(rows):
        raise ValueError("invalid inclusive replay range")

    hits: list[int] = []
    for target in range(first_tick - 1, end):
        prediction = set(predict_next(rows[:target]))
        hits.append(len(prediction.intersection(rows[target])))
    total = sum(hits)
    mean = total / len(hits)
    baseline = DRAW_SIZE * DRAW_SIZE / ALPHABET
    return {
        "first_tick": first_tick,
        "last_tick": end,
        "ticks": len(hits),
        "total_hits": total,
        "mean_hits": mean,
        "uniform_baseline": baseline,
        "lift": mean / baseline,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history", type=Path, help="JSON history; defaults to bounty/dataset_task2.json")
    parser.add_argument("--validate", action="store_true", help="also print causal public-prefix diagnostics")
    args = parser.parse_args()

    path = args.history
    if path is None:
        path = next(
            (candidate for candidate in (Path("bounty/dataset_task2.json"), Path("dataset_task2.json")) if candidate.is_file()),
            None,
        )
    if path is None:
        parser.error("dataset_task2.json not found; pass --history PATH")

    history = json.loads(path.read_text(encoding="utf-8-sig"))
    output: dict[str, object] = {
        "next_tick": len(_rows(history)) + 1,
        "prediction": predict_next(history),
        "parameters": {
            "half_life": HALF_LIFE,
            "radius": RADIUS,
            "drift": DRIFT,
            "self_weight": SELF_WEIGHT,
            "tie_break": "lower symbol",
        },
    }
    if args.validate:
        output["full_public"] = replay(history)
        output["selection_prefix"] = replay(history, 51, 200)
        output["confirmation_prefix"] = replay(history, 201, 400)
    print(json.dumps(output, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
