from pydantic import BaseModel

class SummaryItem(BaseModel):
    title: str
    content_url: str
    summary: str
    publish_date: str
