"""
agents/review_agent.py — weekly review of channel performance.

What it does:
  1. Pulls stats for all published videos (views, likes, comments)
  2. Fetches recent comments and analyses sentiment
  3. Identifies what's working and what's not
  4. Rewrites the strategy memo used by the Idea Engine
  5. Flags any videos that need attention (low CTR, comments disabled, etc.)
"""

import json
from config import CHANNEL_NICHE, CHANNEL_NAME
from utils.db import get_published_videos, update_video_stats, save_strategy, get_strategy
from utils.youtube_api import get_video_stats, get_recent_comments
from utils.llm import llm_complete


# ── Refresh Stats ─────────────────────────────────────────────────────────────

def refresh_all_stats():
    """Pull latest YouTube stats for every published video."""
    videos = get_published_videos()
    if not videos:
        print("[ReviewAgent] No published videos yet.")
        return []

    ids = [v["youtube_id"] for v in videos if v.get("youtube_id")]
    stats = get_video_stats(ids)
    stats_map = {s["youtube_id"]: s for s in stats}

    for v in videos:
        s = stats_map.get(v["youtube_id"], {})
        if s:
            update_video_stats(
                youtube_id=v["youtube_id"],
                views=s.get("views", 0),
                likes=s.get("likes", 0),
                comments=s.get("comments", 0),
                avg_watch_pct=0  # Requires Analytics API — set to 0 if not enabled
            )
    print(f"[ReviewAgent] Stats refreshed for {len(stats)} videos.")
    return videos


# ── Comment Harvest ───────────────────────────────────────────────────────────

def harvest_comments(videos: list[dict], max_per_video: int = 30) -> dict[str, list[str]]:
    """Returns {youtube_id: [comment, ...]} for recent videos."""
    result = {}
    for v in videos[-10:]:  # Only check the 10 most recent
        yt_id = v.get("youtube_id")
        if yt_id:
            comments = get_recent_comments(yt_id, max_results=max_per_video)
            result[yt_id] = comments
    return result


# ── LLM Analysis ──────────────────────────────────────────────────────────────

def analyse_and_update_strategy(videos: list[dict], comments: dict[str, list[str]]):
    """Send all data to the LLM; get back an updated strategy memo."""
    current_strategy = get_strategy()

    # Build a compact performance summary
    perf_summary = []
    for v in videos[-20:]:  # Last 20 videos
        yt_id = v.get("youtube_id", "")
        video_comments = comments.get(yt_id, [])
        perf_summary.append({
            "title": v["title"],
            "views": v.get("views", 0),
            "likes": v.get("likes", 0),
            "comments_count": v.get("comments", 0),
            "sample_comments": video_comments[:5],
            "published_at": v.get("published_at", ""),
        })

    prompt = f"""You are the channel manager for "{CHANNEL_NAME}" — a YouTube channel about {CHANNEL_NICHE}.

CURRENT STRATEGY MEMO:
{current_strategy}

PERFORMANCE DATA (last 20 videos):
{json.dumps(perf_summary, indent=2)}

Analyse this data carefully and do the following:

1. Identify the top 3 performing video types/topics and WHY they worked.
2. Identify the 2-3 topics/formats that underperformed and WHY.
3. Note any recurring themes in the comments (requests, questions, complaints).
4. Spot any surprising results.

Then write an UPDATED STRATEGY MEMO (300-500 words) that:
- Gives concrete guidance on what topics/formats to prioritise next
- Notes what to avoid or improve
- Includes specific audience insights from the comments
- Is written in actionable bullet-point style

Return ONLY the updated memo text — no JSON wrapper, no preamble.
"""

    new_memo = llm_complete(prompt, max_tokens=1000)
    save_strategy(new_memo)
    print("[ReviewAgent] Strategy memo updated.")
    return new_memo


# ── Health Check ──────────────────────────────────────────────────────────────

def channel_health_check(videos: list[dict]) -> list[str]:
    """Returns a list of human-readable alerts."""
    alerts = []
    if not videos:
        alerts.append("[!] No videos published yet.")
        return alerts

    recent = videos[-5:]
    avg_views = sum(v.get("views", 0) for v in recent) / len(recent)

    if avg_views < 100:
        alerts.append(f"[!] Low average views on last 5 videos: {avg_views:.0f}. Consider improving thumbnails and titles.")

    zero_likes = [v["title"] for v in recent if v.get("likes", 0) == 0]
    if zero_likes:
        alerts.append(f"[!] Videos with 0 likes: {zero_likes}")

    missing_thumb = [v["title"] for v in recent if not v.get("thumbnail_path")]
    if missing_thumb:
        alerts.append(f"[!] Videos missing custom thumbnails: {missing_thumb}")

    if len(videos) < 5:
        alerts.append("[!] Channel is young. Keep publishing consistently.")

    if not alerts:
        alerts.append("[OK] Channel health looks good.")

    return alerts


# ── Main callable ─────────────────────────────────────────────────────────────

def run_review_agent():
    print("[ReviewAgent] Starting weekly review...")
    videos = refresh_all_stats()
    comments = harvest_comments(videos)
    alerts = channel_health_check(videos)

    print("\n── Channel Health ──")
    for alert in alerts:
        print(" ", alert)

    if videos:
        new_strategy = analyse_and_update_strategy(videos, comments)
        print("\n── Updated Strategy Memo (first 400 chars) ──")
        print(new_strategy[:400] + "...")
    else:
        print("[ReviewAgent] Not enough data to update strategy yet.")

    print("\n[ReviewAgent] Review complete.")


if __name__ == "__main__":
    run_review_agent()
