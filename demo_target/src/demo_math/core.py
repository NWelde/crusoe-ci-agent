"""Simple numerical helpers with deterministic unit tests."""

from collections.abc import Sequence


def moving_average(values: Sequence[float], window: int) -> list[float]:
    """Return each complete trailing-window average."""
    if window < 1:
        raise ValueError("window must be positive")
    if window > len(values):
        return []
    return [
        sum(values[start : start + window]) / window
        for start in range(len(values) - window + 1)
    ]


def normalize(values: Sequence[float]) -> list[float]:
    """Scale values to sum to one; reject inputs with no meaningful total."""
    total = sum(values)
    if total == 0:
        raise ValueError("values must have a non-zero sum")
    return [value / total for value in values]
