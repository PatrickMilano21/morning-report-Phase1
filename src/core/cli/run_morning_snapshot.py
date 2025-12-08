# src/core/cli/run_morning_snapshot.py

import asyncio
import json
import os
import time
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from src.core.stagehand_runner import create_stagehand_session
from src.core.report_builder import build_morning_report
from src.core.observability.errors import get_error_tracker
from src.skills.yahoo.quote import YahooQuoteSnapshot, fetch_yahoo_quote
from src.skills.yahoo.research import YahooAIAnalysis, fetch_yahoo_ai_analysis
from src.skills.marketwatch.research import (
    MarketWatchTopStories,
    fetch_marketwatch_top_stories,
)
from src.skills.googlenews.research import (
    GoogleNewsTopStories,
    fetch_google_news_stories,
)
from src.skills.vital_knowledge.research import (
    VitalKnowledgeReport,
    fetch_vital_knowledge_headlines,
    fetch_vital_knowledge_headlines_batch,
)
from src.skills.vital_knowledge.macro_news import (
    MacroNewsSummary,
    fetch_macro_news,
)

WATCHLIST_PATH = Path("config/watchlist.json")
SNAPSHOT_DIR = Path("data/snapshots")
REPORTS_DIR = Path("data/reports")
METRICS_DIR = Path("data/metrics")

# Collect metrics during run - will be written to baseline at end
run_metrics = {
    "pipeline_start_time": None,  # Set at start of main()
    "timing": {"per_source": {}},
    "sessions": [],
    "success_count": 0,
    "error_count": 0,
    "llm_tokens": {
        "total_prompt_tokens": 0,
        "total_completion_tokens": 0,
        "total_inference_time_ms": 0,
    },
    "browserbase": {
        "total_proxy_bytes": 0,
        "sessions_detail": [],  # Individual session metrics
    },
    "quality": {
        "per_ticker": {},  # {ticker: {googlenews_articles, googlenews_bullets, yahoo_ai_bullets, vital_knowledge_headlines}}
    },
}


def collect_stagehand_metrics(stagehand):
    """Extract LLM token metrics from stagehand.metrics (StagehandMetrics dataclass)."""
    try:
        metrics = stagehand.metrics
        return {
            "prompt_tokens": getattr(metrics, 'total_prompt_tokens', 0) or 0,
            "completion_tokens": getattr(metrics, 'total_completion_tokens', 0) or 0,
            "inference_time_ms": getattr(metrics, 'total_inference_time_ms', 0) or 0,
        }
    except Exception as e:
        print(f"[Metrics] Warning: Could not collect stagehand metrics: {e}")
        return {"prompt_tokens": 0, "completion_tokens": 0, "inference_time_ms": 0}


async def collect_browserbase_metrics(session_id: str):
    """Fetch session metrics from Browserbase API."""
    try:
        from browserbase import Browserbase
        bb = Browserbase(api_key=os.getenv("BROWSERBASE_API_KEY"))
        session = bb.sessions.retrieve(session_id)
        return {
            "proxy_bytes": getattr(session, 'proxy_bytes', 0) or 0,
            "avg_cpu_usage": getattr(session, 'avg_cpu_usage', None),
            "memory_usage": getattr(session, 'memory_usage', None),
            "status": getattr(session, 'status', None),
        }
    except Exception as e:
        print(f"[Metrics] Warning: Could not collect browserbase metrics for {session_id}: {e}")
        return {"proxy_bytes": 0, "avg_cpu_usage": None, "memory_usage": None, "status": None}


def save_baseline_metrics(step: int = 0, name: str = "baseline"):
    """Save collected metrics to a numbered JSON file (e.g., 000_baseline.json, 001_phase1.json)."""
    from datetime import datetime

    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{step:03d}_{name}.json"
    metrics_path = METRICS_DIR / filename

    # Calculate wall-clock duration (actual time from start to end of pipeline)
    if run_metrics["pipeline_start_time"]:
        wall_clock_duration = round(time.time() - run_metrics["pipeline_start_time"], 1)
    else:
        wall_clock_duration = 0

    baseline = {
        "step": step,
        "name": name,
        "description": f"Metrics from {name} run",
        "timestamp": datetime.now().isoformat(),
        "metrics": {
            "timing": {
                "wall_clock_duration_sec": wall_clock_duration,
                "per_source": run_metrics["timing"]["per_source"],
            },
            "reliability": {
                "success_count": run_metrics["success_count"],
                "error_count": run_metrics["error_count"],
                "session_count": len(run_metrics["sessions"]),
                "success_rate": run_metrics["success_count"] / (run_metrics["success_count"] + run_metrics["error_count"]) if (run_metrics["success_count"] + run_metrics["error_count"]) > 0 else 0,
            },
            "llm_tokens": run_metrics["llm_tokens"],
            "browserbase": {
                "total_proxy_bytes": run_metrics["browserbase"]["total_proxy_bytes"],
                "sessions_detail": run_metrics["browserbase"]["sessions_detail"],
            },
            "quality": run_metrics["quality"],
            "sessions": run_metrics["sessions"],
        },
    }

    metrics_path.write_text(json.dumps(baseline, indent=2))
    print(f"\n[Metrics] Saved to: {metrics_path}")
    print(f"  Sessions: {len(run_metrics['sessions'])}")
    print(f"  Success: {run_metrics['success_count']}, Errors: {run_metrics['error_count']}")
    print(f"  LLM Tokens: {run_metrics['llm_tokens']['total_prompt_tokens']:,} prompt + {run_metrics['llm_tokens']['total_completion_tokens']:,} completion")
    print(f"  Proxy Bytes: {run_metrics['browserbase']['total_proxy_bytes']:,}")

    # Print quality metrics summary
    if run_metrics["quality"]["per_ticker"]:
        print(f"  Quality Metrics:")
        for ticker, quality in run_metrics["quality"]["per_ticker"].items():
            print(f"    {ticker}: {quality['googlenews_articles']} articles, {quality['yahoo_ai_bullets']} AI bullets, {quality['vital_knowledge_headlines']} VK headlines")


def _env_flag(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "y", "on")


def _get_max_concurrent_browsers() -> int:
    raw = os.getenv("MAX_CONCURRENT_BROWSERS")
    if not raw:
        return 2
    try:
        val = int(raw)
        return max(1, val)
    except ValueError:
        return 2


async def _run_source_with_session(
    source_name: str,
    ticker: str,
    fetch_func,
    sem: asyncio.Semaphore,
    *args,
    **kwargs,
):
    """Run a source function with its own isolated browser session."""
    stagehand = None
    all_diagnostics = {}
    failure_point = None
    start_time = time.time()

    try:
        async with sem:  # Acquire semaphore slot for this session
            from src.core.stagehand_runner import create_stagehand_session
            from src.core.observability.guardrails import (
                check_session_creation,
                GuardrailTimer,
                is_guardrails_enabled,
            )

            # GUARDRAIL: Session Creation
            try:
                with GuardrailTimer("session_creation") as session_timer:
                    stagehand, page = await create_stagehand_session()
                all_diagnostics.update(session_timer.get_diagnostics())

                if is_guardrails_enabled():
                    session_diagnostics = await check_session_creation(stagehand, page)
                    all_diagnostics.update(session_diagnostics)

                    if not session_diagnostics.get("session_created", False):
                        failure_point = "session_creation"
                        raise Exception("Session creation failed")

            except Exception as e:
                failure_point = failure_point or "session_creation"
                e.diagnostics = all_diagnostics
                e.failure_point = failure_point
                raise

            # Execute fetch function (which has its own guardrails)
            result = await fetch_func(page, ticker, *args, **kwargs)

            # Collect enhanced metrics
            duration = time.time() - start_time
            session_id = getattr(stagehand, 'session_id', 'unknown')

            # Collect LLM token metrics from stagehand
            llm_metrics = collect_stagehand_metrics(stagehand)
            run_metrics["llm_tokens"]["total_prompt_tokens"] += llm_metrics["prompt_tokens"]
            run_metrics["llm_tokens"]["total_completion_tokens"] += llm_metrics["completion_tokens"]
            run_metrics["llm_tokens"]["total_inference_time_ms"] += llm_metrics["inference_time_ms"]

            # Collect Browserbase session metrics
            bb_metrics = await collect_browserbase_metrics(session_id)
            run_metrics["browserbase"]["total_proxy_bytes"] += bb_metrics["proxy_bytes"]
            run_metrics["browserbase"]["sessions_detail"].append({
                "session_id": session_id,
                "source": source_name,
                "ticker": ticker,
                **bb_metrics,
            })

            print(f"[Metrics] {source_name}/{ticker}: {duration:.1f}s, tokens={llm_metrics['prompt_tokens']}+{llm_metrics['completion_tokens']}, session={session_id}")

            if source_name not in run_metrics["timing"]["per_source"]:
                run_metrics["timing"]["per_source"][source_name] = {}
            run_metrics["timing"]["per_source"][source_name][ticker] = {
                "duration_sec": round(duration, 1),
                "session_id": session_id,
                "llm_tokens": llm_metrics,
            }
            run_metrics["sessions"].append(session_id)
            run_metrics["success_count"] += 1

            return result

    except Exception as e:
        print(f"[ERROR] {ticker} {source_name} failed: {e}")
        # Track error with component identification
        error_tracker = get_error_tracker()

        # Extract diagnostics and failure_point from exception if available (from guardrails)
        # Merge with any session-level diagnostics
        exception_diagnostics = getattr(e, 'diagnostics', {})
        if exception_diagnostics:
            all_diagnostics.update(exception_diagnostics)

        diagnostics = all_diagnostics if all_diagnostics else None
        failure_point = getattr(e, 'failure_point', failure_point)

        error_tracker.record_error(
            error=e,
            component=f"{source_name} ({fetch_func.__module__})",  # e.g., "YahooQuote (src.skills.yahoo.quote)"
            context={"ticker": ticker, "source": source_name, "function": fetch_func.__name__},
            diagnostics=diagnostics,
            failure_point=failure_point,
        )
        run_metrics["error_count"] += 1
        return None
    finally:
        if stagehand is not None:
            try:
                await stagehand.close()
            except Exception as close_error:
                print(f"[WARN] Error closing {source_name} session for {ticker}: {close_error}")


async def fetch_macro_news_with_session():
    """Fetch macro news in a dedicated browser session."""
    stagehand = None
    start_time = time.time()
    try:
        from src.core.stagehand_runner import create_stagehand_session
        stagehand, page = await create_stagehand_session()
        # Get days_back from env var, default to 2
        days_back = int(os.getenv("Vital_Days_Back", "2"))
        result = await fetch_macro_news(page, days_back=days_back)

        # Collect enhanced metrics
        duration = time.time() - start_time
        session_id = getattr(stagehand, 'session_id', 'unknown')

        # Collect LLM token metrics from stagehand
        llm_metrics = collect_stagehand_metrics(stagehand)
        run_metrics["llm_tokens"]["total_prompt_tokens"] += llm_metrics["prompt_tokens"]
        run_metrics["llm_tokens"]["total_completion_tokens"] += llm_metrics["completion_tokens"]
        run_metrics["llm_tokens"]["total_inference_time_ms"] += llm_metrics["inference_time_ms"]

        # Collect Browserbase session metrics
        bb_metrics = await collect_browserbase_metrics(session_id)
        run_metrics["browserbase"]["total_proxy_bytes"] += bb_metrics["proxy_bytes"]
        run_metrics["browserbase"]["sessions_detail"].append({
            "session_id": session_id,
            "source": "MacroNews",
            **bb_metrics,
        })

        print(f"[Metrics] MacroNews: {duration:.1f}s, tokens={llm_metrics['prompt_tokens']}+{llm_metrics['completion_tokens']}, session={session_id}")

        run_metrics["timing"]["per_source"]["MacroNews"] = {
            "duration_sec": round(duration, 1),
            "session_id": session_id,
            "llm_tokens": llm_metrics,
        }
        run_metrics["sessions"].append(session_id)
        run_metrics["success_count"] += 1

        return result
    except Exception as e:
        print(f"[ERROR] Macro News failed: {e}")
        run_metrics["error_count"] += 1
        error_tracker = get_error_tracker()
        error_tracker.record_error(
            error=e,
            component="fetch_macro_news_with_session",
            context={"source": "MacroNews"},
        )
        return None
    finally:
        if stagehand is not None:
            try:
                await stagehand.close()
            except Exception as close_error:
                print(f"[WARN] Error closing Macro News session: {close_error}")


async def _run_vital_knowledge_batch(tickers: list[str]):
    """Batch fetch Vital Knowledge data for all tickers in a single session."""
    stagehand = None
    start_time = time.time()
    try:
        from src.core.stagehand_runner import create_stagehand_session
        stagehand, page = await create_stagehand_session()
        # Get days_back from env var, default to 2 (same as macro_news)
        days_back = int(os.getenv("Vital_Days_Back", "2"))
        results = await fetch_vital_knowledge_headlines_batch(page, tickers, days_back=days_back)

        # Collect enhanced metrics
        duration = time.time() - start_time
        session_id = getattr(stagehand, 'session_id', 'unknown')

        # Collect LLM token metrics from stagehand
        llm_metrics = collect_stagehand_metrics(stagehand)
        run_metrics["llm_tokens"]["total_prompt_tokens"] += llm_metrics["prompt_tokens"]
        run_metrics["llm_tokens"]["total_completion_tokens"] += llm_metrics["completion_tokens"]
        run_metrics["llm_tokens"]["total_inference_time_ms"] += llm_metrics["inference_time_ms"]

        # Collect Browserbase session metrics
        bb_metrics = await collect_browserbase_metrics(session_id)
        run_metrics["browserbase"]["total_proxy_bytes"] += bb_metrics["proxy_bytes"]
        run_metrics["browserbase"]["sessions_detail"].append({
            "session_id": session_id,
            "source": "VitalKnowledge",
            "tickers": tickers,
            **bb_metrics,
        })

        print(f"[Metrics] VitalKnowledge/batch: {duration:.1f}s, tokens={llm_metrics['prompt_tokens']}+{llm_metrics['completion_tokens']}, session={session_id}")

        run_metrics["timing"]["per_source"]["VitalKnowledge"] = {
            "batch": {
                "duration_sec": round(duration, 1),
                "session_id": session_id,
                "tickers": tickers,
                "llm_tokens": llm_metrics,
            }
        }
        run_metrics["sessions"].append(session_id)
        run_metrics["success_count"] += 1

        return {result.ticker: result for result in results}
    except Exception as e:
        print(f"[ERROR] Vital Knowledge batch failed: {e}")
        run_metrics["error_count"] += 1
        error_tracker = get_error_tracker()
        error_tracker.record_error(
            error=e,
            component="_run_vital_knowledge_batch",
            context={"tickers": tickers, "source": "VitalKnowledge"},
        )
        return {}
    finally:
        if stagehand is not None:
            try:
                await stagehand.close()
            except Exception as close_error:
                print(f"[WARN] Error closing Vital Knowledge batch session: {close_error}")


async def _warm_up_yahoo_selector():
    """
    Warm up the Yahoo selector cache by running observe() once.
    This caches the XPath so subsequent per-ticker calls skip observe().
    """
    from src.skills.yahoo.quote import _get_or_discover_selector, CACHE_KEY

    stagehand = None
    try:
        stagehand, page = await create_stagehand_session()
        await page.goto("https://finance.yahoo.com/quote/AAPL", timeout=30000)
        selector = await _get_or_discover_selector(page, CACHE_KEY)
        if selector:
            print(f"[YahooQuote] Warm-up complete, cached selector: {selector[:60]}...")
        else:
            print("[YahooQuote] Warm-up: observe() returned no selector, will use full-page extract")
    except Exception as e:
        print(f"[YahooQuote] Warm-up failed: {e} - per-ticker calls will run observe() individually")
    finally:
        if stagehand:
            try:
                await stagehand.close()
            except Exception:
                pass


async def process_ticker(
    ticker: str,
    sem: asyncio.Semaphore,
    use_yahoo_quote: bool,
    use_yahoo_analysis: bool,
    use_marketwatch: bool,
    use_googlenews: bool,
    use_vital_knowledge: bool,
):
    """Process a single ticker with concurrent source fetches."""
    print(f"\n=== Processing {ticker} ===")

    # Build list of source tasks to run concurrently
    source_tasks = []
    task_info = []  # Track which source each task represents

    # --- Yahoo Quote ---
    if use_yahoo_quote:
        print(f"[{ticker}] Starting Yahoo Quote...")
        source_tasks.append(_run_source_with_session("YahooQuote", ticker, fetch_yahoo_quote, sem))
        task_info.append("quote")

    # --- Yahoo AI analysis ---
    if use_yahoo_analysis:
        print(f"[{ticker}] Starting Yahoo AI...")
        source_tasks.append(_run_source_with_session("YahooAI", ticker, fetch_yahoo_ai_analysis, sem))
        task_info.append("analysis")

    # --- MarketWatch Top Stories ---
    if use_marketwatch:
        print(f"[{ticker}] Starting MarketWatch...")
        source_tasks.append(_run_source_with_session("MarketWatch", ticker, fetch_marketwatch_top_stories, sem, max_cards=3))
        task_info.append("marketwatch")

    # --- Google News ---
    if use_googlenews:
        print(f"[{ticker}] Starting Google News...")
        source_tasks.append(_run_source_with_session("GoogleNews", ticker, fetch_google_news_stories, sem, max_stories=5, max_days=2))
        task_info.append("googlenews")

    # Run all sources concurrently
    results = await asyncio.gather(*source_tasks, return_exceptions=True)

    # Map results back to variables
    quote = None
    analysis = None
    mw = None
    googlenews = None
    error_messages: list[str] = []

    for task_name, result in zip(task_info, results):
        if isinstance(result, Exception):
            error_messages.append(f"{task_name} failed: {result}")
            result = None
        elif result is None:
            error_messages.append(f"{task_name} failed")

        if task_name == "quote":
            quote = result
            if quote:
                print(f"[YahooQuote] {ticker}: ${quote.last_price}")
        elif task_name == "analysis":
            analysis = result
            if analysis:
                print(f"[YahooAI] {ticker}: OK")
        elif task_name == "marketwatch":
            mw = result
            if mw:
                print(f"[MarketWatch] {ticker}: {len(mw.stories) if mw.stories else 0} stories")
        elif task_name == "googlenews":
            googlenews = result
            if googlenews:
                articles_count = len([s for s in googlenews.stories if s.summary and not s.summary.startswith("Error")])
                print(f"[GoogleNews] {ticker}: {articles_count} articles analyzed")

    # Note: Vital Knowledge is processed in batch outside of this function
    return {
        "ticker": ticker,
        "error": "; ".join(error_messages) if error_messages else None,
        "quote": quote.model_dump() if quote else None,
        "analysis": analysis.model_dump() if analysis else None,
        "marketwatch": mw.model_dump() if mw else None,
        "googlenews": googlenews.model_dump() if googlenews else None,
        "vital_knowledge": None,  # Will be filled from batch results
    }


async def main():
    run_metrics["pipeline_start_time"] = time.time()  # Record start time for wall-clock duration

    use_yahoo_quote = _env_flag("ENABLE_YAHOO_QUOTE", True)
    use_yahoo_analysis = _env_flag("ENABLE_YAHOO_ANALYSIS", True)
    use_marketwatch = _env_flag("ENABLE_MARKETWATCH", True)
    use_googlenews = _env_flag("ENABLE_GOOGLE_NEWS", True)
    use_vital_knowledge = _env_flag("ENABLE_VITAL_NEWS", True)
    use_macro_news = _env_flag("ENABLE_MACRO_NEWS", True)

    print(
        "Sources enabled:",
        f"yahoo_quote={use_yahoo_quote},",
        f"yahoo_analysis={use_yahoo_analysis},",
        f"marketwatch={use_marketwatch},",
        f"googlenews={use_googlenews},",
        f"vital_knowledge={use_vital_knowledge},",
        f"macro_news={use_macro_news}",
    )

    # Load watchlist
    if WATCHLIST_PATH.exists():
        watchlist = json.loads(WATCHLIST_PATH.read_text())
    else:
        watchlist = ["AAPL", "GOOGL"]

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    today = date.today()
    snapshot_path = SNAPSHOT_DIR / f"yahoo_snapshot_{today.isoformat()}.json"
    mw_snapshot_path = SNAPSHOT_DIR / f"marketwatch_snapshot_{today.isoformat()}.json"
    googlenews_snapshot_path = SNAPSHOT_DIR / f"googlenews_snapshot_{today.isoformat()}.json"
    vital_knowledge_snapshot_path = SNAPSHOT_DIR / f"vital_knowledge_snapshot_{today.isoformat()}.json"
    macro_news_snapshot_path = SNAPSHOT_DIR / f"macro_news_snapshot_{today.isoformat()}.json"
    report_path = REPORTS_DIR / f"morning_snapshot_{today.isoformat()}.md"

    max_concurrent = _get_max_concurrent_browsers()
    print(f"Using MAX_CONCURRENT_BROWSERS = {max_concurrent}")
    sem = asyncio.Semaphore(max_concurrent)

    # Warm up Yahoo selector cache (one short session)
    if use_yahoo_quote:
        print("\n[YahooQuote] Running selector warm-up...")
        await _warm_up_yahoo_selector()

    ticker_tasks = [
        process_ticker(ticker, sem, use_yahoo_quote, use_yahoo_analysis, use_marketwatch, use_googlenews, use_vital_knowledge)
        for ticker in watchlist
    ]

    all_tasks = list(ticker_tasks)
    macro_news_result = None
    if use_macro_news:
        print("\n[MacroNews] Starting macro news fetch (independent browser session)...")
        macro_news_task = fetch_macro_news_with_session()
        all_tasks.append(macro_news_task)

    vital_knowledge_batch_results = None
    if use_vital_knowledge:
        print(f"\n[VitalKnowledge] Starting batch fetch for {len(watchlist)} tickers (independent browser session)...")
        vital_knowledge_batch_task = _run_vital_knowledge_batch(watchlist)
        all_tasks.append(vital_knowledge_batch_task)

    all_results = await asyncio.gather(*all_tasks)

    results = all_results[:len(ticker_tasks)]

    if use_macro_news:
        macro_news_result = all_results[len(ticker_tasks)]
        if use_vital_knowledge:
            vital_knowledge_batch_results = all_results[len(ticker_tasks) + 1]
    elif use_vital_knowledge:
        vital_knowledge_batch_results = all_results[len(ticker_tasks)]
    if use_vital_knowledge and vital_knowledge_batch_results:
        print("\n[Merging] Adding Vital Knowledge batch results to ticker data...")
        for item in results:
            ticker = item.get("ticker")
            if ticker in vital_knowledge_batch_results:
                item["vital_knowledge"] = vital_knowledge_batch_results[ticker].model_dump()
                headlines_count = len(vital_knowledge_batch_results[ticker].headlines) if vital_knowledge_batch_results[ticker].headlines else 0
                print(f"[VitalKnowledge] {ticker}: {headlines_count} headlines from batch")
            else:
                print(f"[WARN] {ticker}: No Vital Knowledge data from batch")

    yahoo_snapshot = {
        "as_of": today.isoformat(),
        "tickers": [
            {
                "ticker": item.get("ticker"),
                "error": item.get("error"),
                "quote": item.get("quote"),
                "analysis": item.get("analysis"),
            }
            for item in results
        ],
    }
    snapshot_path.write_text(json.dumps(yahoo_snapshot, indent=2), encoding="utf-8")
    print(f"\nYahoo snapshot written to: {snapshot_path}")

    mw_snapshot = {
        "as_of": today.isoformat(),
        "tickers": [
            {
                "ticker": item.get("ticker"),
                "error": item.get("error"),
                "marketwatch": item.get("marketwatch"),
            }
            for item in results
        ],
    }
    mw_snapshot_path.write_text(json.dumps(mw_snapshot, indent=2), encoding="utf-8")
    print(f"MarketWatch snapshot written to: {mw_snapshot_path}")

    googlenews_snapshot = {
        "as_of": today.isoformat(),
        "tickers": [
            {
                "ticker": item.get("ticker"),
                "error": item.get("error"),
                "googlenews": item.get("googlenews"),
            }
            for item in results
        ],
    }
    googlenews_snapshot_path.write_text(json.dumps(googlenews_snapshot, indent=2), encoding="utf-8")
    print(f"Google News snapshot written to: {googlenews_snapshot_path}")

    vital_knowledge_snapshot = {
        "as_of": today.isoformat(),
        "tickers": [
            {
                "ticker": item.get("ticker"),
                "error": item.get("error"),
                "vital_knowledge": item.get("vital_knowledge"),
            }
            for item in results
        ],
    }
    vital_knowledge_snapshot_path.write_text(json.dumps(vital_knowledge_snapshot, indent=2), encoding="utf-8")
    print(f"Vital Knowledge snapshot written to: {vital_knowledge_snapshot_path}")

    if use_macro_news:
        macro_news_snapshot = {
            "as_of": today.isoformat(),
            "macro_news": macro_news_result.model_dump() if macro_news_result else None,
        }
        macro_news_snapshot_path.write_text(json.dumps(macro_news_snapshot, indent=2), encoding="utf-8")
        print(f"Macro News snapshot written to: {macro_news_snapshot_path}")

    typed_items = []
    for item in results:
        ticker = item.get("ticker")

        if not item.get("quote"):
            print(f"[WARN] Skipping {ticker} in report (no quote data)")
            continue

        q = YahooQuoteSnapshot(**item["quote"])

        if item.get("analysis"):
            a = YahooAIAnalysis(**item["analysis"])
        else:
            print(f"[WARN] {ticker}: no Yahoo AI analysis; using empty analysis object")
            a = YahooAIAnalysis(
                ticker=ticker,
                title=None,
                summary=None,
                bullets=[],
            )

        mw_obj = None
        if item.get("marketwatch"):
            try:
                mw_obj = MarketWatchTopStories(**item["marketwatch"])
            except Exception as e:
                print(f"[WARN] {ticker}: failed to parse MarketWatchTopStories: {e}")
                error_tracker = get_error_tracker()
                error_tracker.record_error(
                    error=e,
                    component="parse_MarketWatchTopStories",
                    context={"ticker": ticker},
                )
                mw_obj = None

        googlenews_obj = None
        if item.get("googlenews"):
            try:
                googlenews_obj = GoogleNewsTopStories(**item["googlenews"])
            except Exception as e:
                print(f"[WARN] {ticker}: failed to parse GoogleNewsTopStories: {e}")
                error_tracker = get_error_tracker()
                error_tracker.record_error(
                    error=e,
                    component="parse_GoogleNewsTopStories",
                    context={"ticker": ticker},
                )
                googlenews_obj = None

        vital_knowledge_obj = None
        if item.get("vital_knowledge"):
            try:
                vital_knowledge_obj = VitalKnowledgeReport(**item["vital_knowledge"])
            except Exception as e:
                print(f"[WARN] {ticker}: failed to parse VitalKnowledgeReport: {e}")
                error_tracker = get_error_tracker()
                error_tracker.record_error(
                    error=e,
                    component="parse_VitalKnowledgeReport",
                    context={"ticker": ticker},
                )
                vital_knowledge_obj = None

        if item.get("error"):
            print(f"[INFO] {ticker} had source errors: {item['error']}")

        typed_items.append((q, a, mw_obj, googlenews_obj, vital_knowledge_obj))

        # Collect quality metrics for this ticker
        ticker_quality = {
            "googlenews_articles": len(googlenews_obj.stories) if googlenews_obj else 0,
            "googlenews_bullets": len(googlenews_obj.news_summary.bullet_points) if googlenews_obj and googlenews_obj.news_summary else 0,
            "yahoo_ai_bullets": len(a.bullets) if a else 0,
            "vital_knowledge_headlines": len(vital_knowledge_obj.headlines) if vital_knowledge_obj else 0,
        }
        run_metrics["quality"]["per_ticker"][ticker] = ticker_quality

    if not typed_items:
        print("[WARN] No successful tickers to include in report.")
        # Still save metrics even on failure
        save_baseline_metrics(step=1, name="phase1")
        return

    macro_news_obj = None
    if use_macro_news and macro_news_result:
        try:
            macro_news_obj = MacroNewsSummary(**macro_news_result.model_dump())
        except Exception as e:
            print(f"[WARN] Failed to parse MacroNewsSummary: {e}")
            error_tracker = get_error_tracker()
            error_tracker.record_error(
                error=e,
                component="parse_MacroNewsSummary",
                context={},
            )
            macro_news_obj = None

    report_md = build_morning_report(today, typed_items, macro_news_obj)
    report_path.write_text(report_md, encoding="utf-8")
    print(f"Morning Snapshot written to: {report_path}")
    
    # Print error summary if any errors occurred
    error_tracker = get_error_tracker()
    summary = error_tracker.get_summary()
    if summary["total_errors"] > 0:
        error_summary_path = error_tracker.get_file_path_for_llm()
        print(f"\n[ERRORS] {summary['total_errors']} error(s) occurred. Summary: {error_summary_path}")
        print(f"  Most problematic component: {summary['summary']['most_problematic_component']['component']}")
        print(f"  Error summary file: {error_summary_path}")

    # Save metrics for Phase 1
    save_baseline_metrics(step=1, name="phase1")


def main_cli():
    try:
        asyncio.run(main())
    except Exception as e:
        error_tracker = get_error_tracker()
        error_tracker.record_error(
            error=e,
            component="main_pipeline",
            context={},
        )
        error_summary_path = error_tracker.get_file_path_for_llm()
        print(f"\n[FATAL ERROR] Pipeline failed: {e}")
        print(f"Error summary saved to: {error_summary_path}")
        raise


if __name__ == "__main__":
    main_cli()
