from typing import List, Optional, Literal
from datetime import datetime, timedelta
import asyncio
from pydantic import BaseModel, Field, ConfigDict

from src.core.retry_helpers import navigate_with_retry
from src.core.observability.errors import get_error_tracker


class GoogleNewsStory(BaseModel):
    """News article with URL and summary."""

    headline: str = Field(..., description="Article headline/title")
    url: str = Field(..., description="Full URL to the article")
    source: Optional[str] = Field(default=None, description="Publisher/source name")
    age: Optional[str] = Field(default=None, description="Time indicator like '2 hours ago'")
    summary: Optional[str] = Field(
        default=None,
        description="Brief summary of why the stock is moving based on article content",
    )
    sentiment: Optional[Literal["positive", "negative", "neutral"]] = Field(
        default=None,
        description="Sentiment of the article (positive, negative, or neutral)",
    )


class GoogleNewsSummary(BaseModel):
    """AI-generated summary across all stories for a ticker."""

    model_config = ConfigDict(populate_by_name=True)

    overall_sentiment: Optional[Literal["bullish", "bearish", "mixed", "neutral"]] = Field(
        default=None,
        alias="overallSentiment",
        description="Overall sentiment across all stories",
    )
    bullet_points: List[str] = Field(
        default_factory=list,
        alias="bulletPoints",
        description="4 bullet points of the most important, current market news for the ticker",
    )


class GoogleNewsTopStories(BaseModel):
    """Container for all Google News data for a ticker."""

    ticker: str
    stories: List[GoogleNewsStory] = Field(default_factory=list)
    news_summary: Optional[GoogleNewsSummary] = Field(default=None)


class ArticleLink(BaseModel):
    """Helper model for extracting article links from search results."""
    headline: str
    url: str
    source: Optional[str] = None
    age: Optional[str] = None


class ArticleLinks(BaseModel):
    """Container for extracted article links."""
    articles: List[ArticleLink] = Field(default_factory=list)


async def fetch_google_news_stories(
    page,
    ticker: str,
    max_stories: int = 5,
    max_days: int = 2,
) -> GoogleNewsTopStories:
    """Fetch Google News stories for a ticker with Stagehand."""

    search_query = f"{ticker} stock news"

    url = (
        f"https://www.google.com/search?"
        f"q={search_query.replace(' ', '+')}"
        f"&tbm=nws"
        f"&tbs=qdr:d{max_days},sbd:1"
    )

    print(f"[GoogleNews] Navigating to Google News for '{search_query}'")
    print(f"[GoogleNews] URL: {url}")

    stories: List[GoogleNewsStory] = []

    try:
        await navigate_with_retry(page, url, max_retries=2, timeout=30000, wait_until="networkidle")
        print(f"[GoogleNews] News results loaded")
        # ---------------------------------------------------------------------
        # Use a hybrid approach: Stagehand extract() for content, observe() for URLs

        print(f"[GoogleNews] Extracting article links...")

        # First, use Stagehand to identify and extract article metadata
        # This works well for visible content like headlines, sources, ages
        article_metadata = await page.extract(
            instruction=f"""
            Find the top {max_stories} news article headlines from Google News search results.

            For each article, extract:
            - headline: The article title/headline text
            - source: The publisher name (e.g., "Reuters", "CNBC", "Yahoo Finance")
            - age: How old the article is (e.g., "2 hours ago", "1 day ago")

            ONLY extract articles that are within the last {max_days} days.
            Do NOT include older articles.

            Return the articles in order of relevance and recency.
            """,
            schema=ArticleLinks,
        )

        # Now use JavaScript to get ALL links and match them to headlines
        # This works around Stagehand's difficulty with href extraction
        all_links = await page.evaluate("""
            () => {
                const links = [];
                document.querySelectorAll('a').forEach(link => {
                    const href = link.href;
                    const text = link.textContent.trim();
                    if (href && href.startsWith('http') && text.length > 15) {
                        links.push({ url: href, text: text });
                    }
                });
                return links;
            }
        """)

        # Match extracted headlines with actual URLs
        articles = []
        for article in article_metadata.articles:
            # Find matching URL by headline text
            matching_link = None
            for link in all_links:
                # Check if link text contains significant portion of headline
                if article.headline[:30].lower() in link['text'].lower():
                    matching_link = link['url']
                    break

            if matching_link:
                articles.append(ArticleLink(
                    headline=article.headline,
                    url=matching_link,
                    source=article.source,
                    age=article.age
                ))

        article_links = ArticleLinks(articles=articles)
        print(f"[GoogleNews] Found {len(article_links.articles)} articles to visit")

        # ---------------------------------------------------------------------
        # Visit each article and extract summary (SEQUENTIALLY)
        # ---------------------------------------------------------------------
        # Note: Browserbase doesn't support concurrent tabs well, so we process
        # articles sequentially. This is still faster than the old approach because
        # we removed the back-and-forth navigation and observe/click overhead.

        print(f"\n[GoogleNews] Processing {min(len(article_links.articles), max_stories)} articles sequentially...")

        for i, article in enumerate(article_links.articles[:max_stories]):
            print(f"\n[GoogleNews] [{i+1}/{min(len(article_links.articles), max_stories)}] Visiting: {article.headline[:60]}...")
            print(f"[GoogleNews] URL: {article.url}")

            try:
                # Navigate directly to article URL (no clicking, no going back)
                await navigate_with_retry(page, article.url, max_retries=2, timeout=30000, wait_until="load")
                print(f"[GoogleNews] [{i+1}] Page loaded")

                # Extract summary
                summary_data = await page.extract(
                    instruction=f"""
                    Read this news article about {ticker} stock.
                    Write a brief 2-3 sentence summary explaining:
                    - What is the main news/event?
                    - Why is this causing {ticker} stock to move?
                    - Is this positive, negative, or neutral for the stock?
                    Be factual and concise. Only use information from this article.
                    Return:
                    - summary: Your 2-3 sentence summary
                    - sentiment: "positive", "negative", or "neutral"
                    """,
                    schema=GoogleNewsStory,
                )

                # Create the story object
                story = GoogleNewsStory(
                    headline=article.headline,
                    url=page.url,  # Use final URL after any redirects
                    source=article.source,
                    age=article.age,
                    summary=summary_data.summary if hasattr(summary_data, 'summary') else None,
                    sentiment=summary_data.sentiment if hasattr(summary_data, 'sentiment') else None,
                )

                stories.append(story)
                print(f"[GoogleNews] OK Summary: {story.summary[:80] if story.summary else 'N/A'}...")

            except Exception as e:
                print(f"[GoogleNews] ERROR processing article: {e}")
                error_tracker = get_error_tracker()
                error_tracker.record_error(
                    error=e,
                    component="GoogleNews (src.skills.googlenews.research)",
                    context={"ticker": ticker, "article_headline": article.headline, "article_url": article.url},
                    failure_point="article_processing",
                )
                # Still add article with basic info
                stories.append(GoogleNewsStory(
                    headline=article.headline,
                    url=article.url,
                    source=article.source,
                    age=article.age,
                    summary=None,
                    sentiment=None,
                ))

        print(f"\n[GoogleNews] Processed {len(stories)} articles ({len([s for s in stories if s.summary])} with summaries)")

        # ---------------------------------------------------------------------
        # Generate overall summary
        # ---------------------------------------------------------------------

        overall = None
        try:
            print(f"\n[GoogleNews] Generating overall summary...")

            # Combine all summaries for analysis
            all_summaries = "\n".join([
                f"- {s.headline}: {s.summary}"
                for s in stories
                if s.summary and not s.summary.startswith("Error")
            ])

            if all_summaries:
                # Navigate to a simple page for the AI to think
                # Wrap in try/except in case browser crashes during summary generation
                try:
                    overall = await page.extract(
                        instruction=f"""
                        Based on these {len([s for s in stories if s.summary and not s.summary.startswith("Error")])} news articles about {ticker} stock:

                        {all_summaries}

                        Provide:
                        - overall_sentiment: Is the overall news "bullish", "bearish", "mixed", or "neutral"?
                        - bullet_points: Provide exactly 4 bullet points of the most important, current market news for {ticker}. Each bullet should be concise (1-2 sentences) and focus on actionable market-moving information.
                        """,
                        schema=GoogleNewsSummary,
                    )
                except Exception as summary_error:
                    print(f"[GoogleNews] Error generating summary (continuing with stories): {summary_error}")
                    error_tracker = get_error_tracker()
                    error_tracker.record_error(
                        error=summary_error,
                        component="GoogleNews (src.skills.googlenews.research)",
                        context={"ticker": ticker, "phase": "overall_summary_generation"},
                        failure_point="summary_extraction",
                    )
                    overall = None
        except Exception as e:
            print(f"[GoogleNews] Error in summary generation section (continuing with stories): {e}")
            error_tracker = get_error_tracker()
            error_tracker.record_error(
                error=e,
                component="GoogleNews (src.skills.googlenews.research)",
                context={"ticker": ticker, "phase": "summary_section"},
                failure_point="summary_section_error",
            )
            overall = None

        # ---------------------------------------------------------------------
        # Return results - always return stories we successfully collected
        # ---------------------------------------------------------------------

        result = GoogleNewsTopStories(
            ticker=ticker.upper(),
            stories=stories,
            news_summary=overall,
        )

        successful_count = len([s for s in stories if s.summary and not s.summary.startswith("Error")])
        print(f"\n[GoogleNews] Complete! {len(stories)} stories collected, {successful_count} with summaries")

        return result

    except Exception as e:
        print(f"[GoogleNews] Fatal error for {ticker}: {e}")
        error_tracker = get_error_tracker()
        error_tracker.record_error(
            error=e,
            component="GoogleNews (src.skills.googlenews.research)",
            context={"ticker": ticker, "function": "fetch_google_news_stories", "stories_collected": len(stories) if stories else 0},
            failure_point="fatal_error",
        )
        # Return whatever stories we managed to collect before the fatal error
        # This ensures we don't lose all the work if something crashes late
        if stories:
            successful_count = len([s for s in stories if s.summary and not s.summary.startswith("Error")])
            print(f"[GoogleNews] Returning {len(stories)} stories collected ({successful_count} with summaries) before error")
            return GoogleNewsTopStories(
                ticker=ticker.upper(),
                stories=stories,
                news_summary=None,
            )
        else:
            print(f"[GoogleNews] No stories collected, returning empty result")
            return GoogleNewsTopStories(ticker=ticker.upper(), stories=[])


# =============================================================================
# STANDALONE TEST FUNCTION
# =============================================================================

async def test_google_news(ticker: str = "AAPL"):
    """
    Test the Google News scraper standalone.

    Usage (from morning_report_copy directory):
        python -m src.skills.googlenews.research

    This will:
    1. Create a Browserbase browser session
    2. Search Google News for the ticker
    3. Visit top articles and extract summaries
    4. Print URLs and summaries
    5. Close the browser
    """
    import json
    from src.core.stagehand_runner import create_stagehand_session

    print(f"\n{'='*60}")
    print(f"Testing Google News scraper for {ticker}")
    print(f"{'='*60}\n")

    stagehand = None
    try:
        stagehand, page = await create_stagehand_session()

        result = await fetch_google_news_stories(
            page,
            ticker,
            max_stories=5,
            max_days=2,
        )

        # Print results
        print(f"\n{'='*60}")
        print("RESULTS")
        print(f"{'='*60}\n")

        print(f"Ticker: {result.ticker}")

        if result.news_summary:
            print(f"\n--- Google News Summary ---")
            print(f"Articles Analyzed: {len([s for s in result.stories if s.summary and not s.summary.startswith('Error')])}")
            print(f"Sentiment: {result.news_summary.overall_sentiment}")
            if result.news_summary.bullet_points:
                print(f"\nKey Market News:")
                for bullet in result.news_summary.bullet_points:
                    print(f"  • {bullet}")
        else:
            print(f"\nNo summary available. Stories found: {len(result.stories)}")

        return result

    finally:
        if stagehand:
            await stagehand.close()
            print(f"\n[GoogleNews] Browser session closed")


# =============================================================================
# SCRIPT ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    import asyncio
    from dotenv import load_dotenv

    load_dotenv()
    asyncio.run(test_google_news("AAPL"))
