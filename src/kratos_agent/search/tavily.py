"""Optional Tavily API provider for Kratos Search Fabric."""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.parse
import urllib.request
from typing import Any

from .citations import attach_citations
from .models import SearchResponse, SearchResult
from .provider import SearchProvider

logger=logging.getLogger(__name__)

class TavilySearchProvider(SearchProvider):
    """Direct Tavily REST provider, enabled when TAVILY_API_KEY is configured."""
    def __init__(self, api_key: str | None=None, base_url: str | None=None)->None:
        self.api_key=(api_key or os.environ.get("TAVILY_API_KEY","")).strip()
        self.base_url=(base_url or os.environ.get("KRATOS_TAVILY_URL") or "https://api.tavily.com").rstrip("/")
    @property
    def name(self)->str: return "tavily"
    @property
    def configured(self)->bool: return bool(self.api_key)
    async def is_available(self)->bool: return self.configured
    async def search(self, query: str, *, category: str | None=None, domains: list[str] | None=None, language: str | None=None, max_results: int=10)->SearchResponse:
        started=time.monotonic()
        if not self.api_key:
            return SearchResponse(query=query,results=[],total_results=0,provider=self.name,latency_ms=0.0,metadata={"error":"TAVILY_API_KEY is not configured."})
        payload: dict[str,Any]={"api_key":self.api_key,"query":query,"search_depth":"advanced","max_results":max(1,min(int(max_results),20)),"include_answer":True,"include_raw_content":False}
        if domains: payload["include_domains"]=domains
        try:
            req=urllib.request.Request(f"{self.base_url}/search",data=json.dumps(payload).encode(),headers={"User-Agent":"KratosSearchFabric/1.0","Content-Type":"application/json","Accept":"application/json"})
            with urllib.request.urlopen(req,timeout=15.0) as resp: data=json.loads(resp.read().decode("utf-8","replace"))
            results=[]
            for idx,item in enumerate(data.get("results",[])[:max_results],1):
                url=str(item.get("url") or "")
                results.append(SearchResult(title=str(item.get("title") or "Untitled"),url=url,snippet=str(item.get("content") or item.get("snippet") or ""),source=self.name,score=float(item.get("score",0.0) or 0.0),rank=idx,domain=urllib.parse.urlparse(url).netloc,published_at=item.get("published_date"),content=item.get("raw_content")))
            return SearchResponse(query=query,results=results,total_results=len(results),provider=self.name,latency_ms=(time.monotonic()-started)*1000,answer=data.get("answer"),citations=attach_citations(results))
        except Exception as exc:
            logger.warning("[TavilySearchProvider] query failed: %s",exc)
            return SearchResponse(query=query,results=[],total_results=0,provider=self.name,latency_ms=(time.monotonic()-started)*1000,metadata={"error":str(exc)})
