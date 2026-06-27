"""
agents/idea_engine.py — generates video ideas using LLM + trend signals.

Sources it pulls from:
  1. YouTube search (public, no auth) for trending titles in the niche
  2. Google Trends RSS feed (no API key needed)
  3. Your own channel's comment sentiment (via review agent output)
  4. Claude synthesises all signals into ranked ideas
"""

import requests, json, re
from urllib.parse import quote_plus
from config import CHANNEL_NICHE, CHANNEL_STYLE, TARGET_AUDIENCE
from utils.db import get_strategy, save_ideas, pending_idea_count
from utils.llm import llm_complete
from utils.overrides import get_overrides, override, get_banned_topics, get_required_keywords


# ── Trend Signals ─────────────────────────────────────────────────────────────

def fetch_youtube_trending_titles(niche: str, max_results: int = 20) -> list[str]:
    """
    Scrapes YouTube search suggestion API (no key needed).
    Returns a list of suggested search phrases related to the niche.
    """
    url = f"https://suggestqueries.google.com/complete/search?client=youtube&ds=yt&q={quote_plus(niche)}"
    try:
        resp = requests.get(url, timeout=10)
        data = json.loads(resp.text[resp.text.index("(") + 1 : resp.text.rindex(")")])
        suggestions = [item[0] for item in data[1]]
        return suggestions[:max_results]
    except Exception as e:
        print(f"[IdeaEngine] Trend fetch failed: {e}")
        return []


def fetch_google_trends_rss(niche_keyword: str) -> list[str]:
    """Pulls Google Trends daily trending searches RSS (no API key)."""
    url = f"https://trends.google.com/trends/trendingsearches/daily/rss?geo=US"
    try:
        resp = requests.get(url, timeout=10)
        titles = re.findall(r"<title><!\[CDATA\[(.+?)\]\]></title>", resp.text)
        # filter for ones loosely related to niche keywords
        niche_words = set(niche_keyword.lower().split())
        relevant = [t for t in titles if any(w in t.lower() for w in niche_words)]
        return relevant[:10] or titles[:10]  # fallback to top 10 if no match
    except Exception as e:
        print(f"[IdeaEngine] Google Trends fetch failed: {e}")
        return []


# ── LLM Idea Generation ───────────────────────────────────────────────────────

def generate_ideas(n: int = 10) -> list[dict]:
    OV = get_overrides()
    strategy = get_strategy()

    banned    = get_banned_topics(OV)
    required  = get_required_keywords(OV)
    bias      = override(OV, "idea_scoring_bias", "")
    style     = override(OV, "channel_style", CHANNEL_STYLE)
    title_rules = override(OV, "title_rules", "")

    yt_trends = fetch_youtube_trending_titles(CHANNEL_NICHE)
    google_trends = fetch_google_trends_rss(CHANNEL_NICHE.split()[0])

    banned_clause    = f"\nDO NOT generate ideas about: {banned}" if banned else ""
    required_clause  = f"\nEnsure ideas relate to these keywords: {required}" if required else ""
    bias_clause      = f"\nScoring priority: {bias}" if bias else ""
    title_clause     = f"\nTitle rules from manager: {title_rules}" if title_rules else ""

    prompt = f"""You are a YouTube content strategist for a channel about: {CHANNEL_NICHE}
Target audience: {TARGET_AUDIENCE}
Channel style: {style}

CHANNEL STRATEGY MEMO (learned from past performance):
{strategy}

TRENDING SEARCH SIGNALS:
YouTube suggestions: {json.dumps(yt_trends)}
Google Trends: {json.dumps(google_trends)}
{banned_clause}{required_clause}{bias_clause}{title_clause}

Generate {n} video ideas that:
- Are specific and searchable (good SEO)
- Have a compelling hook (first 5 seconds concept)
- Fill content gaps or ride trends
- Suit the channel style and audience

Return ONLY valid JSON — an array of objects, no markdown, no preamble:
[
  {{
    "title": "Exact YouTube title (max 70 chars, includes keyword)",
    "hook": "First 5-second hook script line",
    "keywords": ["keyword1", "keyword2", "keyword3"],
    "score": 8.5,
    "reason": "One sentence why this will perform well"
  }}
]
"""

    raw = llm_complete(prompt, max_tokens=2000)
    raw = re.sub(r"^```json\s*|```$", "", raw, flags=re.MULTILINE).strip()
    raw = re.sub(r"[\x00-\x1f]", "", raw)

    try:
        ideas = json.loads(raw)
        print(f"[IdeaEngine] Generated {len(ideas)} ideas.")
        return ideas
    except json.JSONDecodeError as e:
        print(f"[IdeaEngine] JSON parse error: {e}\nRaw: {raw[:300]}")
        return []


# ── Main callable ─────────────────────────────────────────────────────────────

def run_idea_engine(target_pending: int = 15):
    """Top up the idea queue until we have at least target_pending pending ideas."""
    current = pending_idea_count()
    print(f"[IdeaEngine] {current} pending ideas in queue.")
    if current >= target_pending:
        print("[IdeaEngine] Queue full. Skipping.")
        return

    needed = target_pending - current
    ideas = generate_ideas(n=max(needed, 10))
    save_ideas(ideas)
    print(f"[IdeaEngine] Saved {len(ideas)} new ideas to DB.")


if __name__ == "__main__":
    run_idea_engine()
