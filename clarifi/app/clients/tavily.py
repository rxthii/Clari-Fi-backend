class TavilyClient:
    def __init__(self, settings):
        self.enabled = bool(settings.tavily_api_key)
        self.key = settings.tavily_api_key

    async def search(self, query: str) -> list[dict]:
        if not self.enabled:
            return []
        from tavily import AsyncTavilyClient
        results = await AsyncTavilyClient(api_key=self.key).search(query[:300], max_results=4)
        return [{"title": str(x.get("title", ""))[:160], "content": str(x.get("content", ""))[:1200], "url": str(x.get("url", ""))[:400]} for x in results.get("results", [])]

