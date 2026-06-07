from datetime import datetime, timezone, timedelta
from typing import List, Optional

from fastapi import FastAPI, Query
from config import logger
from database import supabase
from models import SummaryItem
from services import fetch_and_summarize_daily

app = FastAPI(
    title="News Factory Transcript Summary Service",
    description="FastAPI backend serving cached transcripts of '김어준의 겸손은힘들다 뉴스공장'",
    version="1.0.0"
)

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

    summaries = []
    
    try:
        # Step 1: Query Supabase cache directly (no crawling)
        db_res = supabase.table("summaries").select("*").eq("target_date", date).execute()
        cached_records = db_res.data
        
        for record in cached_records:
            summaries.append(SummaryItem(
                title=record.get("title", ""),
                content_url=record.get("content_url", ""),
                summary=record.get("summary_text", ""),
                publish_date=str(record.get("target_date", date))
            ))
            
        logger.info(f"Returned {len(summaries)} cached records from DB for date {date}.")
        
        # Fallback: if DB has no data, attempt real-time scraping
        if not summaries:
            logger.info(f"No records found for {date} in DB. Initiating real-time fallback crawling...")
            new_summaries = await fetch_and_summarize_daily(date)
            summaries.extend(new_summaries)
            if new_summaries:
                logger.info(f"Fallback added {len(new_summaries)} new summaries.")
            else:
                logger.info(f"Fallback found no articles for {date}.")
                
    except Exception as e:
        logger.error(f"Supabase query error: {e}")

    return summaries

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
