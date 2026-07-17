import os
import httpx
from bs4 import BeautifulSoup
from .log import log_tool_usage

USER_AGENT = "aureon-agent/0.1 (+https://github.com/vkkatariya/aureon-agent)"

async def web_search(query: str, max_results: int = 5) -> list:
    """
    Search using DuckDuckGo HTML or Brave API (if configured).
    Returns list of dicts: [{'title': ..., 'url': ..., 'snippet': ...}]
    """
    brave_api_key = os.getenv("BRAVE_API_KEY")
    headers = {"User-Agent": USER_AGENT}
    
    if brave_api_key:
        # Brave Search API (v2)
        try:
            url = "https://api.search.brave.com/res/v1/web/search"
            headers["Accept"] = "application/json"
            headers["X-Subscription-Token"] = brave_api_key
            
            async with httpx.AsyncClient() as client:
                res = await client.get(url, headers=headers, params={"q": query, "count": max_results}, timeout=10)
                res.raise_for_status()
                data = res.json()
                
                results = []
                for item in data.get("web", {}).get("results", [])[:max_results]:
                    results.append({
                        "title": item.get("title", ""),
                        "url": item.get("url", ""),
                        "snippet": item.get("description", "")
                    })
                log_tool_usage("web_search", {"query": query, "backend": "brave"}, f"Found {len(results)} results", "success")
                return results
        except Exception as e:
            log_tool_usage("web_search", {"query": query, "backend": "brave"}, str(e), "error")
            return [{"error": f"Brave Search API error: {e}"}]
    else:
        # DuckDuckGo HTML fallback (v1)
        try:
            url = "https://html.duckduckgo.com/html/"
            async with httpx.AsyncClient() as client:
                res = await client.post(url, headers=headers, data={"q": query}, timeout=10)
                res.raise_for_status()
                
                soup = BeautifulSoup(res.text, 'html.parser')
                results = []
                for result in soup.find_all('div', class_='result')[:max_results]:
                    title_elem = result.find('a', class_='result__url')
                    snippet_elem = result.find('a', class_='result__snippet')
                    
                    if title_elem and snippet_elem:
                        results.append({
                            "title": title_elem.text.strip(),
                            "url": title_elem.get('href', ''),
                            "snippet": snippet_elem.text.strip()
                        })
                log_tool_usage("web_search", {"query": query, "backend": "duckduckgo"}, f"Found {len(results)} results", "success")
                return results
        except Exception as e:
            log_tool_usage("web_search", {"query": query, "backend": "duckduckgo"}, str(e), "error")
            return [{"error": f"DuckDuckGo Search error: {e}"}]

async def web_fetch(url: str, max_chars: int = 5000) -> str:
    """
    Fetch a webpage and return text content.
    Respects robots.txt by default unless AUREON_WEB_IGNORE_ROBOTS=1.
    """
    headers = {"User-Agent": USER_AGENT}
    ignore_robots = os.getenv("AUREON_WEB_IGNORE_ROBOTS") == "1"
    
    if not ignore_robots:
        # Quick and dirty robots.txt check
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
            
            async with httpx.AsyncClient() as client:
                res = await client.get(robots_url, headers=headers, timeout=5)
                if res.status_code == 200:
                    # Very basic check, proper parsing requires urllib.robotparser, but this is async
                    if "Disallow: /" in res.text and "User-agent: *" in res.text:
                        log_tool_usage("web_fetch", {"url": url}, "Blocked by robots.txt", "error")
                        return "Error: Access blocked by robots.txt"
        except Exception:
            pass # Ignore robots check failures
    else:
        import logging
        logging.getLogger(__name__).warning("AUREON_WEB_IGNORE_ROBOTS is enabled, ignoring robots.txt")
            
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(url, headers=headers, timeout=30, follow_redirects=True)
            res.raise_for_status()
            
            # Use BeautifulSoup to extract text
            soup = BeautifulSoup(res.text, 'html.parser')
            # Remove scripts and styles
            for script in soup(["script", "style"]):
                script.extract()
                
            text = soup.get_text(separator='\n')
            
            # Collapse whitespace
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = '\n'.join(chunk for chunk in chunks if chunk)
            
            if len(text) > max_chars:
                text = text[:max_chars] + f"\n...[TRUNCATED to {max_chars} chars]..."
                
            log_tool_usage("web_fetch", {"url": url}, f"Fetched {len(text)} chars", "success")
            return text
    except Exception as e:
        log_tool_usage("web_fetch", {"url": url}, str(e), "error")
        return f"Error fetching webpage: {e}"
