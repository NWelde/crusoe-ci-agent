import pytest
import requests

from ci_agent.github.runs import GitHubAPIError, GitHubClient, sample_runs


class FakeResponse:
    def __init__(self, status_code, body):
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def test_sample_runs_converts_github_run_and_sums_required_job_seconds():
    t0 = "2026-10-17T10:00:00Z"
    t1 = "2026-10-17T10:01:30Z"
    session = FakeSession(
        [
            FakeResponse(200, {"id": 123, "default_branch": "master"}),
            FakeResponse(
                200,
                {
                    "workflow_runs": [
                        {
                            "id": 77,
                            "workflow_id": 8,
                            "run_attempt": 1,
                            "head_sha": "abc123",
                            "status": "completed",
                            "conclusion": "success",
                            "created_at": t0,
                            "run_started_at": t0,
                            "updated_at": t1,
                        }
                    ]
                },
            ),
            FakeResponse(
                200,
                {
                    "jobs": [
                        {
                            "id": 1,
                            "name": "lint",
                            "status": "completed",
                            "conclusion": "success",
                            "started_at": t0,
                            "completed_at": t1,
                        },
                        {
                            "id": 2,
                            "name": "Active Record 8.1 with PostgreSQL 18",
                            "status": "completed",
                            "conclusion": "success",
                            "started_at": t0,
                            "completed_at": "2026-10-17T10:02:00Z",
                        },
                        {
                            "id": 3,
                            "name": "unrelated",
                            "status": "completed",
                            "conclusion": "success",
                            "started_at": t0,
                            "completed_at": "2026-10-17T10:10:00Z",
                        },
                    ]
                },
            ),
        ]
    )
    client = GitHubClient("secret", session=session)

    repository, snapshots, report = sample_runs(
        client,
        "madeintandem",
        "jsonb_accessor",
        limit=10,
        workflow_id="8",
        required_checks=("lint", "tests"),
        required_job_patterns={"tests": ("Active Record ",)},
    )

    assert repository["id"] == 123
    assert len(snapshots) == 1
    assert snapshots[0].github_run_id == "77"
    assert snapshots[0].source_revision == "abc123"
    assert report["runs"][0]["required_runner_seconds"] == 210
    assert report["runs"][0]["required_check_results"] == {"lint": True, "tests": True}
    assert report["runs"][0]["evidence_class"] == "LIVE_GITHUB_METADATA"
    assert session.calls[0][1]["headers"]["Authorization"] == "Bearer secret"
    assert "secret" not in repr(report)


def test_sample_filters_workflow_before_fetching_jobs():
    session = FakeSession(
        [
            FakeResponse(200, {"id": 123, "default_branch": "master"}),
            FakeResponse(
                200,
                {
                    "workflow_runs": [
                        {
                            "id": 77,
                            "workflow_id": 9,
                            "head_sha": "abc",
                            "status": "completed",
                            "created_at": "2026-10-17T10:00:00Z",
                        }
                    ]
                },
            ),
        ]
    )
    _, runs, report = sample_runs(
        GitHubClient("secret", session=session), "o", "r", workflow_id="8"
    )
    assert runs == ()
    assert report["runs_returned"] == 0
    assert len(session.calls) == 2


def test_api_errors_omit_response_body_and_token():
    client = GitHubClient("secret", session=FakeSession([FakeResponse(401, {"message": "secret"})]))
    with pytest.raises(GitHubAPIError) as error:
        client.repository("o", "r")
    assert "secret" not in str(error.value)
    assert "HTTP 401" in str(error.value)


def test_api_network_errors_are_redacted():
    client = GitHubClient("secret", session=FakeSession([requests.Timeout("secret timeout")]))
    with pytest.raises(GitHubAPIError) as error:
        client.repository("o", "r")
    assert "secret" not in str(error.value)
    assert "Timeout" in str(error.value)


def test_transient_read_retries_are_bounded_and_do_not_apply_to_writes(monkeypatch):
    monkeypatch.setattr("ci_agent.github.runs.time.sleep", lambda _: None)
    session = FakeSession([requests.ConnectionError("secret"), FakeResponse(200, {"id": 1})])
    client = GitHubClient("secret", session=session, read_retries=1)
    assert client.repository("o", "r") == {"id": 1}
    assert len(session.calls) == 2
    exhausted = FakeSession([requests.Timeout("secret")] * 3)
    with pytest.raises(GitHubAPIError, match="Timeout"):
        GitHubClient("secret", session=exhausted, read_retries=2).repository("o", "r")
    assert len(exhausted.calls) == 3


def test_run_limit_is_bounded():
    client = GitHubClient("secret", session=FakeSession([]))
    with pytest.raises(ValueError, match="between 1 and 100"):
        client.recent_runs("o", "r", limit=101)


def test_run_jobs_reads_all_pages_for_large_matrices():
    session = FakeSession(
        [
            FakeResponse(200, {"total_count": 187, "jobs": [{"id": i} for i in range(100)]}),
            FakeResponse(200, {"total_count": 187, "jobs": [{"id": i} for i in range(100, 187)]}),
        ]
    )
    jobs = GitHubClient("secret", session=session).run_jobs("o", "r", 77)
    assert len(jobs) == 187
    assert [call[1]["params"]["page"] for call in session.calls] == [1, 2]
