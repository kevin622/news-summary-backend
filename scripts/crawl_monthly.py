import sys
import os
import asyncio
from datetime import datetime
import argparse

import httpx
from bs4 import BeautifulSoup
from google import genai

# Add parent directory to sys.path so we can import config and database
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings, logger
from database import supabase
from services import fetch_article_content, generate_summary

async def crawl_monthly(target_month: str):
    """
    Crawls and summarizes all articles for a specific month (e.g., '2026-06').
    Handles pagination by iterating through /page/N/.
    """
    base_url = "https://humblefactory.co.kr/category/transcript/"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }

    page = 1
    processed_count = 0
    cached_count = 0
    
    # Parse target month to year and month integers for easy comparison
    try:
        target_dt = datetime.strptime(target_month, "%Y-%m")
        t_year, t_month = target_dt.year, target_dt.month
    except ValueError:
        logger.error("Invalid month format. Please use YYYY-MM (e.g., 2026-06).")
        return

    logger.info(f"Starting crawler for month: {target_month}")

    async with httpx.AsyncClient() as client:
        while True:
            # Construct pagination URL
            url = f"{base_url}page/{page}/" if page > 1 else base_url
            logger.info(f"Fetching list page {page}: {url}")
            
            try:
                response = await client.get(url, headers=headers, follow_redirects=True, timeout=15.0)
            except Exception as e:
                logger.error(f"Failed to fetch list page {page}: {e}")
                break

            # If a page returns 404, we've reached the end
            if response.status_code == 404:
                logger.info(f"Page {page} returned 404 Not Found. End of pagination.")
                break
            
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")
            articles = soup.find_all("article")
            
            if not articles:
                logger.info(f"No articles found on page {page}. Stopping.")
                break

            should_stop = False

            for article in articles:
                time_tag = article.find("time")
                if not time_tag:
                    continue
                
                datetime_attr = time_tag.get("datetime", "")
                if not datetime_attr:
                    continue

                # datetime_attr format: "2026-06-05T12:01:56+09:00"
                # Extract year and month
                try:
                    pub_dt = datetime.fromisoformat(datetime_attr)
                    a_year, a_month = pub_dt.year, pub_dt.month
                    publish_date_str = pub_dt.strftime("%Y-%m-%d")
                except ValueError:
                    logger.warning(f"Could not parse date: {datetime_attr}")
                    continue

                title_a = article.select_one("h3.entry-title a")
                if not title_a:
                    continue
                    
                title = title_a.text.strip()
                href = title_a["href"]

                # Compare article month with target month
                if (a_year > t_year) or (a_year == t_year and a_month > t_month):
                    # Article is newer than target month, keep going down
                    continue
                elif (a_year < t_year) or (a_year == t_year and a_month < t_month):
                    # Article is older than target month, stop completely!
                    logger.info(f"Reached an older month ({a_year}-{a_month:02d}). Stopping pagination.")
                    should_stop = True
                    break
                else:
                    # Article is exactly in the target month!
                    # Check Supabase Cache
                    try:
                        db_res = supabase.table("summaries").select("id").eq("content_url", href).execute()
                        if db_res.data:
                            logger.info(f"Cache HIT (Skipping): {title}")
                            cached_count += 1
                            continue
                    except Exception as e:
                        logger.error(f"Supabase cache lookup error for {href}: {e}")

                    # Cache Miss -> Crawl & Summarize
                    logger.info(f"Cache MISS: Processing '{title}'...")
                    detail_content = await fetch_article_content(href, client)
                    if not detail_content:
                        continue

                    summary_text = await generate_summary(detail_content)
                    if not summary_text:
                        logger.error(f"Failed to generate summary for {href}. Skipping.")
                        continue

                    # Insert to Supabase
                    insert_data = {
                        "title": title,
                        "content_url": href,
                        "summary_text": summary_text,
                        "target_date": publish_date_str
                    }
                    try:
                        supabase.table("summaries").insert(insert_data).execute()
                        logger.info(f"Successfully saved to Supabase: {href}")
                        processed_count += 1
                    except Exception as e:
                        logger.error(f"Failed to insert into Supabase: {e}")

            if should_stop:
                break
                
            page += 1

    logger.info("=========================================")
    logger.info(f"Crawler finished for {target_month}.")
    logger.info(f"Total newly processed & summarized: {processed_count}")
    logger.info(f"Total skipped (already cached): {cached_count}")
    logger.info("=========================================")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Monthly Script for News Factory Transcript Crawling")
    parser.add_argument("month", type=str, help="Target month in YYYY-MM format (e.g., 2026-05)")
    args = parser.parse_args()

    asyncio.run(crawl_monthly(args.month))
