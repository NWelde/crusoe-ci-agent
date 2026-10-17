import pytest
import yaml

from ci_agent.experiments.live_loop import count_workflow_jobs
from ci_agent.strategies import REGISTRY
from ci_agent.workflows.matrix import matrix_cells


def test_include_augments_original_cells_and_adds_distinct_combinations():
    # GitHub's documented include semantics: added properties can be overwritten,
    # original axis values cannot; appended cells are not merged on later rules.
    cells = matrix_cells(
        {
            "fruit": ["apple", "pear"],
            "animal": ["cat", "dog"],
            "include": [
                {"color": "green"},
                {"color": "pink", "animal": "cat"},
                {"fruit": "apple", "shape": "circle"},
                {"fruit": "banana"},
                {"fruit": "banana", "animal": "cat"},
            ],
        }
    )
    assert len(cells) == 6
    assert cells[0] == {"fruit": "apple", "animal": "cat", "color": "pink", "shape": "circle"}
    assert cells[-2:] == [{"fruit": "banana"}, {"fruit": "banana", "animal": "cat"}]


def test_include_only_and_excluded_cells_added_back():
    assert len(matrix_cells({"include": [{"os": "ubuntu-latest"}, {"os": "windows-latest"}]})) == 2
    assert matrix_cells(
        {
            "python": ["3.11", "3.12"],
            "exclude": [{"python": "3.11"}],
            "include": [{"python": "3.11", "extra": True}],
        }
    ) == [{"python": "3.12"}, {"python": "3.11", "extra": True}]


@pytest.mark.parametrize(
    "matrix",
    [
        "${{ fromJSON(needs.plan.outputs.matrix) }}",
        {"os": []},
        {"include": "${{ inputs.matrix }}"},
        {"exclude": ["invalid"]},
    ],
)
def test_unresolved_or_invalid_matrix_never_guesses_coverage(matrix):
    with pytest.raises(ValueError):
        matrix_cells(matrix)


def test_real_ci_with_include_matrix_preserves_full_count_and_commands():
    workflow = {
        "on": "pull_request",
        "jobs": {
            "tests": {
                "runs-on": "${{ matrix.os }}",
                "strategy": {
                    "matrix": {
                        "include": [
                            {"os": "ubuntu-latest", "python": "3.11"},
                            {"os": "windows-latest", "python": "3.12"},
                        ]
                    }
                },
                "steps": [{"uses": "actions/checkout@v4"}, {"run": "python -m pytest -q"}],
            }
        },
    }
    raw = yaml.safe_dump(workflow)
    assert count_workflow_jobs(raw, ["tests"]) == 2
    proposal = REGISTRY["superseded_cancellation"].propose(raw)
    assert proposal is not None
    assert count_workflow_jobs(proposal["candidate_workflow"], ["tests"]) == 2
