"""Guardrails for failure point identification and diagnostics capture."""

import os
import time
from typing import Dict, Any, Optional
from dotenv import load_dotenv

load_dotenv()


def is_guardrails_enabled() -> bool:
    """Check if guardrails are enabled via environment variable."""
    raw = os.getenv("ENABLE_GUARDRAILS", "true")
    return raw.strip().lower() in ("1", "true", "yes", "y", "on")


async def check_page_navigation(page, expected_url: str) -> Dict[str, Any]:
    """
    Check if page navigation succeeded.
    
    Returns diagnostics about navigation state.
    """
    diagnostics = {
        "navigation_success": False,
        "expected_url": expected_url,
        "actual_url": None,
        "page_title": None,
        "page_accessible": False,
    }
    
    if not is_guardrails_enabled():
        return diagnostics
    
    try:
        actual_url = page.url
        page_title = await page.title()
        
        diagnostics.update({
            "navigation_success": actual_url == expected_url or expected_url in actual_url,
            "actual_url": actual_url,
            "page_title": page_title,
            "page_accessible": True,
        })
    except Exception as e:
        diagnostics["navigation_error"] = str(e)
        diagnostics["page_accessible"] = False
    
    return diagnostics


async def check_page_state(page) -> Dict[str, Any]:
    """
    Check current page state before extraction.
    
    Returns diagnostics about page accessibility and state.
    """
    diagnostics = {
        "page_accessible": False,
        "current_url": None,
        "page_title": None,
        "ready_for_extraction": False,
    }
    
    if not is_guardrails_enabled():
        return diagnostics
    
    try:
        url = page.url
        title = await page.title()
        
        # Try simple operation to verify page is responsive
        diagnostics.update({
            "page_accessible": True,
            "current_url": url,
            "page_title": title,
            "ready_for_extraction": True,
        })
    except Exception as e:
        diagnostics.update({
            "page_accessible": False,
            "error": str(e),
            "ready_for_extraction": False,
        })
    
    return diagnostics


async def check_session_creation(stagehand, page) -> Dict[str, Any]:
    """
    Check if Stagehand session was created successfully.
    
    Returns diagnostics about session state.
    """
    diagnostics = {
        "session_created": False,
        "page_object_valid": False,
        "page_accessible": False,
    }
    
    if not is_guardrails_enabled():
        return diagnostics
    
    try:
        if stagehand is not None and page is not None:
            diagnostics["session_created"] = True
            diagnostics["page_object_valid"] = True
            
            # Try to access page properties to verify it's working
            try:
                url = page.url
                diagnostics["page_accessible"] = True
                diagnostics["initial_url"] = url
            except Exception as e:
                diagnostics["page_accessible"] = False
                diagnostics["page_access_error"] = str(e)
    except Exception as e:
        diagnostics["session_error"] = str(e)
    
    return diagnostics


class GuardrailTimer:
    """Context manager for timing operations."""
    
    def __init__(self, operation_name: str):
        self.operation_name = operation_name
        self.start_time: Optional[float] = None
        self.duration_ms: Optional[float] = None
    
    def __enter__(self):
        if is_guardrails_enabled():
            self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if is_guardrails_enabled() and self.start_time is not None:
            self.duration_ms = (time.time() - self.start_time) * 1000
    
    def get_diagnostics(self) -> Dict[str, Any]:
        """Get timing diagnostics."""
        if not is_guardrails_enabled():
            return {}
        
        return {
            f"{self.operation_name}_duration_ms": self.duration_ms,
        }

