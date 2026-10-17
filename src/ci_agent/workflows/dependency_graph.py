"""Workflow dependency parsing adapted from Shadow Runner's implementation.

Source: NWelde/shadow-runner, snapshot 974366782efa7e7e27421d708c66f261b88b14ff.
Copyright (c) 2026 Nathan Beyene; used under the MIT License. See
docs/licenses/SHADOW_RUNNER_LICENSE for the complete notice.
"""

from __future__ import annotations

from typing import Any

import networkx as nx
import yaml


def build_dep_graph(raw_yaml: str) -> dict[str, list[str]]:
    """Return each workflow job mapped to its direct `needs` dependencies."""
    config: dict[str, Any] = yaml.safe_load(raw_yaml) or {}
    jobs = config.get("jobs", {})
    graph: dict[str, list[str]] = {}
    for name, job_config in jobs.items():
        dependencies = (job_config or {}).get("needs")
        if dependencies is None:
            graph[name] = []
        elif isinstance(dependencies, str):
            graph[name] = [dependencies]
        else:
            graph[name] = list(dependencies)
    return graph


def critical_path(dependencies: dict[str, list[str]], durations: dict[str, float]) -> list[str]:
    """Return the slowest dependency chain; reject cyclic job definitions."""
    graph = nx.DiGraph()
    for job, needs in dependencies.items():
        graph.add_node(job, weight=float(durations.get(job, 0.0)))
        for dependency in needs:
            if dependency not in graph:
                graph.add_node(dependency, weight=float(durations.get(dependency, 0.0)))
            graph.add_edge(dependency, job)
    try:
        order = list(nx.topological_sort(graph))
    except nx.NetworkXUnfeasible as exc:
        raise ValueError("workflow job dependencies contain a cycle") from exc
    distances: dict[str, float] = {}
    parents: dict[str, str | None] = {}
    for node in order:
        best_parent = max(graph.predecessors(node), key=lambda item: distances[item], default=None)
        previous = distances[best_parent] if best_parent else 0.0
        distances[node] = previous + float(graph.nodes[node].get("weight", 0.0))
        parents[node] = best_parent
    if not distances:
        return []
    node: str | None = max(distances, key=distances.get)
    path: list[str] = []
    while node is not None:
        path.append(node)
        node = parents[node]
    return list(reversed(path))
