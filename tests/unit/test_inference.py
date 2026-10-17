from dataclasses import dataclass

import pytest
import requests
from pydantic import BaseModel

from ci_agent.inference import CrusoeInference, InferenceError


@dataclass
class FakeResponse:
    status_code: int
    body: object

    @property
    def ok(self):
        return 200 <= self.status_code < 300

    def json(self):
        return self.body


class FakeSession:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def make_client(session, **overrides):
    values = {
        "api_key": "test-secret",
        "model": "example/model",
        "session": session,
        "max_retries": 0,
    }
    values.update(overrides)
    return CrusoeInference(**values)


def test_complete_sends_separate_prompts_and_returns_only_message_content():
    session = FakeSession([FakeResponse(200, {"choices": [{"message": {"content": "READY"}}]})])
    client = make_client(session)

    result = client.complete(system_prompt="role instructions", user_prompt="task evidence")

    assert result == "READY"
    url, request = session.calls[0]
    assert url == "https://api.inference.crusoecloud.com/v1/chat/completions"
    assert request["headers"]["Authorization"] == "Bearer test-secret"
    assert request["json"]["messages"] == [
        {"role": "system", "content": "role instructions"},
        {"role": "user", "content": "task evidence"},
    ]
    assert "test-secret" not in repr(request["json"])


def test_complete_retries_transient_service_failure_with_bounded_count(monkeypatch):
    monkeypatch.setattr("ci_agent.inference.time.sleep", lambda _: None)
    session = FakeSession([
        FakeResponse(503, {}),
        FakeResponse(200, {"choices": [{"message": {"content": "READY"}}]}),
    ])
    client = make_client(session, max_retries=1)

    assert client.complete(system_prompt="system", user_prompt="user") == "READY"
    assert len(session.calls) == 2


def test_auth_error_is_actionable_and_does_not_echo_secret():
    client = make_client(FakeSession([FakeResponse(401, {"error": "test-secret"})]))

    with pytest.raises(InferenceError, match="check its validity") as error:
        client.complete(system_prompt="system", user_prompt="user")

    assert "test-secret" not in str(error.value)


def test_structured_output_is_validated():
    class Decision(BaseModel):
        action: str

    session = FakeSession([
        FakeResponse(200, {"choices": [{"message": {"content": '{"action":"stop"}'}}]})
    ])
    result = make_client(session).complete_structured(
        system_prompt="decide", user_prompt="evidence", output_model=Decision
    )

    assert result == Decision(action="stop")
    assert "action" in session.calls[0][1]["json"]["messages"][0]["content"]


def test_non_https_remote_endpoint_is_rejected():
    with pytest.raises(ValueError, match="must use HTTPS"):
        make_client(FakeSession([]), base_url="http://example.com/v1")


def test_connection_timeout_has_no_unbounded_retry(monkeypatch):
    monkeypatch.setattr("ci_agent.inference.time.sleep", lambda _: None)
    session = FakeSession([requests.Timeout("opaque timeout")])
    client = make_client(session, max_retries=1)
    session.responses = iter([requests.Timeout("opaque timeout"), requests.Timeout("opaque timeout")])

    with pytest.raises(InferenceError, match="timed out"):
        client.complete(system_prompt="system", user_prompt="user")
    assert len(session.calls) == 2
