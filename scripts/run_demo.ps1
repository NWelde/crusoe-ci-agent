param(
    [string]$Target = "demo_target",
    [string]$Output = "artifacts/bro-15-integration"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$TargetPath = (Resolve-Path (Join-Path $Root $Target)).Path
$ExpectedRevision = "12d057cbe2da23ac87368266504681ff1ce62e0b"
$ActualRevision = (git -C $TargetPath rev-parse HEAD).Trim()
if ($ActualRevision -ne $ExpectedRevision) {
    throw "Demo target must be at $ExpectedRevision; found $ActualRevision"
}

$ReportPath = Join-Path $Root $Output
New-Item -ItemType Directory -Path $ReportPath -Force | Out-Null
$StartedAt = [DateTime]::UtcNow.ToString("o")
$Results = [System.Collections.Generic.List[object]]::new()

function Add-CheckResult([string]$Name, [scriptblock]$Action) {
    $Started = [DateTime]::UtcNow
    try {
        $OutputText = (& $Action 2>&1 | Out-String).Trim()
        $ExitCode = $LASTEXITCODE
        if ($null -eq $ExitCode) { $ExitCode = 0 }
        $Results.Add([ordered]@{
            name = $Name; status = $(if ($ExitCode -eq 0) { "passed" } else { "failed" })
            exit_code = $ExitCode; started_at = $Started.ToString("o")
            duration_seconds = [Math]::Round(([DateTime]::UtcNow - $Started).TotalSeconds, 3)
            output = $OutputText
        })
        if ($ExitCode -ne 0) { throw "$Name failed with exit code $ExitCode`n$OutputText" }
    } catch {
        if (-not ($Results | Where-Object name -eq $Name)) {
            $Results.Add([ordered]@{ name = $Name; status = "failed"; output = $_.Exception.Message })
        }
        throw
    }
}

function Test-Patch([string]$PatchName, [bool]$ShouldApply, [string]$ExpectedReason) {
    $PatchPath = Join-Path $Root "tests/fixtures/demo_target/patches/$PatchName"
    $Worktree = Join-Path ([IO.Path]::GetTempPath()) ("bro15-" + [guid]::NewGuid().ToString("N"))
    try {
        git -C $TargetPath worktree add --quiet --detach $Worktree $ExpectedRevision
        if ($LASTEXITCODE -ne 0) { throw "Could not create isolated target worktree" }
        $PatchOutput = git -C $Worktree apply --ignore-whitespace $PatchPath 2>&1
        if ($LASTEXITCODE -ne 0) { throw "Patch did not apply to pinned baseline: $PatchName`n$PatchOutput" }

        $Workflow = Get-Content (Join-Path $Worktree ".github/workflows/ci.yml") -Raw
        $WorkflowOnly = @(git -C $Worktree diff --name-only)
        $Issues = [System.Collections.Generic.List[string]]::new()
        if ($Workflow -notmatch "(?m)^\s*name:\s*tests\s*$" -or
            $Workflow -notmatch "(?m)^\s*run:\s*python -m pytest -q\s*$") {
            $Issues.Add("required_check_removed")
        }
        if (@($WorkflowOnly | Where-Object { $_ -ne ".github/workflows/ci.yml" }).Count -gt 0) {
            $Issues.Add("out_of_scope_paths_changed")
        }
        if ($ShouldApply -and $Issues.Count -gt 0) {
            throw "Legitimate patch violated acceptance rules: $($Issues -join ', ')"
        }
        if (-not $ShouldApply -and $ExpectedReason -notin $Issues) {
            throw "Expected rejection reason '$ExpectedReason' for ${PatchName}; observed: $($Issues -join ', ')"
        }
        return [ordered]@{
            fixture = $PatchName; expected_eligible = $ShouldApply
            observed_eligible = ($Issues.Count -eq 0); rejection_reasons = @($Issues)
            output = "Patch applied to disposable worktree at $ExpectedRevision; required-check and path rules evaluated."
        }
    } finally {
        git -C $TargetPath worktree remove --force $Worktree 2>$null | Out-Null
    }
}

$Checklist = @(
    "Target is pinned to a verified baseline commit.",
    "Required test check and command remain present for candidate changes.",
    "Cache patch is eligible for measurement but has no claimed performance gain.",
    "Shortcut and out-of-scope patches are rejected by acceptance checks.",
    "Mismatched run revisions are expected void and must never create a PR; evaluator is not implemented.",
    "Required-check failure stop is replayed; loss, invalid comparison, inconclusive and exhausted budgets remain unimplemented.",
    "Restart/resume duplicate prevention remains unimplemented.",
    "Human-reviewed PR publication gate is not implemented; no PR or automatic merge path exists."
)

$Fixtures = [System.Collections.Generic.List[object]]::new()
$Status = "passed"
$Failure = $null
try {
    Add-CheckResult "pinned_target" { git -C $TargetPath rev-parse HEAD }
    Add-CheckResult "target_workflow_check" {
        $Workflow = Get-Content (Join-Path $TargetPath ".github/workflows/ci.yml") -Raw
        if ($Workflow -notmatch "(?m)^\s*name:\s*tests\s*$" -or
            $Workflow -notmatch "(?m)^\s*run:\s*python -m pytest -q\s*$") {
            throw "Required tests check or command is missing"
        }
        "Required check 'tests' runs python -m pytest -q"
    }
    Add-CheckResult "target_locked_test_suite" {
        Push-Location $TargetPath
        try { uv run --locked --extra test python -m pytest -q } finally { Pop-Location }
    }
    Add-CheckResult "legitimate_cache_patch" { $script:Fixtures.Add((Test-Patch "cache-pip.patch" $true "")); "eligible" }
    Add-CheckResult "shortcut_patch_rejection" { $script:Fixtures.Add((Test-Patch "remove-tests.patch" $false "required_check_removed")); "rejected: required check removed" }
    Add-CheckResult "out_of_scope_patch_rejection" { $script:Fixtures.Add((Test-Patch "out-of-scope.patch" $false "out_of_scope_paths_changed")); "rejected: changed source path outside allowlist" }
    Add-CheckResult "mismatched_revision_void_gate" {
        $Run = Get-Content (Join-Path $Root "tests/fixtures/demo_target/mismatched-run.json") -Raw | ConvertFrom-Json
        if ($Run.baseline.source_revision -eq $Run.candidate.source_revision -or
            $Run.expected_evaluation.outcome -ne "void" -or
            -not $Run.fixture_label.StartsWith("SUPPLIED EXAMPLE DATA")) {
            throw "Mismatched run fixture does not satisfy its expected void gate"
        }
        "Fixture metadata is supplied example data and incompatible revisions must be void."
    }
    Add-CheckResult "simulated_cli_integration" {
        uv run --directory $Root ci-agent demo-loop --output (Join-Path $ReportPath "simulated-success")
    }
    Add-CheckResult "simulated_required_check_stop" {
        uv run --directory $Root ci-agent demo-loop --fail-check --output (Join-Path $ReportPath "simulated-required-check-failure")
    }
} catch {
    $Status = "failed"
    $Failure = $_.Exception.Message
}

$Report = [ordered]@{
    report_version = 1; status = $Status; evidence_class = "LOCAL_REPLAY_AND_TARGET_CHECKS"
    started_at = $StartedAt; finished_at = [DateTime]::UtcNow.ToString("o")
    repository = "madeintandem/jsonb_accessor"; target_revision = $ActualRevision
    target_workflow = ".github/workflows/ci.yml"; required_checks = @(@{ name = "tests"; command = "python -m pytest -q" })
    no_github_actions_dispatched = $true; no_pull_request_created = $true
    no_live_performance_claim = $true; acceptance_checklist = $Checklist
    fixtures = $Fixtures; checks = $Results; failure = $Failure
    unimplemented_or_unverified = @(
        "No GitHub Actions workflow was dispatched, so no real run IDs or runner-minute comparisons exist.",
        "No PR publication or durable experiment state machine is implemented in this workspace yet.",
        "Regression, run-pair exhaustion, time-budget exhaustion, and restart/resume duplication gates are not wired end to end."
    )
}
$script:ReportsPath = $ReportPath
$JsonPath = Join-Path $ReportPath "report.json"
$MarkdownPath = Join-Path $ReportPath "report.md"
$Report | ConvertTo-Json -Depth 12 | Set-Content -Encoding utf8 $JsonPath
$Lines = @("# BRO-15 full-loop integration report", "", "> LOCAL REPLAY AND TARGET CHECKS; not live GitHub evidence.", "", "- Status: **$Status**", "- Target: ``madeintandem/jsonb_accessor@$ActualRevision``", "- Required check: ``tests`` (``python -m pytest -q``)", "- GitHub Actions dispatched: **No**", "- Pull request created: **No**", "- Live performance claim: **None**", "", "## Acceptance checklist", "")
$Lines += $Checklist | ForEach-Object { "- [ ] $_" }
$Lines += @("", "## Checks", "")
$Lines += $Results | ForEach-Object { "- **$($_.name): $($_.status)** — $($_.output -replace '\s+', ' ' -replace '\|', '\|')" }
$Lines += @("", "## Remaining gaps", "")
$Lines += $Report.unimplemented_or_unverified | ForEach-Object { "- $_" }
Set-Content -Encoding utf8 -Path $MarkdownPath -Value ($Lines -join "`n")
Write-Output "JSON report: $JsonPath"
Write-Output "Markdown report: $MarkdownPath"
if ($Status -ne "passed") { throw $Failure }
