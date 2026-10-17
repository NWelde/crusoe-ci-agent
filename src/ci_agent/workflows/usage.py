"""Inspect CI commands and their local script/action closure without executing code.

Facts are scoped to a proposed edit: workspace/history/runtime consumers are
separate from deployment/lifecycle effects. Unknown commands remain unknown.
"""

import json
import posixpath
import re
import shlex
from dataclasses import dataclass, field

import yaml


@dataclass
class Usage:
    workspace: bool = False
    history: bool = False
    unsafe: bool = False
    unknown: bool = False
    runtimes: set[str] = field(default_factory=set)
    evidence: list[str] = field(default_factory=list)

    def merge(self, other):
        for name in ("workspace", "history", "unsafe", "unknown"):
            setattr(self, name, getattr(self, name) or getattr(other, name))
        self.runtimes.update(other.runtimes)
        self.evidence.extend(other.evidence)
        return self


HISTORY = re.compile(
    r"\bgit\s+(?:describe|log|diff|rev-list|show|merge-base|tag|checkout|fetch|rev-parse)|"
    r"setuptools[_-]scm|versioneer|hatch-vcs|semantic-release|gitversion|"
    r"git-describe|git-revision|git-rev-sync|simple-git|GitPython|pygit2|dulwich|from git import|"
    r"\bgit[\"\']?\s*,\s*[\"\'](?:describe|log|diff|rev-list|show|merge-base|tag|rev-parse)|"
    r"--(?:changed|since|affected)|\b(?:nx affected|lerna changed)\b",
    re.IGNORECASE,
)
EFFECT = re.compile(
    r"\b(?:deploy|publish|release|terraform|pulumi|kubectl|helm|ansible|ssh|scp|rsync)\b|"
    r"git\s+(?:push|commit)|\b(?:curl|wget)\b|https?://|"
    r"secrets\.|id-token|GITHUB_TOKEN|GH_TOKEN",
    re.IGNORECASE,
)
SAFE_ACTIONS = {
    "actions/checkout",
    "actions/setup-node",
    "actions/setup-python",
    "actions/setup-go",
    "actions/setup-java",
    "actions/cache",
    "actions/upload-artifact",
    "actions/download-artifact",
    "dtolnay/rust-toolchain",
    "swatinem/rust-cache",
    "ruby/setup-ruby",
}
SETUP_RUNTIME = {
    "actions/setup-node": "node",
    "actions/setup-python": "python",
    "actions/setup-go": "go",
    "actions/setup-java": "java",
    "ruby/setup-ruby": "ruby",
    "dtolnay/rust-toolchain": "rust",
}


def normalize(path, cwd=""):
    path = posixpath.normpath(posixpath.join(cwd, path))
    if path.startswith(("../", "/")) or path == ".." or "\\" in path or "${{" in path:
        return None
    return path.removeprefix("./")


def command_usage(command, files=None, cwd="", seen=()):
    files = files or {}
    usage = Usage(history=bool(HISTORY.search(command)), unsafe=bool(EFFECT.search(command)))
    if re.search(r"\$\(|`|\$\{\{|\beval\b|\bsource\b|\bexec\b|<<|[<>]", command):
        usage.unknown = True
    for line in re.split(r"&&|\|\||[;\n|]", command):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            tokens = shlex.split(line)
        except ValueError:
            usage.unknown = True
            continue
        if not tokens:
            continue
        executable, *args = tokens
        if executable == "cd" and len(args) == 1:
            updated = normalize(args[0], cwd)
            if updated is None:
                usage.unknown = True
            else:
                cwd = updated
            usage.workspace = True
            continue
        if (
            executable == "set"
            and args
            and all(re.fullmatch(r"-[a-zA-Z]+|pipefail", a) for a in args)
        ):
            continue
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", executable):
            usage.unknown = True
            continue
        if executable in ("echo", "printf", "true", "false", "sleep"):
            # Literal logging is just one case, not the eligibility gate.
            if executable in ("echo", "printf") and re.search(r"[$`<>|]", line):
                usage.unknown = True
            continue
        usage.workspace = True
        if executable in (
            "tsc",
            "eslint",
            "prettier",
            "jest",
            "vitest",
            "mocha",
            "ava",
            "vite",
            "webpack",
            "rollup",
            "esbuild",
            "biome",
            "xo",
            "tsd",
            "nyc",
            "c8",
            "tap",
            "standard",
        ):
            usage.runtimes.add("node")
            continue
        if executable in ("npm", "pnpm", "yarn", "npx"):
            usage.runtimes.add("node")
            manifest_path = normalize("package.json", cwd)
            manifest = files.get(manifest_path)
            if not manifest:
                usage.unknown = True
                usage.evidence.append(f"Missing {manifest_path} for {executable} command closure")
                continue
            try:
                package = json.loads(manifest)
            except (ValueError, TypeError):
                usage.unknown = True
                continue
            scripts = package.get("scripts", {})
            if executable == "npx":
                usage.merge(command_usage(" ".join(args), files, cwd, seen))
                continue
            if args[:1] == ['exec']:
                usage.merge(command_usage(' '.join(args[1:]), files, cwd, seen))
                continue
            target = (
                args[1]
                if args[:1] in (["run"], ["run-script"]) and len(args) > 1
                else (args[0] if args else "")
            )
            install = target in ("ci", "install", "i")
            hooks = (
                ["preinstall", "install", "postinstall", "prepare"]
                if install
                else [f"pre{target}", target, f"post{target}"]
            )
            if not install and target not in scripts:
                usage.unknown = True
            if install:
                # Native dependency builds can use Python and C++ underneath npm.
                usage.runtimes.update(("python", "cpp"))
            for hook in hooks:
                if hook not in scripts:
                    continue
                key = f"{manifest_path}:{hook}"
                if key in seen:
                    usage.unknown = True
                    continue
                usage.evidence.append(f"Inspected npm script {key}")
                usage.merge(command_usage(scripts[hook], files, cwd, (*seen, key)))
            continue
        if executable in (
            "python",
            "python3",
            "pytest",
            "pip",
            "pip3",
            "ruff",
            "mypy",
            "tox",
            "uv",
            "poetry",
        ):
            usage.runtimes.add("python")
            if executable in ("uv", "poetry") and args[:1] == ["run"]:
                usage.merge(command_usage(" ".join(args[1:]), files, cwd, seen))
            elif executable == "tox":
                # Tox environments can run arbitrary configured commands; it is
                # not equivalent to pytest without a resolved environment plan.
                usage.unknown = True
            # Inline arbitrary Python, custom modules and direct scripts need inspection.
            if executable.startswith("python"):
                if (
                    args[:1] == ["-m"]
                    and len(args) > 1
                    and args[1] in ("pytest", "pip", "unittest", "compileall", "ruff", "build")
                ):
                    pass
                elif args and args[0].endswith(".py"):
                    path = normalize(args[0], cwd)
                    source = files.get(path)
                    usage.unknown |= source is None
                    if source is not None:
                        usage.history |= bool(HISTORY.search(source))
                        usage.unsafe |= bool(EFFECT.search(source))
                        usage.evidence.append(f"Inspected Python entry point {path}")
                        # Arbitrary script behavior cannot certify no side effects.
                        usage.unknown = True
                else:
                    usage.unknown = True
            usage.history |= any(
                HISTORY.search(files.get(normalize(p, cwd), ""))
                for p in ("pyproject.toml", "setup.py", "setup.cfg")
            )
            continue
        runtime = {
            "go": "go",
            "cargo": "rust",
            "rustc": "rust",
            "javac": "java",
            "java": "java",
            "mvn": "java",
            "gradle": "java",
            "dotnet": "dotnet",
            "bundle": "ruby",
            "ruby": "ruby",
            "node": "node",
        }.get(executable)
        if runtime:
            usage.runtimes.add(runtime)
            allowed = {
                "test",
                "build",
                "check",
                "clippy",
                "fmt",
                "vet",
                "version",
                "--version",
                "install",
                "restore",
                "exec",
                "rubocop",
                "rake",
                "spec",
            }
            if executable == "node" and args[:1] == ["--test"]:
                pass
            elif executable in ("node", "ruby", "java") or not args or args[0] not in allowed:
                usage.unknown = True
            continue
        if (
            executable in ("bash", "sh")
            or executable.startswith("./")
            or executable.endswith(".sh")
        ):
            script = args[0] if executable in ("bash", "sh") and args else executable
            path = normalize(script, cwd)
            if not path or path in seen or path not in files:
                usage.unknown = True
                continue
            usage.evidence.append(f"Inspected shell script {path}")
            usage.merge(command_usage(files[path], files, cwd, (*seen, path)))
            continue
        if executable == "git":
            # Any git operation can observe history/worktree state.
            usage.history = True
        usage.unknown = True
    return usage


def action_usage(step, files=None, seen=()):
    files = files or {}
    action = step.get("uses", "").lower()
    base = action.split("@")[0]
    usage = Usage()
    if base.startswith("./"):
        paths = [normalize(base + "/" + suffix) for suffix in ("action.yml", "action.yaml")]
        path = next((p for p in paths if p in files), None)
        usage.workspace = True
        if path is None or path in seen:
            usage.unknown = True
            return usage
        try:
            definition = yaml.safe_load(files[path])
            runs = definition.get("runs", {})
            if runs.get("using") != "composite":
                usage.unknown = True
            else:
                for nested in runs.get("steps", []):
                    usage.merge(step_usage(nested, files, seen=(*seen, path)))
            usage.evidence.append(f"Inspected composite action {path}")
        except (ValueError, AttributeError, TypeError):
            usage.unknown = True
        return usage
    if base not in SAFE_ACTIONS:
        usage.unknown = True
    if base in ("actions/upload-artifact", "actions/download-artifact"):
        usage.workspace = True
    if base == "ruby/setup-ruby" and step.get("with", {}).get("bundler-cache"):
        usage.workspace = True
        usage.runtimes.add("ruby")
    values = json.dumps(step.get("with", {}))
    if "hashFiles(" in values:
        usage.workspace = True
    usage.history |= bool(HISTORY.search(values))
    usage.unsafe |= bool(EFFECT.search(values))
    return usage


def step_usage(step, files=None, cwd="", seen=()):
    if "uses" in step:
        return action_usage(step, files, seen)
    if "run" not in step:
        return Usage(unknown=True)
    if step.get("shell", "bash") not in ("bash", "sh", "pwsh", "powershell", "cmd", "python"):
        return Usage(unknown=True)
    if step.get("shell") in ("python", "pwsh", "powershell", "cmd"):
        return Usage(workspace=True, unknown=True)
    cwd = normalize(step.get("working-directory", "."), cwd)
    if cwd is None:
        return Usage(unknown=True)
    return command_usage(step["run"], files, cwd, seen)


def job_usage(job, files=None, defaults=None):
    defaults = defaults or {}
    usage = Usage()
    default_run = defaults.get("run", {}) | job.get("defaults", {}).get("run", {})
    cwd = default_run.get("working-directory", "")
    if default_run.get("shell", "bash") not in ("bash", "sh"):
        usage.unknown = True
    for step in job.get("steps", []):
        usage.merge(step_usage(step, files, cwd))
    text = json.dumps(job)
    usage.history |= bool(HISTORY.search(text))
    usage.unsafe |= bool(EFFECT.search(text))
    return usage
