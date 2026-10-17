"""Coverage equivalence for strategy-certified batching/sharding extensions.

Only a strategy validator may supply a plan; never load a plan from a report or
trust a model's assertion. Required GitHub check names remain on both sides.
"""

from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class CoveragePlan:
    baseline: dict[str, tuple[str, ...]]
    candidate: dict[str, tuple[str, ...]]
    required_checks: tuple[str, ...]

    def __post_init__(self):
        signatures = []
        if not self.required_checks:
            raise ValueError("Coverage plan must preserve explicit required-check identities")
        for jobs in (self.baseline, self.candidate):
            if not set(self.required_checks) <= jobs.keys():
                raise ValueError("Required-check identity was removed")
            units = Counter(unit for values in jobs.values() for unit in values)
            if not units or any(n != 1 for n in units.values()):
                raise ValueError("Coverage units must be a complete disjoint partition")
            signatures.append(units)
        if signatures[0] != signatures[1]:
            raise ValueError("Check coverage differs between variants")


def expected_count(expected, variant):
    return len(getattr(expected, variant)) if isinstance(expected, CoveragePlan) else expected


def coverage_signature(jobs, expected, variant):
    names = Counter(j.get("name") for j in jobs)
    if None in names:
        raise ValueError("Missing job check name")
    if not isinstance(expected, CoveragePlan):
        return names
    mapping = getattr(expected, variant)
    if names != Counter(mapping.keys()):
        raise ValueError("Run does not match strategy-certified coverage plan")
    return Counter(unit for name in names for unit in mapping[name])


def runner_signature(jobs, expected, variant):
    if not isinstance(expected, CoveragePlan):
        return Counter((j["name"], tuple(sorted(j.get("labels", [])))) for j in jobs)
    mapping = getattr(expected, variant)
    return Counter(
        (unit, tuple(sorted(j.get("labels", []))))
        for j in jobs
        for unit in (
            mapping[j["name"]]
            + ((f"required-check:{j['name']}",) if j["name"] in expected.required_checks else ())
        )
    )
