import json, os, re
from datetime import datetime, timezone

from config import CHANNEL_NICHE, CHANNEL_NAME, TARGET_AUDIENCE, CHANNEL_STYLE
from utils.db import get_published_videos, get_strategy, save_strategy, get_conn, pending_idea_count
from utils.llm import llm_complete
from utils.youtube_api import (
    get_channel_stats,
    get_channel_overview,
    get_traffic_sources,
    get_device_breakdown,
    get_content_type_performance,
    get_video_analytics,
)


MODEL_HINT = "gemini-2.0-flash"  # passed to LLM for context (uses Groq-compatible provider)


def get_directives() -> dict:
    with get_conn() as c:
        row = c.execute("SELECT memo FROM strategy WHERE id=1").fetchone()
    try:
        data = json.loads(row["memo"]) if row else {}
        return data.get("directives", {})
    except (json.JSONDecodeError, TypeError):
        return {}


def save_directives(directives: dict, reasoning: str):
    with get_conn() as c:
        raw = c.execute("SELECT memo FROM strategy WHERE id=1").fetchone()
        try:
            existing = json.loads(raw["memo"]) if raw else {}
        except (json.JSONDecodeError, TypeError):
            existing = {}
        existing["directives"] = directives
        existing["last_manager_run"] = datetime.now(timezone.utc).isoformat()
        existing["last_reasoning"] = reasoning
        c.execute("UPDATE strategy SET memo=?, updated_at=? WHERE id=1",
                  (json.dumps(existing, indent=2), datetime.now(timezone.utc).isoformat()))
    print("[Manager] Directives saved.")


def log_manager_action(action_type: str, summary: str, details: str, impact: str):
    with get_conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS manager_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                action_type TEXT,
                summary     TEXT,
                details     TEXT,
                impact      TEXT,
                created_at  TEXT DEFAULT (datetime('now'))
            );
        """)
        c.execute("INSERT INTO manager_log (action_type, summary, details, impact) VALUES (?,?,?,?)",
                  (action_type, summary, details, impact))


def get_manager_log() -> list[dict]:
    with get_conn() as c:
        try:
            rows = c.execute(
                "SELECT * FROM manager_log ORDER BY created_at DESC LIMIT 50"
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []


def build_channel_report() -> dict:
    videos = get_published_videos()
    if not videos:
        return {"status": "no_videos", "videos": [], "kpis": {}}

    videos_sorted = sorted(videos, key=lambda v: v.get("published_at", ""), reverse=True)
    recent_5 = videos_sorted[:5]
    older_5  = videos_sorted[5:10] if len(videos_sorted) >= 10 else []

    recent_avg = sum(v.get("views", 0) for v in recent_5) / max(len(recent_5), 1)
    older_avg  = sum(v.get("views", 0) for v in older_5)  / max(len(older_5), 1)

    growth_trend = ("improving" if recent_avg > older_avg
                    else "declining" if recent_avg < older_avg * 0.8
                    else "stable")

    try:
        channel_stats = get_channel_stats()
    except Exception:
        channel_stats = {"subscribers": 0, "total_views": 0, "total_videos": 0}

    subs = channel_stats.get("subscribers", 0)
    if subs < 1000:
        stage = "early (0-1k subs)"
    elif subs < 10000:
        stage = "growth (1k-10k subs)"
    else:
        stage = "established (10k+ subs)"

    # ── YouTube Analytics API (28-day window) ──────────────────────────────
    overview = get_channel_overview(days=28) if videos else {}
    traffic  = get_traffic_sources(days=28)  if videos else []
    devices  = get_device_breakdown(days=28) if videos else []
    ctypes   = get_content_type_performance(days=28) if videos else {}

    def _pct(val, total):
        return round(val / total * 100, 1) if total else 0

    total_views_28d = int(overview.get("views", 0))
    traffic_summary = []
    for t in traffic:
        v = int(t.get("views", 0))
        traffic_summary.append({
            "source": t.get("insightTrafficSourceType", "unknown"),
            "views": v,
            "pct": _pct(v, total_views_28d) if total_views_28d else 0,
        })

    device_summary = []
    for d in devices:
        v = int(d.get("views", 0))
        device_summary.append({
            "device": d.get("deviceType", "unknown"),
            "views": v,
            "pct": _pct(v, total_views_28d) if total_views_28d else 0,
        })

    # ── Enrich top videos with Analytics API data ──────────────────────────
    video_data = []
    for v in videos_sorted[:20]:
        views = v.get("views", 0)
        likes = v.get("likes", 0)
        entry = {
            "title":         v.get("title", "Unknown"),
            "youtube_id":    v.get("youtube_id", ""),
            "published":     (v.get("published_at") or "")[:10],
            "views":         views,
            "likes":         likes,
            "comments":      v.get("comments", 0),
            "like_rate_pct": round(likes / views * 100, 2) if views > 0 else 0,
            "avg_watch_pct": v.get("avg_watch_pct", 0),
        }
        if entry["youtube_id"]:
            va = get_video_analytics(entry["youtube_id"], days=90)
            if va:
                entry["avg_watch_pct"] = round(float(va.get("averageViewPercentage", 0)), 1)
                entry["thumbnail_ctr"] = round(float(va.get("videoThumbnailImpressionsClickRate", 0)) * 100, 2)
                entry["shares"] = int(va.get("shares", 0))
        video_data.append(entry)

    strategy = get_strategy()
    strategy_text = strategy if isinstance(strategy, str) else json.dumps(strategy)

    current_goal = get_current_goal({
        "kpis": {"subscribers": subs, "total_videos_published": len(videos)}
    })

    return {
        "channel": {
            "name": CHANNEL_NAME, "niche": CHANNEL_NICHE,
            "target_audience": TARGET_AUDIENCE, "current_style": CHANNEL_STYLE,
        },
        "kpis": {
            "subscribers": subs,
            "channel_stage": stage,
            "next_goal": current_goal["label"] if current_goal else "All goals met",
            "next_goal_subs": current_goal["subs"] if current_goal else None,
            "total_videos_published": len(videos),
            "total_views": sum(v.get("views", 0) for v in videos),
            "total_likes": sum(v.get("likes", 0) for v in videos),
            "recent_avg_views": round(recent_avg, 1),
            "older_avg_views":  round(older_avg, 1),
            "growth_trend": growth_trend,
            "pending_ideas_in_queue": pending_idea_count(),
        },
        "analytics_28d": {
            "views":          total_views_28d,
            "watch_time_min": int(overview.get("estimatedMinutesWatched", 0)),
            "avg_view_duration_sec": int(overview.get("averageViewDuration", 0)),
            "subscribers_gained":    int(overview.get("subscribersGained", 0)),
            "subscribers_lost":      int(overview.get("subscribersLost", 0)),
            "likes":            int(overview.get("likes", 0)),
            "comments":         int(overview.get("comments", 0)),
            "shares":           int(overview.get("shares", 0)),
            "thumbnail_impressions": int(overview.get("videoThumbnailImpressions", 0)),
            "thumbnail_ctr_pct": round(float(overview.get("videoThumbnailImpressionsClickRate", 0)) * 100, 2),
            "traffic_sources":  traffic_summary,
            "device_breakdown": device_summary,
            "content_type_performance": ctypes,
        },
        "videos": video_data,
        "current_directives": get_directives(),
        "current_strategy": strategy_text[:2000],
    }


SYSTEM_PROMPT = """You are the YouTube Channel Manager for {channel_name}. Your ONLY mandate is channel growth: subscribers, views, watch time, engagement. You have full authority to change how videos are made.

CHANNEL STRATEGY KNOWLEDGE:
- Stage-based targets (determined by subscriber count in report):
  Early (0-1k subs): Prioritise volume and discovery. 3-5 Shorts/week + 2 long videos/week.
  Growth (1k-10k): 2-3 Shorts/week + 3 long videos/week. Consistency is key.
  Established (10k+): Optimise for revenue. 2 Shorts/week + 3-4 long videos/week.

- Shorts are under 60 sec, pushed aggressively by algorithm — treat as free discovery.
  Long videos (8-15 min) build watch hours for monetisation.

- Personal finance niche: long videos outperform shorts. Viewers trust deep dives.
  A 10-min "5 mistakes" video beats a 45-sec version. Skew toward long-form.

- Ideal ratio: ~1 Short for every Long video. Cut the hook section from the long video
  into a Short (auto-clip, almost zero extra production work).

ANALYTICS INTERPRETATION GUIDE:
The report includes `analytics_28d` with these dimensions. Use them to diagnose:

1. **Traffic sources** (`traffic_sources`): Where views come from.
   - `YT_SEARCH` = YouTube search results. High = good SEO/titles. Low = fix titles, tags.
   - `YT_HOME` (browse) = YouTube homepage suggestions. High = algorithm pushing your content.
   - `YT_CHANNEL` = viewers browsing your channel page. High = strong audience, consider playlists.
   - `YT_TRENDING` = on trending shelf. Rare but powerful.
   - `YT_SHORTS` = Shorts feed. High = Shorts are working for discovery.
   - `EXTERNAL` = embedded / shared off-platform. High = share-worthy content.
   - `YT_OTHER_PAGE` = suggested videos sidebar. Optimise end screens and cards.
   - Dominant source tells you where to focus. If search is low → improve titles/descriptions.
     If browse is low → algorithm isn't recommending you → improve retention/CTR.

2. **Device breakdown** (`device_breakdown`): How viewers watch.
   - `MOBILE` > 70% means most viewers are on phones → vertical thumbnails, short attention spans.
   - `DESKTOP` high means deep-dive audience → longer videos, detailed explanations.
   - `TV` high means cinematic/topical content → high production value matters.
   - Adjust video length and thumbnail design based on the dominant device.

3. **Content type performance** (`content_type_performance`): Shorts vs long-form.
   - Compare `SHORTS` and `VIDEOS` (long-form) on views, watch time, avg view duration.
   - If Shorts drive views but low watch time → use them for discovery, not retention.
   - If long-form has high avg view duration → the format resonates. Make more.

4. **Thumbnail CTR** (`thumbnail_ctr_pct`): Percentage of impressions that became views.
   - Below 2% = thumbnails are failing. Above 5% = thumbnails are strong.
   - Low CTR + high avg view duration = thumbnails are the bottleneck. Fix them.
   - High CTR + low avg view duration = thumbnails over-promise. Tone them down.

5. **Audience engagement** (subscribers_gained vs lost, likes, comments, shares):
   - Net subscriber growth = channel health signal.
   - Subscribers lost > gained in a period → content mismatch or infrequent posting.
   - Low comments despite high views → add better CTAs and prompts.
   - High shares = content is click-worthy beyond your audience.

6. **Per-video analytics** (`videos` list, `avg_watch_pct`, `thumbnail_ctr`):
   - avg_watch_pct > 60% = excellent retention. Study what those videos do differently.
   - avg_watch_pct < 30% = viewers drop off early. Fix the hook.
   - thumbnail_ctr < 2% per video means the title/thumbnail combo isn't working.

Available directives (only include what you're changing):
{{
  "directives": {{
    "video_length_min": int,
    "video_length_max": int,
    "short_length_sec": int,
    "publish_days": ["Mon",...],
    "publish_hour": int,
    "long_videos_per_week": int,
    "shorts_per_week": int,
    "auto_clip_shorts_from_long": true/false,
    "channel_style": "tone instruction",
    "banned_topics": ["topic"],
    "required_keywords": ["kw"],
    "idea_scoring_bias": "priority instruction for idea scoring",
    "script_instruction_override": "rule added to every script",
    "title_rules": "exact title format rule",
    "thumbnail_style": "visual style instruction",
    "hook_style": "exact hook format that works",
    "cta_instruction": "CTA script for all videos"
  }},
  "analysis": {{
    "growth_status": "growing|stalling|declining",
    "top_performer_pattern": "...",
    "underperformer_pattern": "...",
    "biggest_problem": "...",
    "immediate_fix": "...",
    "3_month_strategy": "...",
    "actions_taken": ["directive: reason"]
  }}
}}

Be SPECIFIC. Base every directive on the data. Cite the numbers you see (CTR, traffic source %, device %, avg watch time). Return ONLY valid JSON."""


def run_manager_analysis(report: dict) -> dict:
    prompt = SYSTEM_PROMPT.format(channel_name=report["channel"]["name"])
    prompt += f"\n\nCHANNEL REPORT:\n{json.dumps(report, indent=2)}"
    prompt += "\n\nReturn ONLY valid JSON. No markdown."
    try:
        raw = llm_complete(prompt, max_tokens=4000)
        raw = re.sub(r"^```json\s*|```$", "", raw, flags=re.MULTILINE).strip()
        raw = re.sub(r"[\x00-\x1f]", "", raw)
        return json.loads(raw)
    except Exception as e:
        print(f"[Manager] Analysis error: {e}")
        return {}


def apply_directives_to_pipeline(directives: dict):
    os.makedirs("data", exist_ok=True)
    path = "data/manager_overrides.json"
    with open(path, "w") as f:
        json.dump({
            "_updated_by": "channel_manager",
            "_updated_at": datetime.now(timezone.utc).isoformat(),
            **directives
        }, f, indent=2)
    print(f"[Manager] {len(directives)} directives to {path}")
    return path


def format_manager_report(report: dict, analysis: dict) -> str:
    kpis = report.get("kpis", {})
    a28d = report.get("analytics_28d", {})
    a    = analysis.get("analysis", {})
    d    = analysis.get("directives", {})
    lines = [
        "",
        "+------------------------------------------------------------+",
        f"|  MANAGER REPORT — {datetime.now().strftime('%Y-%m-%d %H:%M')}            |",
        "+------------------------------------------------------------+",
        f"  Channel: {report['channel']['name']}  |  Stage: {kpis.get('channel_stage','?')}",
        f"  Subs: {kpis.get('subscribers',0):,}  |  Next goal: {kpis.get('next_goal','?')}"
        f"  {kpis.get('total_videos_published',0)} videos  |  {kpis.get('total_views',0):,} views",
        f"  Growth: {kpis.get('growth_trend','---').upper()}  |  Recent avg: {kpis.get('recent_avg_views',0):,.0f} views",
        "",
        "--- 28-DAY ANALYTICS ---------------------------------------",
        f"  Views: {a28d.get('views',0):,}  |  Watch time: {a28d.get('watch_time_min',0):,} min",
        f"  Subs: +{a28d.get('subscribers_gained',0)} / -{a28d.get('subscribers_lost',0)}  |  Net: {a28d.get('subscribers_gained',0) - a28d.get('subscribers_lost',0)}",
        f"  Thumbnail CTR: {a28d.get('thumbnail_ctr_pct','?')}%  |  Avg duration: {a28d.get('avg_view_duration_sec',0)}s",
    ]
    # traffic sources
    traffic = a28d.get("traffic_sources", [])
    if traffic:
        lines.append("  Traffic:")
        for t in sorted(traffic, key=lambda x: x.get("pct", 0), reverse=True)[:5]:
            src = t.get("source", "?")[:20].replace("_", " ").title()
            lines.append(f"    {src:20s} {t.get('pct',0):5.1f}%  ({t.get('views',0):,} views)")
    # device breakdown
    devices = a28d.get("device_breakdown", [])
    if devices:
        lines.append("  Devices:")
        for d_ in sorted(devices, key=lambda x: x.get("pct", 0), reverse=True):
            dev = d_.get("device", "?")[:10].title()
            lines.append(f"    {dev:10s} {d_.get('pct',0):5.1f}%")
    lines += [
        "",
        "--- DIAGNOSIS ---------------------------------------------",
        f"  Status:          {a.get('growth_status','---')}",
        f"  - Working:       {a.get('top_performer_pattern','---')}",
        f"  - Broken:        {a.get('underperformer_pattern','---')}",
        f"  - Biggest issue: {a.get('biggest_problem','---')}",
        f"  - Fix now:       {a.get('immediate_fix','---')}",
        "",
        "--- DIRECTIVES APPLIED ------------------------------------",
    ]
    if d:
        for k, v in d.items():
            lines.append(f"  - {k}: {v}")
    else:
        lines.append("  No changes - strategy maintained.")
    lines += ["", f"  3-month: {a.get('3_month_strategy','---')}", "", "="*60]
    return "\n".join(lines)


# ── Goal Milestones ────────────────────────────────────────────────────────────

GOALS = [
    {"name": "early_start",   "subs": 10,    "label": "First 10 subs — initial traction"},
    {"name": "early_momentum","subs": 100,   "label": "100 subs — proving the concept"},
    {"name": "early_mid",     "subs": 500,   "label": "500 subs — gaining momentum"},
    {"name": "growth_stage",  "subs": 1000,  "label": "1,000 subs — growth stage unlocked"},
    {"name": "growth_mid",    "subs": 5000,  "label": "5,000 subs — solid audience"},
    {"name": "established",   "subs": 10000, "label": "10,000 subs — established channel"},
    {"name": "scaling",       "subs": 50000, "label": "50,000 subs — scaling up"},
]


def get_current_goal(report: dict) -> dict | None:
    """Return the next unachieved goal milestone."""
    subs = report.get("kpis", {}).get("subscribers", 0)
    for g in GOALS:
        if subs < g["subs"]:
            return g
    return None


def goals_met(report: dict) -> bool:
    """True if all defined goals have been reached."""
    return get_current_goal(report) is None


def run_gemini_manager(print_report: bool = True) -> dict:
    print("[Manager] Starting channel analysis...")
    report = build_channel_report()

    if report.get("status") == "no_videos":
        print("[Manager] No videos yet - applying starter directives.")
        starter = {
            "video_length_min": 8, "video_length_max": 12,
            "short_length_sec": 45,
            "long_videos_per_week": 2,
            "shorts_per_week": 3,
            "auto_clip_shorts_from_long": True,
            "publish_days": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
            "publish_hour": 14,
            "channel_style": "friendly, energetic, short and punchy",
            "hook_style": "Open with a surprising stat or contrarian claim in first 5 seconds",
            "title_rules": "Lead with a number or 'How to'. Under 60 chars. Include main keyword.",
            "cta_instruction": "At 70% through: ask viewers to subscribe and comment their #1 question",
            "thumbnail_style": "use colorful, eye-catching, high-contrast graphics with text overlays",
        }
        apply_directives_to_pipeline(starter)
        save_directives(starter, "Starter directives - no performance data yet.")
        return {"report": report, "analysis": {}, "directives": starter}

    analysis = run_manager_analysis(report)
    if not analysis:
        return {"report": report, "analysis": {}, "directives": {}}

    directives = analysis.get("directives", {})
    a = analysis.get("analysis", {})

    save_directives(directives, json.dumps(a, indent=2))
    apply_directives_to_pipeline(directives)
    log_manager_action(
        "full_analysis",
        a.get("biggest_problem", "Routine analysis"),
        json.dumps(directives),
        a.get("immediate_fix", "")
    )

    if print_report:
        print(format_manager_report(report, analysis))

    return {"report": report, "analysis": analysis, "directives": directives}


if __name__ == "__main__":
    run_gemini_manager()
