from ci_agent.reporting.live_report import write_live_report


def test_stopped_report_never_claims_completed_e2e(tmp_path):
    report = {
        "status": "stopped",
        "outcome": "void",
        "reason": "Required check failed",
        "runs": [
            {
                "pair": 1,
                "variant": "baseline",
                "status": "collected",
                "run_id": 123,
                "evidence": {
                    "id": 123,
                    "html_url": "https://github.com/o/r/actions/runs/123",
                    "conclusion": "failure",
                    "jobs": [{"id": 1}],
                },
            }
        ],
        "inputs": {"common_source_files": {"lib/fix.rb": "source"}},
    }
    text = write_live_report(tmp_path, report).read_text(encoding="utf-8")
    assert "has not completed" in text
    assert "The full end-to-end measurement completed." not in text
    assert "Required check failed" in text
    assert "[123](https://github.com/o/r/actions/runs/123)" in text
    assert "lib/fix.rb" in text
    assert "applied identically" in text


def test_completed_report_contains_only_supplied_metrics_and_verification(tmp_path):
    report = {
        "status": "completed",
        "outcome": "loss",
        "pairs": [{"baseline_minutes": 10, "candidate_minutes": 11, "reduction_percent": -10}],
        "mean_reduction_percent": -10,
        "exploratory_95_percent_interval": [-20, 0],
        "verification": {
            "method": "independent raw-evidence recomputation",
            "distinct_runs": 6,
            "jobs_per_run": 187,
            "runner_labels_verified": True,
            "limitations": ["Host load is uncontrolled."],
        },
    }
    text = write_live_report(tmp_path, report).read_text(encoding="utf-8")
    assert "Outcome: **loss**" in text
    assert "**-10.00%**" in text
    assert "187" in text
    assert "Host load is uncontrolled." in text
    assert "do not establish statistical certainty" in text


def test_preflight_empty_report_is_writable(tmp_path):
    text = write_live_report(tmp_path, {"status": "preflight"}).read_text(encoding="utf-8")
    assert "partial execution evidence" in text


def test_failed_checks_show_job_and_steps_without_claiming_success(tmp_path):
    report = {
        "status": "stopped",
        "outcome": "void",
        "failed_checks": [
            {
                "job_id": 123,
                "name": "Active Record on JRuby",
                "conclusion": "failure",
                "failed_steps": [{"name": "Run bundle exec rake spec", "conclusion": "failure"}],
            },
            {
                "job_id": 456,
                "name": "Another check",
                "conclusion": "failure",
                "failed_steps": ["Run specs"],
            },
        ],
    }
    text = write_live_report(tmp_path, report).read_text(encoding="utf-8")
    assert "Failed required checks" in text
    assert "Active Record on JRuby (job 123): **failure**" in text
    assert "Run bundle exec rake spec" in text
    assert "Run specs" in text
    assert "cannot be published as a verified win" in text
    assert "The full end-to-end measurement completed." not in text
