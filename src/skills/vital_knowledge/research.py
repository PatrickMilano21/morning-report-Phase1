# src/skills/vital_knowledge/research.py
#
# This script scrapes Vital Knowledge for ticker-specific macro news using Stagehand.
# - Navigates to "Everything" tab
# - Extracts all report links with dates from the page
# - Filters by date constraint (today back to N days ago at 12pm ET)
# - Opens each matching report and extracts ticker-specific news for ALL tickers
# - Combines results per ticker, weighting newer articles more

import asyncio
import os
from datetime import datetime, timedelta
from typing import List, Optional, Literal, Dict
from pydantic import BaseModel, Field, ConfigDict
from zoneinfo import ZoneInfo

from src.core.retry_helpers import navigate_with_retry, extract_with_retry
from src.core.observability.errors import get_error_tracker


# =============================================================================
# DATA MODELS (Pydantic)
# =============================================================================

class VitalKnowledgeHeadline(BaseModel):
    """Single headline from Vital Knowledge report."""
    headline: str = Field(..., description="The headline text")
    context: Optional[str] = Field(default=None, description="Additional context or details")
    sentiment: Optional[Literal["positive", "negative", "neutral"]] = Field(
        default=None,
        description="Sentiment of the headline"
    )


class VitalKnowledgeSummary(BaseModel):
    """Summary of all headlines for a ticker."""
    overall_sentiment: Optional[Literal["bullish", "bearish", "mixed", "neutral"]] = Field(
        default=None,
        description="Overall sentiment across headlines"
    )
    key_themes: List[str] = Field(
        default_factory=list,
        description="Main themes or topics"
    )
    summary: Optional[str] = Field(
        default=None,
        description="Very brief 1-2 sentence summary of key points"
    )


class VitalKnowledgeReport(BaseModel):
    """Container for all extracted Vital Knowledge data."""
    ticker: str
    headlines: List[VitalKnowledgeHeadline] = Field(default_factory=list)
    report_dates: List[str] = Field(default_factory=list, description="Dates of reports scraped")
    summary: Optional[VitalKnowledgeSummary] = Field(default=None)


class ReportLink(BaseModel):
    """A single report link extracted from the Everything page."""
    title: str = Field(..., description="Report title")
    date_str: str = Field(..., description="Date string as shown on page (e.g., 'Dec 3, 2025 05:20 AM')")
    category: str = Field(..., description="Report category (MORNING, MARKET CLOSE, etc.)")
    url: Optional[str] = Field(default=None, description="Report URL if available")
    parsed_date: Optional[datetime] = Field(default=None, description="Parsed datetime object")


class TickerBullets(BaseModel):
    """Extracted bullets for a specific ticker from a report."""
    bullets: List[str] = Field(default_factory=list, description="List of bullet points about the ticker, max 5 per report")


class TickerSummary(BaseModel):
    """Summary for a ticker across all reports."""
    overall_sentiment: Optional[str] = Field(default=None, description="bullish, bearish, mixed, or neutral")
    key_themes: List[str] = Field(default_factory=list, description="2-3 main themes")
    summary: Optional[str] = Field(default=None, description="1-2 sentence summary")


class ArticleSource(BaseModel):
    """Source article that was scraped."""
    title: str = Field(..., description="Report title")
    date_str: str = Field(..., description="Date string (e.g., 'Dec 3, 2025 02:20 AM')")
    category: str = Field(..., description="Report category (MORNING, MARKET CLOSE, etc.)")


class TickerReport(BaseModel):
    """Internal model for processing ticker data."""
    ticker: str = Field(..., description="Stock ticker symbol")
    bullets: List[str] = Field(default_factory=list, description="Top 5 bullets, weighted by importance/recency")
    summary: Optional[TickerSummary] = Field(default=None, description="Overall summary for this ticker")
    sources: List[ArticleSource] = Field(default_factory=list, description="Reports that mentioned this ticker")
    report_count: int = Field(default=0, description="Number of reports that mentioned this ticker")


# =============================================================================
# CONSTANTS
# =============================================================================

TICKER_EXTRACTION_INSTRUCTION = """You are analyzing a Vital Knowledge market report to extract news specific to a particular stock ticker.

Your job is to find and extract ONLY information that DIRECTLY impacts the specified ticker.

INSTRUCTIONS:

1. Read the ENTIRE report carefully.

2. Look for mentions of:
   - The ticker symbol itself (e.g., "AAPL", "GOOGL")
   - The company name (e.g., "Apple", "Alphabet/Google")
   - Products, services, or executives directly tied to that company
   - Analyst ratings, price targets, or earnings for that company
   - Sector news that SPECIFICALLY names or impacts that company

3. DO NOT include:
   - General market/macro news (unless it specifically names the ticker)
   - Sector news that doesn't mention the specific company
   - News about competitors (unless comparing directly to the ticker)

4. For each bullet point:
   - Be specific and include numbers when available (price targets, % moves, earnings figures)
   - Explain WHY it matters for the stock
   - Keep it concise but informative (1-2 sentences)

5. Return up to 5 bullet points. If there is NO news about this ticker in the report, return an empty list.

OUTPUT FORMAT:
Return a list of bullet points, each being a complete, actionable piece of information about the ticker."""


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def parse_vital_date(date_str: str) -> Optional[datetime]:
    """
    Parse Vital Knowledge date string to datetime.
    
    Examples:
    - "Dec 3, 2025 05:20 AM" -> datetime(2025, 12, 3, 5, 20)
    - "Dec 2, 2025 04:02 PM" -> datetime(2025, 12, 2, 16, 2)
    """
    try:
        formats = [
            "%b %d, %Y %I:%M %p",  # "Dec 3, 2025 05:20 AM"
            "%B %d, %Y %I:%M %p",  # "December 3, 2025 05:20 AM"
        ]
        
        for fmt in formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt
            except ValueError:
                continue
        
        # Try date only
        date_only_formats = [
            "%b %d, %Y",  # "Dec 3, 2025"
            "%B %d, %Y",  # "December 3, 2025"
        ]
        
        date_parts = ' '.join(date_str.split()[:3])
        for fmt in date_only_formats:
            try:
                dt = datetime.strptime(date_parts, fmt)
                return dt
            except ValueError:
                continue
        
        return None
    except Exception:
        return None


def get_date_constraint(days_back: int = 1) -> tuple[datetime, datetime]:
    """
    Get the date range constraint: today back to N days ago at 12pm ET.
    """
    et = ZoneInfo('US/Eastern')
    now_et = datetime.now(et)
    end_date = now_et
    start_day = now_et - timedelta(days=days_back)
    start_date = start_day.replace(hour=12, minute=0, second=0, microsecond=0)
    return start_date, end_date


def is_in_date_range(report_date: datetime, start_date: datetime, end_date: datetime) -> bool:
    """Check if report date falls within the constraint range."""
    if report_date.tzinfo is None:
        et = ZoneInfo('US/Eastern')
        report_date = report_date.replace(tzinfo=et)
    return start_date <= report_date <= end_date


def _convert_ticker_report_to_vital_knowledge_report(ticker_report: TickerReport) -> VitalKnowledgeReport:
    """Convert TickerReport to VitalKnowledgeReport for compatibility."""
    # Convert bullets to headlines
    headlines = [
        VitalKnowledgeHeadline(
            headline=bullet,
            context=None,
            sentiment=None,
        )
        for bullet in ticker_report.bullets
    ]
    
    # Convert summary
    summary = None
    if ticker_report.summary:
        summary = VitalKnowledgeSummary(
            overall_sentiment=ticker_report.summary.overall_sentiment,
            key_themes=ticker_report.summary.key_themes,
            summary=ticker_report.summary.summary,
        )
    
    # Extract report dates from sources
    report_dates = []
    seen_dates = set()
    for source in ticker_report.sources:
        # Try to parse date from date_str and format as YYYY-MM-DD
        parsed_date = parse_vital_date(source.date_str)
        if parsed_date:
            date_str = parsed_date.strftime("%Y-%m-%d")
            if date_str not in seen_dates:
                seen_dates.add(date_str)
                report_dates.append(date_str)
    
    return VitalKnowledgeReport(
        ticker=ticker_report.ticker,
        headlines=headlines,
        report_dates=report_dates,
        summary=summary,
    )


# =============================================================================
# MAIN SCRAPING FUNCTION
# =============================================================================

async def fetch_vital_knowledge_headlines_batch(
    page,
    tickers: List[str],
    days_back: Optional[int] = None,
) -> List[VitalKnowledgeReport]:
    """
    Fetch ticker-specific news from Vital Knowledge for multiple tickers.

    This function:
    1. Logs in to vitalknowledge.net
    2. Navigates to "Everything" tab
    3. Extracts all report links with dates
    4. Filters by date constraint (today back to N days ago at 12pm ET)
    5. Opens each matching report and extracts news for ALL tickers
    6. Combines results per ticker, weighting newer articles more

    Args:
        page: A StagehandPage instance
        tickers: List of stock ticker symbols (e.g., ["AAPL", "GOOGL"])
        days_back: Number of days to look back (defaults to env var Vital_Days_Back or 2)

    Returns:
        List[VitalKnowledgeReport] - one per ticker, compatible with existing code
    """
    # Get days_back from parameter, env var, or default
    if days_back is None:
        days_back = int(os.getenv("Vital_Days_Back", "2"))
    
    print(f"[VitalKnowledge] Starting batch scrape for {len(tickers)} tickers: {tickers}")
    print(f"[VitalKnowledge] Days back: {days_back}")

    # ========================================================================
    # STEP 1: LOGIN TO VITAL KNOWLEDGE
    # ========================================================================
    username = os.getenv("Vital_login")
    password = os.getenv("Vital_password")

    if not username or not password:
        raise ValueError("Missing Vital_login or Vital_password in .env")

    print("[VitalKnowledge] Navigating to login page...")
    await navigate_with_retry(page, "https://vitalknowledge.net/login", max_retries=2, timeout=30000, wait_until="networkidle")

    print("[VitalKnowledge] Entering credentials...")
    await page.act(f"Enter '{username}' into the username or email input field")
    await page.act(f"Enter '{password}' into the password input field")
    await page.act("Click the login or sign in button")
    await page.wait_for_load_state("networkidle", timeout=30000)
    print("[VitalKnowledge] Login successful")

    # Get date constraint
    start_date, end_date = get_date_constraint(days_back)
    print(f"[VitalKnowledge] Date constraint: {start_date.strftime('%Y-%m-%d %H:%M %Z')} to {end_date.strftime('%Y-%m-%d %H:%M %Z')}")

    # Initialize per-ticker data: ticker -> list of (bullet, weight, source)
    ticker_data: Dict[str, List[tuple[str, float, ArticleSource]]] = {t: [] for t in tickers}

    try:
        # ========================================================================
        # STEP 2: NAVIGATE TO "EVERYTHING" TAB
        # ========================================================================
        print("[VitalKnowledge] Navigating to 'Everything' tab...")
        await page.act("Click on the 'Everything' link or button in the navigation")
        await page.wait_for_load_state("networkidle", timeout=15000)
        await asyncio.sleep(2)

        # ========================================================================
        # STEP 3: EXTRACT ALL REPORT LINKS WITH DATES
        # ========================================================================
        print("[VitalKnowledge] Extracting report links from Everything page...")

        class ReportLinksExtract(BaseModel):
            reports: List[ReportLink] = Field(..., description="List of all reports visible on the page")

        links_result = await page.extract(
            instruction="""
            On this Vital Knowledge "Everything" page, extract all visible report links.
            
            For each report, extract:
            - title: The report title/headline
            - date_str: The full date and time string as shown (e.g., "Dec 3, 2025 05:20 AM")
            - category: The report category label (MORNING, MARKET CLOSE, INTRADAY, EARNINGS, etc.)
            
            Include ALL reports visible on the page, regardless of category.
            """,
            schema=ReportLinksExtract,
        )

        if not links_result or not links_result.reports:
            print("[VitalKnowledge] No reports found on Everything page")
            return [VitalKnowledgeReport(ticker=t) for t in tickers]

        print(f"[VitalKnowledge] Found {len(links_result.reports)} total reports on page")

        # ========================================================================
        # STEP 4: PARSE DATES AND FILTER BY CONSTRAINT
        # ========================================================================
        print("[VitalKnowledge] Parsing dates and filtering by constraint...")

        valid_reports: List[ReportLink] = []
        for report in links_result.reports:
            parsed_date = parse_vital_date(report.date_str)
            if parsed_date:
                report.parsed_date = parsed_date
                if is_in_date_range(parsed_date, start_date, end_date):
                    valid_reports.append(report)
                    print(f"  [OK] {report.category}: {report.title} ({report.date_str})")
                else:
                    print(f"  [SKIP] {report.category}: {report.title} ({report.date_str}) - outside date range")
            else:
                print(f"  [WARN] Could not parse date: {report.date_str}")

        if not valid_reports:
            print("[VitalKnowledge] No reports match the date constraint")
            return [VitalKnowledgeReport(ticker=t) for t in tickers]

        print(f"[VitalKnowledge] {len(valid_reports)} reports match date constraint")

        # ========================================================================
        # STEP 5: PROCESS EACH REPORT - EXTRACT FOR ALL TICKERS
        # ========================================================================
        reports_processed = 0

        for i, report in enumerate(valid_reports):
            print(f"\n[VitalKnowledge] Processing report {i+1}/{len(valid_reports)}: {report.title}")

            try:
                # Click/open the report link
                observe_results = await page.observe(
                    f"Find the report link with the title '{report.title}' or text matching '{report.title[:50]}...'"
                )

                if observe_results:
                    await page.act(observe_results[0])
                else:
                    await page.act(f"Click the link with the title '{report.title}'")

                await asyncio.sleep(3)
                await page.wait_for_load_state("networkidle", timeout=15000)

                # Calculate weight for this report (newer = higher weight)
                weight = 1.0 - (i * 0.5 / max(len(valid_reports) - 1, 1))

                # Create source info
                source = ArticleSource(
                    title=report.title,
                    date_str=report.date_str,
                    category=report.category,
                )

                # Extract for each ticker
                for ticker in tickers:
                    print(f"  [VitalKnowledge] Extracting {ticker} from report...")

                    extract_result = await extract_with_retry(
                        page,
                        instruction=f"""{TICKER_EXTRACTION_INSTRUCTION}

                        TICKER TO FIND: {ticker}

                        Extract news ONLY about {ticker}. Return up to 5 bullet points.
                        If there is no news about {ticker}, return an empty list.
                        """,
                        schema=TickerBullets,
                        max_retries=1,
                    )

                    if extract_result and extract_result.bullets:
                        for bullet in extract_result.bullets[:5]:
                            ticker_data[ticker].append((bullet, weight, source))
                        print(f"    [OK] Found {len(extract_result.bullets)} bullets for {ticker}")
                    else:
                        print(f"    [--] No news for {ticker}")

                reports_processed += 1

                # Navigate back to Everything page for next report
                if i < len(valid_reports) - 1:
                    print("[VitalKnowledge] Navigating back to Everything page...")
                    await navigate_with_retry(page, "https://vitalknowledge.net/", max_retries=2, timeout=15000, wait_until="networkidle")
                    await page.act("Click on the 'Everything' link or button in the navigation")
                    await page.wait_for_load_state("networkidle", timeout=15000)
                    await asyncio.sleep(2)

            except Exception as e:
                print(f"  [ERROR] Error processing report: {e}")
                error_tracker = get_error_tracker()
                error_tracker.record_error(
                    error=e,
                    component="VitalKnowledge (src.skills.vital_knowledge.research)",
                    context={"report_title": report.title, "report_index": i, "tickers": tickers},
                    failure_point="report_processing",
                )
                continue

        # ========================================================================
        # STEP 6: COMBINE AND WEIGHT RESULTS PER TICKER
        # ========================================================================
        print(f"\n[VitalKnowledge] Combining results for {len(tickers)} tickers...")

        ticker_results: List[TickerReport] = []

        for ticker in tickers:
            print(f"\n[VitalKnowledge] Processing {ticker}...")

            data = ticker_data[ticker]

            if not data:
                print(f"  [--] No bullets found for {ticker}")
                ticker_results.append(TickerReport(ticker=ticker))
                continue

            # Sort by weight (highest first)
            data.sort(key=lambda x: x[1], reverse=True)

            # Take top 5 bullets
            top_bullets = [bullet for bullet, _, _ in data[:5]]

            # Get unique sources that mentioned this ticker
            seen_sources = set()
            sources = []
            for _, _, source in data:
                key = source.title
                if key not in seen_sources:
                    seen_sources.add(key)
                    sources.append(source)

            print(f"  [OK] {len(top_bullets)} bullets from {len(sources)} reports")

            # Generate summary
            summary = None
            if top_bullets:
                print(f"  [VitalKnowledge] Generating summary for {ticker}...")

                bullets_text = "\n".join(f"- {b}" for b in top_bullets)

                try:
                    summary = await page.extract(
                        instruction=f"""
                        Based on these Vital Knowledge bullets about {ticker}:

                        {bullets_text}

                        Provide:
                        - overall_sentiment: Must be exactly one of: "bullish", "bearish", "mixed", or "neutral"
                        - key_themes: List 2-3 main themes (e.g., ["earnings beat", "analyst upgrade", "product launch"])
                        - summary: Write a very brief 1-2 sentence summary of the key points about {ticker}
                        """,
                        schema=TickerSummary,
                    )
                except Exception as e:
                    print(f"    [WARN] Could not generate summary: {e}")
                    error_tracker = get_error_tracker()
                    error_tracker.record_error(
                        error=e,
                        component="VitalKnowledge (src.skills.vital_knowledge.research)",
                        context={"ticker": ticker, "phase": "summary_generation"},
                        failure_point="summary_extraction",
                    )

            ticker_results.append(TickerReport(
                ticker=ticker,
                bullets=top_bullets,
                summary=summary,
                sources=sources,
                report_count=len(sources),
            ))

        # Convert TickerReport to VitalKnowledgeReport for compatibility
        vital_knowledge_reports = [
            _convert_ticker_report_to_vital_knowledge_report(ticker_report)
            for ticker_report in ticker_results
        ]

        print(f"\n[VitalKnowledge] Complete! Processed {reports_processed} reports for {len(tickers)} tickers")
        return vital_knowledge_reports

    except Exception as e:
        print(f"[VitalKnowledge] Failed: {e}")
        import traceback
        traceback.print_exc()
        error_tracker = get_error_tracker()
        error_tracker.record_error(
            error=e,
            component="VitalKnowledge (src.skills.vital_knowledge.research)",
            context={"tickers": tickers, "function": "fetch_vital_knowledge_headlines_batch"},
            failure_point="batch_fetch_failed",
        )
        return [VitalKnowledgeReport(ticker=t) for t in tickers]


async def fetch_vital_knowledge_headlines(
    page,
    ticker: str,
) -> VitalKnowledgeReport:
    """
    Fetch ticker-specific macro news from Vital Knowledge morning and market close reports.

    This function:
    1. Logs in to vitalknowledge.net
    2. Navigates to morning reports and extracts ticker-specific news (max 5 bullets)
    3. Navigates to market close reports and extracts ticker-specific news (max 5 bullets)
    4. Combines bullets, sorts by importance, keeps top 5
    5. Generates a very brief summary

    Args:
        page: A StagehandPage instance
        ticker: Stock ticker symbol (e.g., "AAPL")

    Returns:
        VitalKnowledgeReport with headlines and summary
    """
    print(f"[VitalKnowledge] Starting scrape for {ticker}")

    # Login
    username = os.getenv("Vital_login")
    password = os.getenv("Vital_password")

    if not username or not password:
        raise ValueError("Missing Vital_login or Vital_password in .env")

    print("[VitalKnowledge] Navigating to login page...")
    await navigate_with_retry(page, "https://vitalknowledge.net/login", max_retries=2, timeout=30000, wait_until="networkidle")

    print("[VitalKnowledge] Entering credentials...")
    await page.act(f"Enter '{username}' into the username or email input field")
    await page.act(f"Enter '{password}' into the password input field")
    await page.act("Click the login or sign in button")
    await page.wait_for_load_state("networkidle", timeout=30000)
    print("[VitalKnowledge] Login successful")

    all_bullets: List[str] = []
    report_dates: List[str] = []

    try:
        # ---------------------------------------------------------------------
        # MORNING REPORT
        # ---------------------------------------------------------------------
        print("[VitalKnowledge] Navigating to morning reports...")
        await page.act("Click on the 'morning' link or button in the navigation")
        await page.wait_for_load_state("networkidle", timeout=15000)
        
        print("[VitalKnowledge] Clicking first morning report...")
        await page.act("Click the first morning report link in the list to open it")
        await asyncio.sleep(3)
        await page.wait_for_load_state("networkidle", timeout=15000)
        
        # Extract date from URL
        try:
            if '/article/' in page.url:
                date_parts = page.url.split('/article/')[1].split('/')[:3]
                morning_date = '-'.join(date_parts)
            else:
                morning_date = datetime.now().strftime("%Y-%m-%d")
        except Exception:
            morning_date = datetime.now().strftime("%Y-%m-%d")
        report_dates.append(morning_date)
        print(f"[VitalKnowledge] Morning report date: {morning_date}")
        
        # Extract ticker-specific bullets from morning report
        print(f"[VitalKnowledge] Extracting ticker-specific news from morning report...")
        morning_bullets_result = await page.extract(
            instruction=f"""
            Read through this Vital Knowledge morning report.

            Extract ONLY news that specifically impacts {ticker} stock.

            Return up to 5 bullet points about {ticker}. Each bullet should be:
            - Specific to {ticker} (not general market news)
            - Concise but informative (1-2 sentences)
            - Focused on what's driving {ticker} stock movement

            If there is no news about {ticker} in this report, return an empty list.
            """,
            schema=ExtractedBullets,
        )
        
        morning_bullets = morning_bullets_result.bullets if morning_bullets_result else []
        print(f"[VitalKnowledge] Found {len(morning_bullets)} bullets in morning report")
        all_bullets.extend(morning_bullets)

        # ---------------------------------------------------------------------
        # MARKET CLOSE REPORT
        # ---------------------------------------------------------------------
        print("[VitalKnowledge] Navigating to market close reports...")
        await page.act("Click on the 'market close' link or button in the navigation")
        await asyncio.sleep(2)
        await page.wait_for_load_state("networkidle", timeout=15000)
        
        print("[VitalKnowledge] Clicking first market close report...")
        await page.act("Click the first market close report link in the list to open it")
        await asyncio.sleep(3)
        await page.wait_for_load_state("networkidle", timeout=15000)
        
        # Extract date from URL
        try:
            if '/article/' in page.url:
                date_parts = page.url.split('/article/')[1].split('/')[:3]
                market_close_date = '-'.join(date_parts)
            else:
                market_close_date = datetime.now().strftime("%Y-%m-%d")
        except Exception:
            market_close_date = datetime.now().strftime("%Y-%m-%d")
        
        report_dates.append(market_close_date)
        print(f"[VitalKnowledge] Market close report date: {market_close_date}")
        
        # Extract ticker-specific bullets from market close report
        print(f"[VitalKnowledge] Extracting ticker-specific news from market close report...")
        market_close_bullets_result = await page.extract(
            instruction=f"""
            Read through this Vital Knowledge market close report.

            Extract ONLY news that specifically impacts {ticker} stock.

            Return up to 5 bullet points about {ticker}. Each bullet should be:
            - Specific to {ticker} (not general market news)
            - Concise but informative (1-2 sentences)
            - Focused on what's driving {ticker} stock movement

            If there is no news about {ticker} in this report, return an empty list.
            """,
            schema=ExtractedBullets,
        )
        
        market_close_bullets = market_close_bullets_result.bullets if market_close_bullets_result else []
        print(f"[VitalKnowledge] Found {len(market_close_bullets)} bullets in market close report")
        all_bullets.extend(market_close_bullets)

        # ---------------------------------------------------------------------
        # COMBINE AND SORT BULLETS BY IMPORTANCE (MAX 5 TOTAL)
        # ---------------------------------------------------------------------
        final_bullets: List[str] = []
        
        if all_bullets:
            print(f"[VitalKnowledge] Combining {len(all_bullets)} bullets, sorting by importance...")
            
            # Have AI sort by importance and keep top 5
            combined_result = await page.extract(
                instruction=f"""
                You have {len(all_bullets)} bullet points about {ticker} stock from morning and market close reports:

                {chr(10).join(f"- {bullet}" for bullet in all_bullets)}

                Sort these by importance (most market-moving first) and return the top 5 most important bullets.
                If there are fewer than 5, return all of them.
                """,
                schema=CombinedBullets,
            )
            
            final_bullets = combined_result.top_bullets[:5] if combined_result else []
            print(f"[VitalKnowledge] Selected {len(final_bullets)} top bullets")

        # ---------------------------------------------------------------------
        # GENERATE VERY BRIEF SUMMARY
        # ---------------------------------------------------------------------
        summary = None
        if final_bullets:
            print("[VitalKnowledge] Generating brief summary...")
            
            bullets_text = "\n".join(f"- {bullet}" for bullet in final_bullets)
            
            summary = await page.extract(
                instruction=f"""
                Based on these Vital Knowledge bullets about {ticker}:

                {bullets_text}

                Provide:
                - overall_sentiment: Must be exactly one of: "bullish", "bearish", "mixed", or "neutral"
                - key_themes: List 2-3 main themes (e.g., ["earnings", "analyst upgrade"])
                - summary: Write a very brief 1-2 sentence summary of the key points about {ticker}
                """,
                schema=VitalKnowledgeSummary,
            )

        # ---------------------------------------------------------------------
        # CONVERT BULLETS TO HEADLINES FOR COMPATIBILITY
        # ---------------------------------------------------------------------
        headlines = [
            VitalKnowledgeHeadline(
                headline=bullet,
                context=None,
                sentiment=None,
            )
            for bullet in final_bullets
        ]

        # ---------------------------------------------------------------------
        # RETURN RESULTS
        # ---------------------------------------------------------------------
        result = VitalKnowledgeReport(
            ticker=ticker.upper(),
            headlines=headlines,
            report_dates=report_dates,
            summary=summary,
        )

        print(f"\n[VitalKnowledge] Complete! {len(final_bullets)} bullets extracted for {ticker}")

        return result

    except Exception as e:
        print(f"[VitalKnowledge] Failed for {ticker}: {e}")
        error_tracker = get_error_tracker()
        error_tracker.record_error(
            error=e,
            component="VitalKnowledge (src.skills.vital_knowledge.research)",
            context={"ticker": ticker, "function": "fetch_vital_knowledge_headlines"},
            failure_point="single_ticker_fetch_failed",
        )
        return VitalKnowledgeReport(ticker=ticker.upper())


# =============================================================================
# STANDALONE TEST FUNCTION
# =============================================================================

async def test_vital_knowledge(tickers: List[str] = None):
    """
    Test the Vital Knowledge scraper standalone with multiple tickers.

    Usage (from morning_report_copy directory):
        python -m src.skills.vital_knowledge.research

    Reads tickers from config/watchlist.json if not provided.
    """
    import json
    from pathlib import Path
    from src.core.stagehand_runner import create_stagehand_session

    # Load tickers from watchlist if not provided
    if tickers is None:
        watchlist_path = Path(__file__).parent.parent.parent.parent / "config" / "watchlist.json"
        with open(watchlist_path) as f:
            tickers = json.load(f)

    print(f"\n{'='*60}")
    print(f"Testing Vital Knowledge scraper for {len(tickers)} tickers")
    print(f"Tickers: {tickers}")
    print(f"{'='*60}\n")

    stagehand = None

    try:
        stagehand, page = await create_stagehand_session()

        # Use batch function to process all tickers from the same reports
        print(f"\n{'='*60}")
        print(f"Processing all {len(tickers)} tickers in batch (same reports)")
        print(f"{'='*60}\n")

        all_results = await fetch_vital_knowledge_headlines_batch(page, tickers)

        # Print results for each ticker
        for result in all_results:
            print(f"\n{'='*60}")
            print(f"Results for {result.ticker}")
            print(f"{'='*60}\n")
            print(f"Report Dates: {result.report_dates}")
            print(f"Bullets found: {len(result.headlines)}\n")

            for i, headline in enumerate(result.headlines, 1):
                print(f"Bullet {i}: {headline.headline}")

            if result.summary:
                print(f"\nSummary: {result.summary.summary}")
                print(f"Sentiment: {result.summary.overall_sentiment}")

        # Final summary
        print(f"\n{'='*60}")
        print("FINAL SUMMARY")
        print(f"{'='*60}\n")

        for result in all_results:
            print(f"{result.ticker}: {len(result.headlines)} bullets")
            if result.summary and result.summary.summary:
                print(f"  > {result.summary.summary[:150]}...")
            print()

        return all_results

    finally:
        if stagehand:
            await stagehand.close()
            print(f"\n[VitalKnowledge] Browser session closed")


# =============================================================================
# SCRIPT ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import asyncio
    from dotenv import load_dotenv

    load_dotenv()
    # Reads tickers from config/watchlist.json automatically
    asyncio.run(test_vital_knowledge())
