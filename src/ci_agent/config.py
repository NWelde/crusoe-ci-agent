"""Validated runtime settings with conservative experiment defaults."""

from pydantic import BaseModel, ConfigDict, Field


class AgentConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    database_path: str = "ci_agent.sqlite3"
    poll_interval_seconds: int = Field(default=60, ge=5)
    max_active_experiments: int = Field(default=1, ge=1)
    max_run_pairs_per_experiment: int = Field(default=3, ge=1)
    minimum_samples: int = Field(default=3, ge=2)
    minimum_gain_percent: float = Field(default=5.0, ge=0)
    required_checks: tuple[str, ...] = ("tests",)
    allow_fixture_runs: bool = False
