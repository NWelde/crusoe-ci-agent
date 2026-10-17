"""Fail-closed cache observations from bounded, unextracted GitHub log archives."""

import hashlib
import io
import json
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

LIMIT = 100 * 1024 * 1024


class ArchiveUnavailable(ValueError):
    """A retryable archive service failure exhausted its attempts."""


def parse_cache_archive(payload):
    """Observe explicit restore evidence; bundle install alone never means cold."""
    if len(payload) > LIMIT:
        raise ValueError("Compressed log archive exceeds size cap")
    result = {}
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        if sum(info.file_size for info in archive.infolist()) > LIMIT:
            raise ValueError("Expanded log archive exceeds size cap")
        for info in archive.infolist():
            if "/" not in info.filename or "ruby_setup-ruby" not in info.filename:
                continue
            text = archive.read(info).decode("utf-8", errors="replace")
            job = info.filename.split("/", 1)[0]
            if job in result:
                raise ValueError("Ambiguous per-job cache log evidence")
            result[job] = dict(parse_job_cache_text(text), archive_member=info.filename)
    return result


def _archive_audit(client, owner, repo, run_id):
    """Download with a hard resource cap; persist hashes and observations only."""
    for attempt in range(3):
        response = None
        data = bytearray()
        try:
            response = client.session.get(
                f"https://api.github.com/repos/{owner}/{repo}/actions/runs/{run_id}/logs",
                headers={
                    "Authorization": f"Bearer {client._token}",
                    "Accept": "application/vnd.github+json",
                },
                stream=True,
                timeout=60,
            )
            if 500 <= response.status_code < 600 and attempt < 2:
                continue
            if 500 <= response.status_code < 600:
                raise ArchiveUnavailable(f"GitHub archive unavailable (HTTP {response.status_code})")
            if response.status_code != 200:
                raise ValueError(f"GitHub run log archive unavailable (HTTP {response.status_code})")
            for chunk in response.iter_content(chunk_size=65536):
                data.extend(chunk)
                if len(data) > LIMIT:
                    raise ValueError("Log archive download exceeds size cap")
            break
        except (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError):
            if attempt == 2:
                raise
        finally:
            if response is not None:
                response.close()
    audit = {
        "run_id": run_id,
        "archive_sha256": hashlib.sha256(data).hexdigest(),
        "jobs": parse_cache_archive(bytes(data)),
    }
    return audit


def parse_job_cache_text(text):
    """Only classify explicit single-key cache restore evidence."""
    requested = re.findall(r"Cache key: ([^\r\n]+)", text)
    found = re.findall(r"Found cache for key: ([^\r\n]+)", text)
    if len(requested) != 1 or len(found) > 1:
        raise ValueError("Ambiguous per-job cache log evidence")
    status = "unknown"
    if found:
        status = "exact_hit" if found[0] == requested[0] else "partial_hit"
    elif re.search(r"Cache not found for (?:input )?keys", text, flags=re.IGNORECASE):
        status = "miss"
    return {
        "status": status,
        "requested_key_sha256": hashlib.sha256(requested[0].encode()).hexdigest(),
        "restored_key_sha256": hashlib.sha256(found[0].encode()).hexdigest() if found else None,
        "log_sha256": hashlib.sha256(text.encode()).hexdigest(),
    }


def _job_log_audit(client, owner, repo, run_id):
    jobs = client.run_jobs(owner, repo, run_id)
    if not jobs or len({job["name"] for job in jobs}) != len(jobs):
        raise ValueError("Job metadata missing or ambiguous")
    def read_job(job):
        url = f"https://api.github.com/repos/{owner}/{repo}/actions/jobs/{int(job['id'])}/logs"
        for attempt in range(3):
            response = None
            data = bytearray()
            try:
                response = client.session.get(
                    url, headers={"Authorization": f"Bearer {client._token}"},
                    stream=True, timeout=30,
                )
                if 500 <= response.status_code < 600 and attempt < 2:
                    continue
                if response.status_code != 200:
                    raise ValueError(f"Job log unavailable (HTTP {response.status_code})")
                for chunk in response.iter_content(chunk_size=65536):
                    data.extend(chunk)
                    if len(data) > 2 * 1024 * 1024:
                        raise ValueError("Job log exceeds size cap")
                parsed = parse_job_cache_text(data.decode("utf-8", errors="replace"))
                return job["name"], dict(parsed, log_url=url), len(data)
            except (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError):
                if attempt == 2:
                    raise
            finally:
                if response is not None:
                    response.close()
    observed = {}
    total = 0
    with ThreadPoolExecutor(max_workers=6) as pool:
        for name, evidence, size in pool.map(read_job, jobs):
            total += size
            if total > LIMIT:
                raise ValueError("Combined job logs exceed size cap")
            observed[name] = evidence
    return {"run_id": run_id, "source_kind": "per_job_logs", "jobs": observed}


def audit_run_caches(client, owner, repo, run_id, output):
    """Audit a complete archive, falling back to bounded individual job logs."""
    try:
        audit = _archive_audit(client, owner, repo, run_id)
    except (ArchiveUnavailable, requests.ConnectionError, requests.Timeout,
            requests.exceptions.ChunkedEncodingError):
        audit = _job_log_audit(client, owner, repo, run_id)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / f"cache-{run_id}.json").write_text(
        json.dumps(audit, indent=2) + "\n", encoding="utf-8"
    )
    return audit


def compare_pair_caches(baseline, candidate, expected_jobs):
    """Require every job's explicit cache state and actual restored keys to match."""
    before, after = baseline.get("jobs", {}), candidate.get("jobs", {})
    if len(before) != expected_jobs or set(before) != set(after):
        return {"matched": False, "reason": "Cache log coverage incomplete or differs"}
    fields = ("status", "requested_key_sha256", "restored_key_sha256")
    for job in before:
        if before[job]["status"] == "unknown" or any(
            before[job][field] != after[job][field] for field in fields
        ):
            return {"matched": False, "reason": "Cache state unknown or unmatched", "job": job}
    return {
        "matched": True,
        "jobs": len(before),
        "baseline_run_id": baseline["run_id"],
        "candidate_run_id": candidate["run_id"],
    }
