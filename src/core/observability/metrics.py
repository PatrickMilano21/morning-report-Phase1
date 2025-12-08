# src/core/observability/metrics.py
"""
Metrics collection for tracking LLM costs, timing, and session performance.

Usage:
    from src.core.observability.metrics import get_metrics_collector

    # Record metrics after each session
    collector = get_metrics_collector()
    collector.record_session(
        source_name="YahooQuote",
        ticker="AAPL",
        stagehand=stagehand,  # Before close()
        session_id=stagehand.session_id,
        duration_sec=elapsed_time,
        success=True
    )

    # At end of pipeline
    collector.save_run_metrics("000_baseline")
"""

import json
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any


@dataclass
class SessionMetrics:
    """Metrics for a single Stagehand session."""
    source_name: str
    ticker: Optional[str]
    session_id: str
    duration_sec: float
    success: bool
    error: Optional[str] = None

    # LLM token metrics (from stagehand.metrics)
    act_prompt_tokens: int = 0
    act_completion_tokens: int = 0
    extract_prompt_tokens: int = 0
    extract_completion_tokens: int = 0
    observe_prompt_tokens: int = 0
    observe_completion_tokens: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_cached_tokens: int = 0
    total_inference_time_ms: int = 0

    # Browserbase session info
    region: Optional[str] = None
    proxy_bytes: int = 0


@dataclass
class RunMetrics:
    """Aggregated metrics for a full pipeline run."""
    run_id: str
    timestamp: str
    sessions: List[SessionMetrics] = field(default_factory=list)

    # Computed totals
    total_sessions: int = 0
    success_count: int = 0
    error_count: int = 0

    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_cached_tokens: int = 0
    total_inference_time_ms: int = 0

    total_duration_sec: float = 0
    total_browser_minutes: float = 0


class MetricsCollector:
    """Singleton collector for aggregating metrics across sessions."""

    _instance: Optional['MetricsCollector'] = None

    def __init__(self):
        self.run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.start_time = time.time()
        self.sessions: List[SessionMetrics] = []
        self.metrics_dir = Path("data/metrics")
        self.metrics_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def get_instance(cls) -> 'MetricsCollector':
        """Get or create the singleton instance."""
        if cls._instance is None:
            cls._instance = MetricsCollector()
        return cls._instance

    @classmethod
    def reset(cls):
        """Reset the singleton (for new runs)."""
        cls._instance = None

    def record_session(
        self,
        source_name: str,
        ticker: Optional[str],
        stagehand: Any,  # Stagehand instance
        session_id: str,
        duration_sec: float,
        success: bool,
        error: Optional[str] = None,
    ):
        """Record metrics from a completed session.

        Call this BEFORE stagehand.close() to capture metrics.
        """
        metrics = SessionMetrics(
            source_name=source_name,
            ticker=ticker,
            session_id=session_id,
            duration_sec=duration_sec,
            success=success,
            error=error,
        )

        # Extract LLM metrics from stagehand if available
        try:
            if hasattr(stagehand, 'metrics') and stagehand.metrics:
                sm = stagehand.metrics
                metrics.act_prompt_tokens = getattr(sm, 'actPromptTokens', 0) or 0
                metrics.act_completion_tokens = getattr(sm, 'actCompletionTokens', 0) or 0
                metrics.extract_prompt_tokens = getattr(sm, 'extractPromptTokens', 0) or 0
                metrics.extract_completion_tokens = getattr(sm, 'extractCompletionTokens', 0) or 0
                metrics.observe_prompt_tokens = getattr(sm, 'observePromptTokens', 0) or 0
                metrics.observe_completion_tokens = getattr(sm, 'observeCompletionTokens', 0) or 0
                metrics.total_prompt_tokens = getattr(sm, 'totalPromptTokens', 0) or 0
                metrics.total_completion_tokens = getattr(sm, 'totalCompletionTokens', 0) or 0
                metrics.total_cached_tokens = getattr(sm, 'totalCachedInputTokens', 0) or 0
                metrics.total_inference_time_ms = getattr(sm, 'totalInferenceTimeMs', 0) or 0
        except Exception as e:
            print(f"[MetricsCollector] Warning: Could not extract LLM metrics: {e}")

        # Extract session info if available
        try:
            if hasattr(stagehand, 'session_id'):
                metrics.session_id = stagehand.session_id
        except Exception:
            pass

        self.sessions.append(metrics)

        # Log metrics inline
        tokens = metrics.total_prompt_tokens + metrics.total_completion_tokens
        if tokens > 0:
            print(f"[Metrics] {source_name}/{ticker}: {tokens} tokens, {duration_sec:.1f}s")

    def get_run_metrics(self) -> RunMetrics:
        """Aggregate all session metrics into a run summary."""
        run = RunMetrics(
            run_id=self.run_id,
            timestamp=datetime.now().isoformat(),
            sessions=self.sessions,
            total_sessions=len(self.sessions),
            success_count=sum(1 for s in self.sessions if s.success),
            error_count=sum(1 for s in self.sessions if not s.success),
        )

        # Aggregate token counts
        for s in self.sessions:
            run.total_prompt_tokens += s.total_prompt_tokens
            run.total_completion_tokens += s.total_completion_tokens
            run.total_cached_tokens += s.total_cached_tokens
            run.total_inference_time_ms += s.total_inference_time_ms
            run.total_duration_sec += s.duration_sec

        run.total_browser_minutes = run.total_duration_sec / 60

        return run

    def save_run_metrics(self, step_name: str = None) -> Path:
        """Save run metrics to JSON file.

        Args:
            step_name: Optional name for the metrics file (e.g., "000_baseline", "001_verbose_0")
        """
        run = self.get_run_metrics()

        # Build output data
        data = {
            "run_id": run.run_id,
            "timestamp": run.timestamp,
            "summary": {
                "total_sessions": run.total_sessions,
                "success_count": run.success_count,
                "error_count": run.error_count,
                "success_rate": run.success_count / run.total_sessions if run.total_sessions > 0 else 0,
            },
            "llm_costs": {
                "total_prompt_tokens": run.total_prompt_tokens,
                "total_completion_tokens": run.total_completion_tokens,
                "total_tokens": run.total_prompt_tokens + run.total_completion_tokens,
                "total_cached_tokens": run.total_cached_tokens,
                "total_inference_time_ms": run.total_inference_time_ms,
            },
            "timing": {
                "total_duration_sec": run.total_duration_sec,
                "total_browser_minutes": run.total_browser_minutes,
                "avg_session_duration_sec": run.total_duration_sec / run.total_sessions if run.total_sessions > 0 else 0,
            },
            "per_session": [asdict(s) for s in run.sessions],
        }

        # Aggregate by source
        by_source: Dict[str, Dict] = {}
        for s in run.sessions:
            if s.source_name not in by_source:
                by_source[s.source_name] = {
                    "count": 0,
                    "success_count": 0,
                    "total_tokens": 0,
                    "total_duration_sec": 0,
                }
            by_source[s.source_name]["count"] += 1
            if s.success:
                by_source[s.source_name]["success_count"] += 1
            by_source[s.source_name]["total_tokens"] += s.total_prompt_tokens + s.total_completion_tokens
            by_source[s.source_name]["total_duration_sec"] += s.duration_sec

        data["by_source"] = by_source

        # Determine filename
        if step_name:
            filename = f"{step_name}.json"
        else:
            filename = f"run_{run.run_id}.json"

        filepath = self.metrics_dir / filename
        filepath.write_text(json.dumps(data, indent=2))

        print(f"\n[Metrics] Saved to: {filepath}")
        print(f"  Total tokens: {run.total_prompt_tokens + run.total_completion_tokens}")
        print(f"  Total duration: {run.total_duration_sec:.1f}s ({run.total_browser_minutes:.2f} min)")
        print(f"  Success rate: {run.success_count}/{run.total_sessions}")

        return filepath

    def print_summary(self):
        """Print a summary of collected metrics."""
        run = self.get_run_metrics()

        print("\n" + "="*60)
        print("                    METRICS SUMMARY")
        print("="*60)
        print(f"Run ID: {run.run_id}")
        print(f"Sessions: {run.total_sessions} ({run.success_count} success, {run.error_count} errors)")
        print(f"\nLLM COSTS:")
        print(f"  Prompt tokens:     {run.total_prompt_tokens:,}")
        print(f"  Completion tokens: {run.total_completion_tokens:,}")
        print(f"  Cached tokens:     {run.total_cached_tokens:,}")
        print(f"  Total tokens:      {run.total_prompt_tokens + run.total_completion_tokens:,}")
        print(f"  Inference time:    {run.total_inference_time_ms:,}ms")
        print(f"\nTIMING:")
        print(f"  Total duration:    {run.total_duration_sec:.1f}s ({run.total_browser_minutes:.2f} min)")
        print(f"  Avg per session:   {run.total_duration_sec / run.total_sessions:.1f}s" if run.total_sessions > 0 else "  Avg per session:   N/A")
        print("="*60)


def get_metrics_collector() -> MetricsCollector:
    """Get the global metrics collector instance."""
    return MetricsCollector.get_instance()


def reset_metrics_collector():
    """Reset the metrics collector for a new run."""
    MetricsCollector.reset()
