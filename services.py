import httpx
from bs4 import BeautifulSoup
from google import genai
from datetime import datetime

from config import settings, logger
from database import supabase
from models import SummaryItem

gemini_client = genai.Client(api_key=settings.GEMINI_API_KEY)

async def fetch_article_content(url: str, client: httpx.AsyncClient) -> str:
    """Crawls the detailed interview transcript page and extracts the text content."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }
    try:
        response = await client.get(url, headers=headers, follow_redirects=True, timeout=15.0)
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to fetch article detail page {url}: {e}")
        return ""

    soup = BeautifulSoup(response.text, "html.parser")
    content_div = soup.select_one(".post-content, .entry-content, .w-post-elm.post_content")
    if not content_div:
        logger.warning(f"Could not find transcript content container at {url}, attempting fallback.")
        paragraphs = soup.find_all("p")
        if paragraphs:
            return "\n".join([p.get_text().strip() for p in paragraphs if p.get_text().strip()])
        return ""

    return content_div.get_text("\n").strip()

async def generate_summary(text: str) -> str:
    """Calls Gemini API (gemini-3.1-flash-lite) to summarize the interview transcript."""
    prompt = "이 뉴스 인터뷰 전문을 읽고 핵심 내용 3줄 요약 및 주요 참석자 정보를 빈티지하고 정갈한 톤으로 요약해줘."
    full_prompt = f"{prompt}\n\n[전문]\n{text}"

    try:
        response = await gemini_client.aio.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=full_prompt
        )
        if not response.text:
            raise ValueError("Empty response received from Gemini API")
        return response.text.strip()
    except Exception as e:
        logger.error(f"Gemini API call failed: {e}")
        return ""

async def fetch_and_summarize_daily(target_date: str) -> list[SummaryItem]:
    """
    Fallback function for API requests:
    Crawls the first page of the transcript list to find any articles matching target_date.
    If found, summarizes and saves to DB. Returns the newly created SummaryItems.
    """
    base_url = "https://humblefactory.co.kr/category/transcript/"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }
    
    new_summaries = []
    
    try:
        # Validate date string format
        datetime.strptime(target_date, "%Y-%m-%d")
    except ValueError:
        logger.error(f"Invalid date format: {target_date}")
        return []

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(base_url, headers=headers, follow_redirects=True, timeout=15.0)
            response.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to fetch transcript list page: {e}")
            return []
            
        soup = BeautifulSoup(response.text, "html.parser")
        articles = soup.find_all("article")
        
        for article in articles:
            time_tag = article.find("time")
            if not time_tag: continue
            
            datetime_attr = time_tag.get("datetime", "")
            if not datetime_attr: continue
            
            try:
                pub_dt = datetime.fromisoformat(datetime_attr)
                publish_date_str = pub_dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
                
            if publish_date_str != target_date:
                # We only care about finding articles on the exact target date
                continue
                
            title_a = article.select_one("h3.entry-title a")
            if not title_a: continue
            
            title = title_a.text.strip()
            href = title_a["href"]
            
            # Double check to prevent dupes in case another process inserted it
            try:
                db_res = supabase.table("summaries").select("id").eq("content_url", href).execute()
                if db_res.data:
                    logger.info(f"Fallback: Article already cached: {title}")
                    continue
            except Exception:
                pass
                
            logger.info(f"Fallback Cache MISS: Real-time processing for '{title}'...")
            detail_content = await fetch_article_content(href, client)
            if not detail_content: continue
            
            summary_text = await generate_summary(detail_content)
            if not summary_text: continue
            
            insert_data = {
                "title": title,
                "content_url": href,
                "summary_text": summary_text,
                "target_date": publish_date_str
            }
            try:
                supabase.table("summaries").insert(insert_data).execute()
                logger.info(f"Successfully saved real-time summary to Supabase: {href}")
                new_summaries.append(SummaryItem(
                    title=title,
                    content_url=href,
                    summary=summary_text,
                    publish_date=publish_date_str
                ))
            except Exception as e:
                logger.error(f"Failed to insert into Supabase: {e}")
                
    return new_summaries
