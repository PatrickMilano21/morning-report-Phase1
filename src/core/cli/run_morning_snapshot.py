# src/core/cli/run_morning_snapshot.py

import asyncio
import json
import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from src.core.stagehand_runner import create_stagehand_session
from src.core.report_builder import build_morning_report
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
    *args,
    **kwargs,
):
    """Run a source function with its own isolated browser session."""
    stagehand = None
    try:
        from src.core.stagehand_runner import create_stagehand_session
        stagehand, page = await create_stagehand_session()
        result = await fetch_func(page, ticker, *args, **kwargs)
        return result
    except Exception as e:
        print(f"[ERROR] {ticker} {source_name} failed: {e}")
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
    try:
        from src.core.stagehand_runner import create_stagehand_session
        stagehand, page = await create_stagehand_session()
        result = await fetch_macro_news(page)
        return result
    except Exception as e:
        print(f"[ERROR] Macro News failed: {e}")
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
    try:
        from src.core.stagehand_runner import create_stagehand_session
        stagehand, page = await create_stagehand_session()
        results = await fetch_vital_knowledge_headlines_batch(page, tickers)
        return {result.ticker: result for result in results}
    except Exception as e:
        print(f"[ERROR] Vital Knowledge batch failed: {e}")
        return {}
    finally:
        if stagehand is not None:
            try:
                await stagehand.close()
            except Exception as close_error:
                print(f"[WARN] Error closing Vital Knowledge batch session: {close_error}")


async def process_ticker(
    ticker: str,
    sem: asyncio.Semaphore,
    use_yahoo_quote: bool,
    use_yahoo_analysis: bool,
    use_marketwatch: bool,
    use_googlenews: bool,
    use_vital_knowledge: bool,
):
    async with sem:
        print(f"\n=== Processing {ticker} ===")

        quote = None
        analysis = None
        mw = None
        googlenews = None
        vital_knowledge = None
        error_messages: list[str] = []

        # --- Yahoo quote ---
        if use_yahoo_quote:
            print(f"[{ticker}] Starting Yahoo Quote...")
            quote = await _run_source_with_session("YahooQuote", ticker, fetch_yahoo_quote)
            if quote:
                print(f"[YahooQuote] {ticker}: OK")
            else:
                error_messages.append("YahooQuote failed")

        # --- Yahoo AI analysis ---
        if use_yahoo_analysis:
            print(f"[{ticker}] Starting Yahoo AI...")
            analysis = await _run_source_with_session("YahooAI", ticker, fetch_yahoo_ai_analysis)
            if analysis:
                print(f"[YahooAI] {ticker}: OK")
            else:
                error_messages.append("YahooAI failed")

        # --- MarketWatch Top Stories ---
        if use_marketwatch:
            print(f"[{ticker}] Starting MarketWatch...")
            mw = await _run_source_with_session("MarketWatch", ticker, fetch_marketwatch_top_stories, max_cards=3)
            if mw:
                print(f"[MarketWatch] {ticker}: {len(mw.stories) if mw.stories else 0} stories")
            else:
                error_messages.append("MarketWatch failed")

        # --- Google News ---
        if use_googlenews:
            print(f"[{ticker}] Starting Google News...")
            googlenews = await _run_source_with_session("GoogleNews", ticker, fetch_google_news_stories, max_stories=5, max_days=2)
            if googlenews:
                articles_count = len([s for s in googlenews.stories if s.summary and not s.summary.startswith("Error")])
                print(f"[GoogleNews] {ticker}: {articles_count} articles analyzed")
            else:
                error_messages.append("GoogleNews failed")

        # Vital Knowledge is processed in batch outside of this function
        vital_knowledge = None
        return {
            "ticker": ticker,
            "error": "; ".join(error_messages) if error_messages else None,
            "quote": quote.model_dump() if quote else None,
            "analysis": analysis.model_dump() if analysis else None,
            "marketwatch": mw.model_dump() if mw else None,
            "googlenews": googlenews.model_dump() if googlenews else None,
            "vital_knowledge": vital_knowledge.model_dump() if vital_knowledge else None,
        }


async def main():
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
                mw_obj = None

        googlenews_obj = None
        if item.get("googlenews"):
            try:
                googlenews_obj = GoogleNewsTopStories(**item["googlenews"])
            except Exception as e:
                print(f"[WARN] {ticker}: failed to parse GoogleNewsTopStories: {e}")
                googlenews_obj = None

        vital_knowledge_obj = None
        if item.get("vital_knowledge"):
            try:
                vital_knowledge_obj = VitalKnowledgeReport(**item["vital_knowledge"])
            except Exception as e:
                print(f"[WARN] {ticker}: failed to parse VitalKnowledgeReport: {e}")
                vital_knowledge_obj = None

        if item.get("error"):
            print(f"[INFO] {ticker} had source errors: {item['error']}")

        typed_items.append((q, a, mw_obj, googlenews_obj, vital_knowledge_obj))

    if not typed_items:
        print("[WARN] No successful tickers to include in report.")
        return

    macro_news_obj = None
    if use_macro_news and macro_news_result:
        try:
            macro_news_obj = MacroNewsSummary(**macro_news_result.model_dump())
        except Exception as e:
            print(f"[WARN] Failed to parse MacroNewsSummary: {e}")
            macro_news_obj = None

    report_md = build_morning_report(today, typed_items, macro_news_obj)
    report_path.write_text(report_md, encoding="utf-8")
    print(f"Morning Snapshot written to: {report_path}")


def main_cli():
    asyncio.run(main())


if __name__ == "__main__":
    main_cli()
