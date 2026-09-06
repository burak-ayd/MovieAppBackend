import os
import httpx
from typing import Optional, Dict, Any
from rapidfuzz import fuzz

class TMDBClient:
    def __init__(self):
        self.api_key = os.getenv("TMDB_API_KEY", "")
        self.base_url = "https://api.themoviedb.org/3"
        self.client = httpx.AsyncClient(timeout=10.0)

    async def find_by_imdb_id(self, imdb_id: str) -> Optional[Dict[str, Any]]:
        url = f"{self.base_url}/find/{imdb_id}"
        resp = await self.client.get(url, params={"api_key": self.api_key, "external_source": "imdb_id"})
        if resp.status_code == 200:
            data = resp.json()
            if data.get("movie_results"):
                return {"media_type": "movie", "data": data["movie_results"][0]}
            if data.get("tv_results"):
                return {"media_type": "tv", "data": data["tv_results"][0]}
        return None

    async def search_best_match(self, title: str, year: Optional[int] = None) -> Optional[Dict[str, Any]]:
        params = {"api_key": self.api_key, "query": title, "language": "tr-TR"}
        if year:
            params["year"] = year

        resp = await self.client.get(f"{self.base_url}/search/multi", params=params)
        if resp.status_code != 200:
            return None

        results = resp.json().get("results", [])
        best_cand = None
        best_score = 0.0

        for item in results:
            target_title = item.get("title") or item.get("name") or ""
            score = fuzz.token_sort_ratio(title.lower(), target_title.lower())
            if score > best_score:
                best_score = score
                best_cand = item

        return best_cand if best_score >= 80.0 else None
