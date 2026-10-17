import base64
from unittest.mock import Mock

import pytest

from ci_agent.workflows.source_evidence import (
    collect_sources,
    git_blob_sha,
    local_sources,
    verify_sources,
)


def client_for(files, *, truncated=False):
    client = Mock()
    client._get.return_value = {
        "truncated": truncated,
        "tree": [
            {
                "type": "blob",
                "path": path,
                "sha": git_blob_sha(content),
                "size": len(content.encode()),
            }
            for path, content in files.items()
        ],
    }
    client.get_contents.side_effect = lambda owner, name, path, revision: {
        "encoding": "base64",
        "content": base64.b64encode(files[path].encode()).decode(),
    }
    return client


def test_pinned_sources_are_verified_and_cached_without_refetching_blobs():
    client = client_for(
        {"package.json": '{"scripts": {"test": "node --test"}}', "tests/test_x.py": "assert 1"}
    )
    snapshot = collect_sources(client, "owner/repo", "commit-sha")
    assert snapshot["complete"]
    assert all(call.args[-1] == "commit-sha" for call in client.get_contents.call_args_list)
    reads = client.get_contents.call_count
    verify_sources(client, "owner/repo", "commit-sha", snapshot)
    assert client.get_contents.call_count == reads


@pytest.mark.parametrize("mutation", ["contents", "omission", "revision"])
def test_source_tampering_is_rejected_before_reuse(mutation):
    client = client_for({"package.json": '{"scripts":{"test":"node --test"}}'})
    snapshot = collect_sources(client, "owner/repo", "original")
    if mutation == "contents":
        snapshot["files"]["package.json"] = '{"scripts":{"test":"deploy"}}'
    elif mutation == "omission":
        snapshot["files"] = {}
    else:
        snapshot["revision"] = "different"
    with pytest.raises(ValueError):
        verify_sources(client, "owner/repo", "original", snapshot)


def test_fetch_rejects_mismatched_blob_and_marks_truncated_inventory_incomplete():
    client = client_for({"setup.py": "print(1)"}, truncated=True)
    assert not collect_sources(client, "owner/repo", "sha")["complete"]
    client._get.return_value["tree"][0]["sha"] = "wrong"
    with pytest.raises(ValueError, match="pinned Git tree"):
        collect_sources(client, "owner/repo", "sha")


def test_submodule_and_symlink_inventory_cannot_certify_complete_source():
    client = client_for({"package.json": "{}"})
    client._get.return_value["tree"].append({"type": "commit", "path": "library", "mode": "160000"})
    assert not collect_sources(client, "owner/repo", "sha")["complete"]


def test_local_analysis_excludes_credentials_and_generated_dependency_trees(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    (tmp_path / ".env").write_text("SECRET=never-read")
    dependency = tmp_path / "node_modules" / "something"
    dependency.mkdir(parents=True)
    (dependency / "package.json").write_text("{}")
    snapshot = local_sources(tmp_path)
    assert snapshot["files"] == {"package.json": "{}"}
