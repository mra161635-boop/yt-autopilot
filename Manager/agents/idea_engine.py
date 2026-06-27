"""
agents/idea_engine.py — generates video ideas using Claude + trend signals.
Respects Gemini Manager directives: banned topics, required keywords, scoring bias.
"""

import requests, json, re
from urllib.parse import quote_plus
from anthropic import Anthropic
from config import ANTHROPIC_API_KEY, CHANNEL_NICHE, CHANNEL_STYLE, TARGET_AUDIENCE, CLAUDE_MODEL
from utils.db import get_strategy, save_ideas, pending_idea_count
from utils.overrides import get_overrides, override, get_banned_topics, get_required_keywords

client = Anthropic(api_key=ANTHROPIC_API_KEY)


def fetch_youtube_trending_titles(niche: str, max_results: int = 20) -> list[str]:
    url = f"https://suggestqueries.google.com/complete/search?client=youtube&ds=yt&q={quote_plus(niche)}"
    try:
        resp = requests.get(url, timeout=10)
        data = json.loads(resp.text[resp.text.index("(") + 1 : resp.text.rindex(")")])
        return [item[0] for item in data[1]][:max_results]
    except Exception as e:
        print(f"[IdeaEngine] Trend fetch failed: {e}")
        return []


def fetch_google_trends_rss(niche_keyword: str) -> list[str]:
    url = "https://trends.google.com/trends/trendingsearches/daily/rss?geo=US"
    try:
        resp = requests.get(url, timeout=10)
        titles = re.findall(r"<title><!\[CDATA\[(.+?)\]\]></title>", resp.text)
        niche_words = set(niche_keyword.lower().split())
        relevant = [t for t in titles if any(w in t.lower() for w in niche_words)]
        return relevant[:10] or titles[:10]
    except Exception as e:
        print(f"[IdeaEngine] Google Trends failed: {e}")
        return []


def generate_ideas(n: int = 10) -> list[dict]:
    OV = get_overrides()
    strategy = get_strategy()
    if isinstance(strategy, dict):
        strategy = strategy.get("strategy_text", "No strategy yet.")

    banned    = get_banned_topics(OV)
    required  = get_required_keywords(OV)
    bias      = override(OV, "idea_scoring_bias", "")
    style     = override(OV, "channel_style", CHANNEL_STYLE)
    title_rules = override(OV, "title_rules", "")

    yt_trends     = fetch_youtube_trending_titles(CHANNEL_NICHE)
    google_trends = fetch_google_trends_rss(CHANNEL_NICHE.split()[0])

    banned_clause    = f"\nDO NOT generate ideas about: {banned}" if banned else ""
    required_clause  = f"\nEnsure ideas relate to these keywords: {required}" if required else ""
    bias_clause      = f"\nScoring priority: {bias}" if bias else ""
    title_clause     = f"\nTitle rules from manager: {title_rules}" if title_rules else ""

    prompt = f"""You are a YouTube content strategist for a channel about: {CHANNEL_NICHE}
Target audience: {TARGET_AUDIENCE}
Channel style: {style}

CHANNEL STRATEGY MEMO:
{strategy}

TRENDING SIGNALS:
YouTube: {json.dumps(yt_trends)}
Google:  {json.dumps(google_trends)}
{banned_clause}{required_clause}{bias_clause}{title_clause}

Generate {n} video ideas. Return ONLY valid JSON array:
[
  {{
    "title": "Exact YouTube title (max 70 chars, keyword-rich)",
    "hook": "First 5-second hook script line",
    "keywords": ["keyword1", "keyword2", "keyword3"],
    "score": 8.5,
    "reason": "One sentence why this will perform well"
  }}
]"""

    resp = client.messages.create(
        model=CLAUDE_MODEL, max_tokens=2000,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = resp.content[0].text.strip()
    raw = re.sub(r"^```json\s*|```$", "", raw, flags=re.MULTILINE).strip()

    try:
        ideas = json.loads(raw)
        print(f"[IdeaEngine] Generated {len(ideas)} ideas.")
        return ideas
    except json.JSONDecodeError as e:
        print(f"[IdeaEngine] JSON error: {e}")
        return []


def run_idea_engine(target_pending: int = 15):
    current = pending_idea_count()
    print(f"[IdeaEngine] {current} pending ideas in queue.")
    if current >= target_pending:
        print("[IdeaEngine] Queue full. Skipping.")
        return
    ideas = generate_ideas(n=max(target_pending - current, 10))
    save_ideas(ideas)
    print(f"[IdeaEngine] Saved {len(ideas)} new ideas.")


if __name__ == "__main__":
    run_idea_engine()
