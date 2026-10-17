import io
import zipfile

import pytest

from ci_agent.experiments.live_cache import compare_pair_caches, parse_cache_archive


def logs(text):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("tests/3_Run ruby_setup-ruby@sha.txt", text)
    return output.getvalue()


@pytest.mark.parametrize(
    "text,status",
    [
        ("Cache key: requested\nFound cache for key: requested\n", "exact_hit"),
        ("Cache key: requested\nFound cache for key: fallback\n", "partial_hit"),
        ("Cache key: requested\nCache not found for input keys: requested\n", "miss"),
        ("Cache key: requested\n[command]bundle install --jobs 4\n", "unknown"),
    ],
)
def test_only_explicit_cache_evidence_classifies_state(text, status):
    result = parse_cache_archive(logs(text))
    assert result["tests"]["status"] == status
    assert "requested" not in result["tests"].values()


def test_cache_comparison_requires_full_matching_explicit_evidence():
    hit = {"run_id": 1, "jobs": parse_cache_archive(logs("Cache key: k\nFound cache for key: k\n"))}
    other = dict(hit, run_id=2)
    assert compare_pair_caches(hit, other, 1)["matched"]
    assert not compare_pair_caches(hit, other, 2)["matched"]
    unknown = {"run_id": 2, "jobs": parse_cache_archive(logs("Cache key: k\n"))}
    assert not compare_pair_caches(hit, unknown, 1)["matched"]
    assert not compare_pair_caches(unknown, unknown, 1)["matched"]


@pytest.mark.parametrize('error_kind', ['chunked', 'timeout', 'connection', 'server'])
def test_archive_retry_discards_partial_stream_and_closes_responses(tmp_path, error_kind):
    import hashlib
    from types import SimpleNamespace
    from unittest.mock import Mock

    import requests

    from ci_agent.experiments.live_cache import audit_run_caches

    payload = logs('Cache key: k\nFound cache for key: k\n')
    first = Mock(status_code=503 if error_kind == 'server' else 200)
    error = {
        'chunked': requests.exceptions.ChunkedEncodingError,
        'timeout': requests.Timeout,
        'connection': requests.ConnectionError,
        'server': requests.ConnectionError,
    }[error_kind]
    def interrupted(**kwargs):
        yield b'partial must be discarded'
        raise error('transient')
    first.iter_content.side_effect = interrupted
    second = Mock(status_code=200)
    second.iter_content.return_value = iter([payload])
    client = SimpleNamespace(_token='secret', session=Mock())
    client.session.get.side_effect = [first, second]
    audit = audit_run_caches(client, 'owner', 'repo', 1, tmp_path)
    assert audit['archive_sha256'] == hashlib.sha256(payload).hexdigest()
    assert audit['jobs']['tests']['status'] == 'exact_hit'
    assert client.session.get.call_count == 2
    first.close.assert_called_once()
    second.close.assert_called_once()


def test_archive_retry_is_bounded_and_does_not_retry_permission_failures(tmp_path):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from ci_agent.experiments.live_cache import _archive_audit

    for status, attempts in [(503, 3), (403, 1)]:
        response = Mock(status_code=status)
        client = SimpleNamespace(_token='secret', session=Mock())
        client.session.get.return_value = response
        with pytest.raises(ValueError, match=f'HTTP {status}'):
            _archive_audit(client, 'owner', 'repo', 1)
        assert client.session.get.call_count == attempts
        assert response.close.call_count == attempts
        assert not (tmp_path / 'cache-1.json').exists()


def test_fallback_records_every_job_and_never_fabricates_archive_hash(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    import requests

    from ci_agent.experiments import live_cache

    monkeypatch.setattr(live_cache, '_archive_audit', Mock(side_effect=requests.ConnectionError()))
    client = SimpleNamespace(_token='secret', session=Mock(), run_jobs=Mock(return_value=[{'id': 1, 'name': 'lint'}, {'id': 2, 'name': 'tests (ruby 3.2)'}]))
    def response_for(url, **kwargs):
        response = Mock(status_code=200)
        response.iter_content.return_value = iter([b'Cache key: k\nFound cache for key: k\n'])
        return response
    client.session.get.side_effect = response_for
    audit = live_cache.audit_run_caches(client, 'owner', 'repo', 9, tmp_path)
    assert audit['source_kind'] == 'per_job_logs'
    assert 'archive_sha256' not in audit
    assert set(audit['jobs']) == {'lint', 'tests (ruby 3.2)'}
    assert live_cache.compare_pair_caches(audit, audit, 2)['matched']
    assert not live_cache.compare_pair_caches(audit, audit, 3)['matched']


def test_fallback_missing_job_log_never_saves_partial_audit(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    import requests

    from ci_agent.experiments import live_cache

    monkeypatch.setattr(live_cache, '_archive_audit', Mock(side_effect=requests.ConnectionError()))
    client = SimpleNamespace(_token='secret', session=Mock(), run_jobs=Mock(return_value=[{'id': 1, 'name': 'tests'}]))
    client.session.get.return_value = Mock(status_code=404)
    with pytest.raises(ValueError, match='Job log unavailable'):
        live_cache.audit_run_caches(client, 'owner', 'repo', 9, tmp_path)
    assert not (tmp_path / 'cache-9.json').exists()
