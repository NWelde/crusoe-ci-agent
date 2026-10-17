"""Expand static GitHub matrix axes, exclude rules and include augmentations."""

import itertools
from copy import deepcopy


def matrix_cells(matrix):
    if isinstance(matrix, str):
        raise ValueError("Dynamic matrices need resolved run coverage evidence")  # noqa: TRY004
    if not isinstance(matrix, dict):
        raise TypeError("Matrix must be a mapping or an unresolved expression")
    axes = {key: value for key, value in matrix.items() if key not in ("include", "exclude")}
    if any(not isinstance(values, list) or not values for values in axes.values()):
        raise ValueError("Matrix axes must be nonempty static lists")
    includes, excludes = matrix.get("include", []), matrix.get("exclude", [])
    if any(
        not isinstance(rules, list) or any(not isinstance(rule, dict) for rule in rules)
        for rules in (includes, excludes)
    ):
        raise ValueError("Matrix include/exclude rules must be static mappings")
    originals = [
        dict(zip(axes, values, strict=True)) for values in itertools.product(*axes.values())
    ]
    if not axes and includes:
        originals = []
    originals = [
        cell
        for cell in originals
        if not any(all(cell.get(key) == value for key, value in rule.items()) for rule in excludes)
    ]
    cells = deepcopy(originals)
    extra = []
    for rule in includes:
        matching = [
            index
            for index, original in enumerate(originals)
            if all(key not in axes or original.get(key) == value for key, value in rule.items())
        ]
        if matching:
            for index in matching:
                cells[index].update(rule)
        else:
            extra.append(deepcopy(rule))
    return cells + extra
