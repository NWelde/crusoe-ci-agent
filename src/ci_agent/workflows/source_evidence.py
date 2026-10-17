"""Bounded source snapshots pinned to the exact Git commit under analysis."""

import hashlib
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ci_agent.github.fork_experiment import _content_text

SUFFIXES = {
    ".json",
    ".toml",
    ".cfg",
    ".ini",
    ".py",
    ".js",
    ".cjs",
    ".mjs",
    ".ts",
    ".tsx",
    ".sh",
    ".bash",
    ".yml",
    ".yaml",
    ".go",
    ".rs",
    ".rb",
    ".java",
    ".cs",
    ".xml",
}
NAMES = {"Makefile", "Dockerfile", "Gemfile", "Rakefile", "gradlew"}
MAX_FILES = 250
MAX_BYTES = 1_000_000


def relevant(path):
    return (
        not any(
            part in {"node_modules", "vendor", ".git", "dist", "build", ".venv"}
            for part in path.split("/")
        )
        and not Path(path).name.startswith(".env")
        and (
            Path(path).suffix in SUFFIXES
            or Path(path).name in NAMES
            or (Path(path).name.startswith("requirements") and path.endswith(".txt"))
        )
        and not path.endswith(("package-lock.json", "yarn.lock", "pnpm-lock.yaml"))
    )


def git_blob_sha(content):
    data = content.encode("utf-8")
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def collect_sources(client, repository, revision):
    """Read source as data only; bounded omissions forbid whole-source proofs."""
    owner, name = repository.split("/")
    tree = client._get(f"/repos/{owner}/{name}/git/trees/{revision}", params={"recursive": "1"})
    if not isinstance(tree.get("tree"), list):
        return {
            "revision": revision,
            "files": {},
            "complete": False,
            "reason": "Source inventory unavailable",
        }
    entries = [
        item for item in tree["tree"] if item.get("type") == "blob" and relevant(item["path"])
    ]
    total = sum(item.get("size", MAX_BYTES + 1) for item in entries)
    special = any(
        item.get("type") == "commit" or item.get("mode") == "120000" for item in tree["tree"]
    )
    complete = (
        not tree.get("truncated")
        and not special
        and len(entries) <= MAX_FILES
        and total <= MAX_BYTES
    )
    # Always prioritize manifests and directly inspectable scripts on large repositories.
    entries.sort(
        key=lambda item: (
            Path(item["path"]).name
            not in ("package.json", "pyproject.toml", "setup.py", "setup.cfg"),
            item["path"],
        )
    )
    selected, size = [], 0
    for item in entries:
        if len(selected) >= MAX_FILES or size + item.get("size", MAX_BYTES + 1) > MAX_BYTES:
            complete = False
            continue
        selected.append(item)
        size += item["size"]

    def fetch(item):
        content = _content_text(client.get_contents(owner, name, item["path"], revision))
        if git_blob_sha(content) != item["sha"]:
            raise ValueError(f"Source blob does not match pinned Git tree: {item['path']}")
        return item["path"], content

    with ThreadPoolExecutor(max_workers=8) as pool:
        files = dict(pool.map(fetch, selected))
    return {
        "revision": revision,
        "files": files,
        "complete": complete,
        "blob_shas": {item["path"]: item["sha"] for item in selected},
        "reason": None
        if complete
        else "Source inventory truncated or exceeds bounded analysis budget",
    }


def local_sources(root):
    root = Path(root).resolve()
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-co", "--exclude-standard", "-z"],
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        names = set(result.stdout.decode("utf-8").split("\0")) - {""}
        paths = [root / name for name in names if relevant(name) and (root / name).is_file()]
    else:
        paths = []
        for folder, dirs, names in os.walk(root):
            dirs[:] = [
                d
                for d in dirs
                if d
                not in {".git", ".venv", "node_modules", "vendor", "dist", "build", "artifacts"}
            ]
            paths.extend(
                Path(folder) / name
                for name in names
                if relevant((Path(folder) / name).relative_to(root).as_posix())
            )
    if any(not p.resolve().is_relative_to(root) for p in paths):
        raise ValueError(
            "Source symlink escapes repository; cannot certify complete local inventory"
        )
    complete = True
    files = {}
    size = 0
    paths.sort(
        key=lambda p: (
            p.name not in ("package.json", "pyproject.toml", "setup.py", "setup.cfg"),
            str(p),
        )
    )
    for path in paths:
        if len(files) >= MAX_FILES or size + path.stat().st_size > MAX_BYTES:
            complete = False
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeError, OSError):
            complete = False
            continue
        files[path.relative_to(root).as_posix()] = content
        size += len(content.encode("utf-8"))
    return {
        "revision": "LOCAL_UNCOMMITTED_ANALYSIS_ONLY",
        "complete": complete,
        "files": files,
        "reason": None
        if complete
        else "Source inventory exceeds analysis budget or contains unreadable files",
    }


def verify_sources(client, repository, revision, snapshot):
    """Recheck cached source against the immutable remote inventory before reuse."""
    if snapshot.get("revision") != revision:
        raise ValueError("Source evidence revision differs from inspected source")
    owner, name = repository.split("/")
    tree = client._get(f"/repos/{owner}/{name}/git/trees/{revision}", params={"recursive": "1"})
    if not isinstance(tree.get("tree"), list):
        if snapshot.get("complete") or snapshot.get("files"):
            raise ValueError("Pinned source inventory is unavailable for independent verification")
        return snapshot
    entries = {
        item["path"]: item
        for item in tree.get("tree", [])
        if item.get("type") == "blob" and relevant(item["path"])
    }
    files = snapshot.get("files", {})
    special = any(
        item.get("type") == "commit" or item.get("mode") == "120000" for item in tree["tree"]
    )
    if snapshot.get("complete") and (
        tree.get("truncated") or special or set(entries) != set(files)
    ):
        raise ValueError("Source evidence completeness does not match pinned tree")
    for path, content in files.items():
        if path not in entries or git_blob_sha(content) != entries[path]["sha"]:
            raise ValueError(f"Source evidence was modified or omitted from pinned tree: {path}")
    return snapshot


def proposal_source_context(snapshot):
    """Bound model context while keeping script/config evidence inspectable."""
    files = snapshot.get("files", {})
    selected = {}
    for path, content in files.items():
        if Path(path).name in (
            "package.json",
            "pyproject.toml",
            "setup.py",
            "setup.cfg",
            "action.yml",
            "action.yaml",
        ) or path.endswith((".sh", ".bash")):
            selected[path] = content
    return {
        "revision": snapshot.get("revision"),
        "complete": snapshot.get("complete", False),
        "file_sha256": {
            path: hashlib.sha256(content.encode()).hexdigest() for path, content in files.items()
        },
        "inspected_scripts_and_config": selected,
    }
