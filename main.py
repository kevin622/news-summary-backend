import logging
import asyncio
from datetime import datetime, timezone, timedelta
from typing import List, Optional

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Query
from google import genai
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict
from supabase import create_client, Client

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("news-summary-backend")

# 1. Environment variables (using pydantic-settings)
class Settings(BaseSettings):
    SUPABASE_PROJECT_URL: str
    SUPABASE_SECRET_KEY: str
    GEMINI_API_KEY: str

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()

# 2. Client Initializations
supabase: Client = create_client(settings.SUPABASE_PROJECT_URL, settings.SUPABASE_SECRET_KEY)

app = FastAPI(
    title="News Factory Transcript Summary Service",
    description="FastAPI backend to fetch, summarize and cache transcripts of '김어준의 겸손은힘들다 뉴스공장'",
    version="1.0.0"
)

# Pydantic Response Model
class SummaryItem(BaseModel):
    title: str
    content_url: str
    summary: str
    publish_date: str

# 3. Crawler Logic
async def fetch_today_articles(target_date: str) -> List[dict]:
    """
    Crawls https://humblefactory.co.kr/category/transcript/
    and retrieves articles matching the target_date (YYYY-MM-DD).
    """
    url = "https://humblefactory.co.kr/category/transcript/"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, follow_redirects=True, timeout=15.0)
            response.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to fetch category page: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch category page: {str(e)}"
        )

    soup = BeautifulSoup(response.text, "html.parser")
    articles = soup.find_all("article")
    
    matched_articles = []
    for article in articles:
        # Check publish date from <time> tag
        time_tag = article.find("time")
        if not time_tag:
            continue
        
        datetime_attr = time_tag.get("datetime", "")
        # datetime_attr typically format: "2026-06-05T12:01:56+09:00"
        if not datetime_attr.startswith(target_date):
            continue

        # Extract title and link
        title_a = article.select_one("h3.entry-title a")
        if not title_a:
            continue
            
        title = title_a.text.strip()
        href = title_a["href"]

        matched_articles.append({
            "title": title,
            "content_url": href,
            "publish_date": target_date
        })

    logger.info(f"Found {len(matched_articles)} articles for date {target_date}")
    return matched_articles

async def fetch_article_content(url: str) -> str:
    """
    Crawls the detailed interview transcript page and extracts the transcript text content.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, follow_redirects=True, timeout=15.0)
            response.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to fetch article detail page {url}: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"Failed to fetch article detail page {url}: {str(e)}"
        )

    soup = BeautifulSoup(response.text, "html.parser")
    # Identify content div
    content_div = soup.select_one(".post-content, .entry-content, .w-post-elm.post_content")
    if not content_div:
        logger.warning(f"Could not find transcript content container at {url}, attempting fallback.")
        paragraphs = soup.find_all("p")
        if paragraphs:
            return "\n".join([p.get_text().strip() for p in paragraphs if p.get_text().strip()])
        return ""

    # Clean text extraction with newline separations
    text = content_div.get_text("\n").strip()
    return text

# 4. Gemini API Helper
async def generate_summary(text: str) -> str:
    """
    Calls Gemini API (gemini-3.1-flash-lite) to summarize the interview transcript.
    """
    prompt = "이 뉴스 인터뷰 전문을 읽고 핵심 내용 3줄 요약 및 주요 참석자 정보를 빈티지하고 정갈한 톤으로 요약해줘."
    full_prompt = f"{prompt}\n\n[전문]\n{text}"

    try:
        # Create client instance bound to the active event loop to avoid session/loop mismatch
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        response = await client.aio.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=full_prompt
        )
        if not response.text:
            raise ValueError("Empty response received from Gemini API")
        return response.text.strip()
    except Exception as e:
        logger.error(f"Gemini API call failed: {e}")
        raise HTTPException(
            status_code=502,
            detail=f"Gemini API call failed: {str(e)}"
        )

# 5. Endpoint
@app.get("/today-summaries", response_model=List[SummaryItem])
async def get_today_summaries(
    date: Optional[str] = Query(
        None, 
        description="Target date in YYYY-MM-DD format (KST). Defaults to today's date."
    )
):
    # Set date to KST today if not provided
    if not date:
        kst = timezone(timedelta(hours=9))
        date = datetime.now(kst).strftime("%Y-%m-%d")
        logger.info(f"Date query parameter not provided. Using today (KST): {date}")
    else:
        logger.info(f"Target date query: {date}")

    # Step 1: Crawl category list page for matching articles
    articles = await fetch_today_articles(date)
    if not articles:
        logger.info(f"No articles found for date {date}")
        return []

    summaries = []

    for article in articles:
        url = article["content_url"]
        title = article["title"]
        publish_date = article["publish_date"]

        # Step 2: Query Supabase cache
        cached_record = None
        try:
            db_res = supabase.table("summaries").select("*").eq("content_url", url).execute()
            if db_res.data:
                cached_record = db_res.data[0]
        except Exception as e:
            logger.error(f"Supabase cache lookup error for {url}: {e}")

        if cached_record:
            # Step 3: Cache Hit
            logger.info(f"Cache HIT for: {url}")
            summaries.append(SummaryItem(
                title=cached_record.get("title") or title,
                content_url=cached_record["content_url"],
                summary=cached_record["summary_text"],
                publish_date=str(cached_record["target_date"])
            ))
        else:
            # Step 4: Cache Miss -> Crawl detailed page, summarize, cache in Supabase
            logger.info(f"Cache MISS for: {url}. Scraping detail page...")
            detail_content = await fetch_article_content(url)
            if not detail_content:
                logger.warning(f"Empty content parsed for {url}. Skipping summary generation.")
                continue

            logger.info(f"Requesting Gemini summary for {url} using gemini-3.1-flash-lite...")
            summary_text = await generate_summary(detail_content)

            # Insert into database
            try:
                insert_data = {
                    "title": title,
                    "content_url": url,
                    "summary_text": summary_text,
                    "target_date": publish_date
                }
                supabase.table("summaries").insert(insert_data).execute()
                logger.info(f"Successfully cached summary in Supabase for: {url}")
            except Exception as e:
                logger.error(f"Failed to cache summary in Supabase: {e}")
                # Return the result anyway even if database caching fails
            
            summaries.append(SummaryItem(
                title=title,
                content_url=url,
                summary=summary_text,
                publish_date=publish_date
            ))

    return summaries


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
