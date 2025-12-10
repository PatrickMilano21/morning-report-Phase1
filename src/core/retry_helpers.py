# src/core/retry_helpers.py

import asyncio
from typing import Any, Callable, Optional, Tuple, Type


async def _retry_async(
    func: Callable[..., Any],
    *args,
    max_retries: int = 2,
    base_delay: float = 1.0,
    retry_exceptions: Tuple[Type[BaseException], ...] = (Exception,),
    **kwargs,
) -> Any:
    """
    Generic async retry helper with exponential backoff.

    attempt 0: first try (no delay)
    attempt 1: delay base_delay
    attempt 2: delay base_delay * 2
    """
    attempt = 0
    while True:
        try:
            return await func(*args, **kwargs)
        except retry_exceptions as e:
            attempt += 1
            if attempt > max_retries:
                raise
            delay = base_delay * (2 ** (attempt - 1))
            print(
                f"[Retry] {func.__name__} failed (attempt {attempt}/{max_retries}): {e}. "
                f"Retrying in {delay:.1f}s..."
            )
            await asyncio.sleep(delay)


async def navigate_with_retry(
    page,
    url: str,
    max_retries: int = 2,
    timeout: int = 30000,
    wait_until: str = "load",
) -> None:
    """
    Navigate to URL with exponential backoff retry.
    Applies to all skills; keeps behavior consistent.
    """
    async def _goto(u: str, **inner_kwargs):
        return await page.goto(u, **inner_kwargs)

    await _retry_async(
        _goto,
        url,
        max_retries=max_retries,
        base_delay=1.0,
        timeout=timeout,
        wait_until=wait_until,
    )


async def extract_with_retry(
    page,
    instruction: str,
    schema: Any,
    max_retries: int = 1,
    selector: Optional[str] = None,
) -> Any:
    """
    Extract with optional single retry for transient Stagehand errors.
    Targeted use only where we've seen flakiness (e.g., Vital Knowledge).
    """
    async def _extract(instr: str, sch: Any, selector: Optional[str] = None):
        return await page.extract(instruction=instr, schema=sch, selector=selector)

    return await _retry_async(
        _extract,
        instruction,
        schema,
        max_retries=max_retries,
        base_delay=1.0,
        selector=selector,
    )
