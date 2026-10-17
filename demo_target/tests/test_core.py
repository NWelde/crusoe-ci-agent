import pytest
from demo_math import moving_average, normalize


def test_moving_average_uses_complete_trailing_windows():
    assert moving_average([1, 2, 3, 4], 2) == [1.5, 2.5, 3.5]


def test_moving_average_returns_empty_when_window_is_too_large():
    assert moving_average([1, 2], 3) == []


def test_moving_average_rejects_non_positive_window():
    with pytest.raises(ValueError, match="window must be positive"):
        moving_average([1, 2], 0)


def test_normalize_returns_proportions():
    assert normalize([2, 3, 5]) == [0.2, 0.3, 0.5]


def test_normalize_rejects_zero_total():
    with pytest.raises(ValueError, match="non-zero sum"):
        normalize([1, -1])
