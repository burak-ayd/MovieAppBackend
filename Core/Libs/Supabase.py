import os
from supabase import create_client, Client
from typing import List, Dict, Any, Optional

class SupabaseManager:
    def __init__(self):
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_KEY", "")
        self.client: Client = create_client(url, key)

    def upsert_media(self, media_record: Dict[str, Any]):
        self.client.table("media").upsert(media_record, on_conflict="id").execute()

    def upsert_source(self, media_id: str, provider: str, page_url: str, title: str):
        payload = {
            "media_id": media_id,
            "provider": provider,
            "page_url": page_url,
            "title_scraped": title
        }
        self.client.table("sources").upsert(
            payload,
            on_conflict="provider, page_url",
            ignore_duplicates=True
        ).execute()

    def get_crawler_state(self, provider: str) -> Optional[Dict[str, Any]]:
        res = self.client.table("crawler_state").select("*").eq("provider", provider).execute()
        return res.data[0] if res.data else None

    def update_crawler_state(self, provider: str, backfill_page: int, is_completed: bool = False):
        self.client.table("crawler_state").upsert({
            "provider": provider,
            "backfill_page": backfill_page,
            "is_backfill_completed": is_completed
        }).execute()
