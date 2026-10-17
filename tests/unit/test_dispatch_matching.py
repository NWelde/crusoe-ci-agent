from datetime import UTC, datetime
from unittest.mock import Mock

from ci_agent.github.runs import GitHubClient


def test_dispatch_matches_github_second_precision_without_accepting_prior_or_wrong_revision():
    client = GitHubClient("test-token")
    prior = {"id": 1, "head_sha": "exact-sha", "created_at": "2026-10-17T00:00:00Z"}
    wrong_sha = {"id": 2, "head_sha": "other-sha", "created_at": "2026-10-17T00:00:01Z"}
    match = {"id": 3, "head_sha": "exact-sha", "created_at": "2026-10-17T00:00:01Z"}
    client.find_dispatch_run = Mock(return_value=[prior, wrong_sha, match])
    result = client.wait_for_dispatch_run(
        "owner", "repo", "workflow", "branch", "exact-sha",
        dispatched_after=datetime(2026, 10, 17, 0, 0, 1, 987654, tzinfo=UTC),
        timeout_seconds=1,
    )
    assert result == match
