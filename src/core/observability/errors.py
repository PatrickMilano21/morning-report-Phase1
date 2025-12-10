"""Error tracking focused on identifying what went wrong and which files/components failed."""

import json
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any


class ErrorTracker:
    """
    High-level error tracker that identifies:
    - What component failed (file/function)
    - What went wrong (error type and message)
    - Context (ticker, source, etc.)
    
    Creates summary files that are easy for humans and LLMs to understand.
    """
    
    def __init__(self):
        self.errors: List[Dict[str, Any]] = []
        self.errors_dir = Path("data/errors")
        self.errors_dir.mkdir(parents=True, exist_ok=True)
        self.today = datetime.now().strftime("%Y-%m-%d")
        # Clear old error files when a new tracker is created (fresh start for each run)
        self._clear_old_errors()

    def _clear_old_errors(self):
        """Delete all existing error files to start fresh for this run."""
        if not self.errors_dir.exists():
            return

        deleted_count = 0
        for file in self.errors_dir.iterdir():
            if file.is_file() and file.suffix in (".json", ".jsonl", ".txt"):
                try:
                    file.unlink()
                    deleted_count += 1
                except Exception as e:
                    print(f"[ErrorTracker] Could not delete {file.name}: {e}")

        if deleted_count > 0:
            print(f"[ErrorTracker] Cleared {deleted_count} old error file(s)")
    
    def record_error(
        self,
        error: Exception,
        component: str,  # e.g., "YahooQuote", "fetch_google_news_stories", "process_ticker"
        context: Optional[Dict[str, Any]] = None,
        diagnostics: Optional[Dict[str, Any]] = None,
        failure_point: Optional[str] = None,
        session_id: Optional[str] = None,
    ):
        """
        Record an error with component identification and diagnostics.

        Args:
            error: The exception that occurred
            component: Which component failed (file/function name)
            context: Additional context (ticker, source, etc.)
            diagnostics: Diagnostic information (page URL, timing, etc.)
            failure_point: Which stage failed (e.g., "navigation", "extraction", "session_creation")
            session_id: Browserbase session ID for debugging via Session Inspector
        """
        # Build session URL for easy debugging access
        session_url = None
        if session_id:
            session_url = f"https://www.browserbase.com/sessions/{session_id}"

        error_record = {
            "timestamp": datetime.utcnow().isoformat(),
            "component": component,  # Which file/component failed
            "error_type": type(error).__name__,
            "error_message": str(error),
            "context": context or {},
            "failure_point": failure_point,  # Which stage failed
            "diagnostics": diagnostics or {},  # Diagnostic information
            "session_id": session_id,  # Browserbase session ID
            "session_url": session_url,  # Direct link to Session Inspector
            "traceback": self._extract_relevant_traceback(error),
        }
        
        self.errors.append(error_record)
        self._save_error(error_record)
        self._update_summary()
    
    def _extract_relevant_traceback(self, error: Exception) -> str:
        """Extract relevant traceback focusing on our code with file paths."""
        tb_lines = traceback.format_exception(type(error), error, error.__traceback__)
        
        # Extract file paths and relevant stack frames
        relevant_lines = []
        for line in tb_lines:
            line = line.strip()
            # Include lines that mention our source files
            if "src/" in line or "File" in line:
                relevant_lines.append(line)
        
        # If no relevant lines, return full traceback
        if not relevant_lines:
            return "\n".join(tb_lines)
        
        return "\n".join(relevant_lines)
    
    def _save_error(self, error_record: Dict[str, Any]):
        """Save individual error to file."""
        error_file = (
            self.errors_dir 
            / f"error_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}_{error_record['component']}.json"
        )
        
        with open(error_file, "w") as f:
            json.dump(error_record, f, indent=2)
        
        # Also append to daily error log
        daily_log = self.errors_dir / f"errors_{self.today}.jsonl"
        with open(daily_log, "a") as f:
            f.write(json.dumps(error_record) + "\n")
    
    def _update_summary(self):
        """Create/update summary file that's easy for humans and LLMs to read."""
        summary = self.get_summary()
        
        summary_file = self.errors_dir / f"error_summary_{self.today}.json"
        with open(summary_file, "w") as f:
            json.dump(summary, f, indent=2)
        
        # Also create human-readable summary
        summary_text_file = self.errors_dir / f"error_summary_{self.today}.txt"
        with open(summary_text_file, "w") as f:
            f.write(self._format_summary_text(summary))
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary of all errors for easy consumption by LLMs."""
        if not self.errors:
            return {
                "total_errors": 0,
                "status": "no_errors",
                "message": "No errors occurred in this run.",
            }
        
        # Group errors by component
        by_component: Dict[str, List[Dict[str, Any]]] = {}
        by_error_type: Dict[str, int] = {}
        
        for error in self.errors:
            component = error["component"]
            error_type = error["error_type"]
            
            if component not in by_component:
                by_component[component] = []
            by_component[component].append(error)
            
            by_error_type[error_type] = by_error_type.get(error_type, 0) + 1
        
        # Find most common errors
        most_common_component = max(by_component.items(), key=lambda x: len(x[1]), default=(None, []))
        most_common_error_type = max(by_error_type.items(), key=lambda x: x[1], default=(None, 0))
        
        return {
            "total_errors": len(self.errors),
            "status": "errors_occurred",
            "timestamp": datetime.utcnow().isoformat(),
            "summary": {
                "errors_by_component": {
                    component: len(errors) 
                    for component, errors in by_component.items()
                },
                "errors_by_type": by_error_type,
                "most_problematic_component": {
                    "component": most_common_component[0],
                    "error_count": len(most_common_component[1]),
                } if most_common_component[0] else None,
                "most_common_error_type": {
                    "error_type": most_common_error_type[0],
                    "count": most_common_error_type[1],
                } if most_common_error_type[0] else None,
            },
            "errors": self.errors[-10:],  # Last 10 errors for context
        }
    
    def _format_summary_text(self, summary: Dict[str, Any]) -> str:
        """Format summary as human-readable text."""
        lines = [
            "=" * 60,
            "ERROR SUMMARY",
            "=" * 60,
            "",
            f"Total Errors: {summary['total_errors']}",
            f"Status: {summary['status']}",
            "",
        ]
        
        if summary["status"] == "no_errors":
            lines.append("✅ No errors occurred in this run.")
            return "\n".join(lines)
        
        # Errors by component
        if "errors_by_component" in summary.get("summary", {}):
            lines.append("Errors by Component:")
            for component, count in summary["summary"]["errors_by_component"].items():
                lines.append(f"  - {component}: {count} error(s)")
            lines.append("")
        
        # Most problematic component
        if summary["summary"].get("most_problematic_component"):
            component_info = summary["summary"]["most_problematic_component"]
            lines.append(f"Most Problematic Component: {component_info['component']} ({component_info['error_count']} errors)")
            lines.append("")
        
        # Recent errors
        if summary.get("errors"):
            lines.append("Recent Errors:")
            for error in summary["errors"][:5]:  # Show last 5
                lines.append(f"\n  Component: {error['component']}")
                lines.append(f"  Error: {error['error_type']}: {error['error_message']}")
                if error.get("context"):
                    ctx_str = ", ".join(f"{k}={v}" for k, v in error["context"].items())
                    lines.append(f"  Context: {ctx_str}")
                if error.get("session_url"):
                    lines.append(f"  Session: {error['session_url']}")

        return "\n".join(lines)
    
    def get_file_path_for_llm(self) -> str:
        """Get path to summary file that LLMs can read."""
        summary_file = self.errors_dir / f"error_summary_{self.today}.json"
        return str(summary_file.absolute())


# Global error tracker instance
_error_tracker: Optional[ErrorTracker] = None


def get_error_tracker() -> ErrorTracker:
    """Get or create global error tracker."""
    global _error_tracker
    if _error_tracker is None:
        _error_tracker = ErrorTracker()
    return _error_tracker

