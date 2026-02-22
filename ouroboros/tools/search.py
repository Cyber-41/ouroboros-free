"""Web search tool.

Provider chain (first available key wins):
  1. Tavily      — TAVILY_API_KEY      (1000 req/month, AI-optimised results)
  2. SerpAPI     — SERPAPI_API_KEY     (100 req/month, Google results)
  3. DuckDuckGo  — no key required     (unlimited, fallback of last resort)
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from ouroboros.tools.registry import ToolContext, ToolEntry


# ---------------------------------------------------------------------------
# Provider implementations
# Each returns (results_text, error_or_None)
# ---------------------------------------------------------------------------

def _search_tavily(query: str) -> Tuple[Optional[str], Optional[str]]:
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        return None, "no_key"

    try:
        import urllib.request, json
        payload = json.dumps({
            "api_key": api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": 5,
            "include_answer": True,
        }).encode()
        req = urllib.request.Request(
            "https://api.tavily.com/search",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        # Tavily returns {"answer": "...", "results": [{title, url, content}]}
        answer = data.get("answer", "")
        results = data.get("results", [])
        snippets = [
            f"[{r.get('title','')}]({r.get('url','')}): {r.get('content','')[:300]}"
            for r in results[:5]
        ]
        text = (f"{answer}\n\n" if answer else "") + "\n".join(snippets)
        return text.strip() or "(no results)", None

    except urllib.error.HTTPError as e:
        if e.code == 429:
            return None, "rate_limit"
        return None, f"http_{e.code}"
    except Exception as e:
        return None, repr(e)


def _search_serpapi(query: str) -> Tuple[Optional[str], Optional[str]]:
    api_key = os.environ.get("SERPAPI_API_KEY", "")
    if not api_key:
        return None, "no_key"

    try:
        params = urllib.parse.urlencode({
            "q": query,
            "api_key": api_key,
            "num": 5,
            "output": "json",
        })
        url = f"https://serpapi.com/search.json?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "Ouroboros/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        # SerpAPI: answer_box (if present) + organic_results
        parts = []
        box = data.get("answer_box", {})
        if box.get("answer"):
            parts.append(box["answer"])
        elif box.get("snippet"):
            parts.append(box["snippet"])

        for r in data.get("organic_results", [])[:5]:
            title = r.get("title", "")
            link = r.get("link", "")
            snippet = r.get("snippet", "")
            parts.append(f"[{title}]({link}): {snippet}")

        text = "\n".join(parts)
        return text.strip() or "(no results)", None

    except urllib.error.HTTPError as e:
        if e.code in (429, 403):
            return None, "rate_limit"
        return None, f"http_{e.code}"
    except Exception as e:
        return None, repr(e)


def _search_duckduckgo(query: str) -> Tuple[Optional[str], Optional[str]]:
    """DuckDuckGo Instant Answer API — no key, no signup, limited to instant answers."""
    try:
        params = urllib.parse.urlencode({
            "q": query,
            "format": "json",
            "no_html": 1,
            "skip_disambig": 1,
        })
        url = f"https://api.duckduckgo.com/?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "Ouroboros/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        parts = []
        if data.get("AbstractText"):
            parts.append(data["AbstractText"])
        for r in data.get("RelatedTopics", [])[:5]:
            if isinstance(r, dict) and r.get("Text"):
                parts.append(r["Text"])

        text = "\n".join(parts)
        return text.strip() or "(no instant answer — try a more specific query)", None

    except Exception as e:
        return None, repr(e)


# ---------------------------------------------------------------------------
# Tool handler
# ---------------------------------------------------------------------------

def _web_search(ctx: ToolContext, query: str) -> str:
    """
    Search the web using available providers in priority order:
    Tavily -> SerpAPI -> DuckDuckGo
    """
    providers = [
        ("tavily",     _search_tavily),
        ("serpapi",    _search_serpapi),
        ("duckduckgo", _search_duckduckgo),
    ]

    last_error = None
    for name, fn in providers:
        result, error = fn(query)

        if result is not None:
            # Success — note which provider was used
            return json.dumps({
                "provider": name,
                "query": query,
                "answer": result,
            }, ensure_ascii=False, indent=2)

        if error == "no_key":
            # No key configured — silently skip to next
            continue

        if error == "rate_limit":
            # Quota exhausted — try next provider
            last_error = f"{name}: rate limit / quota exhausted"
            continue

        # Unexpected error — log and try next
        last_error = f"{name}: {error}"
        continue

    return json.dumps({
        "error": "All search providers failed or unavailable.",
        "last_error": last_error,
        "hint": "Set TAVILY_API_KEY or SERPAPI_API_KEY in Colab Secrets.",
    }, ensure_ascii=False, indent=2)


def get_tools() -> List[ToolEntry]:
    return [
        ToolEntry("web_search", {
            "name": "web_search",
            "description": (
                "Search the web. Uses Tavily (primary), SerpAPI (fallback), "
                "or DuckDuckGo (last resort). Returns JSON with provider, query, answer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                },
                "required": ["query"],
            },
        }, _web_search),
    ]
