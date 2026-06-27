import json, os, re
from datetime import datetime, timezone

from config import CHANNEL_NICHE, CHANNEL_NAME, TARGET_AUDIENCE, CHANNEL_STYLE
from utils.db import get_published_videos, get_strategy, save_strategy, get_conn, pending_idea_count
from utils.llm import llm_complete
from utils.youtube_api import get_channel_stats


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

    video_data = []
    for v in videos_sorted[:20]:
        views = v.get("views", 0)
        likes = v.get("likes", 0)
        video_data.append({
            "title":         v.get("title", "Unknown"),
            "youtube_id":    v.get("youtube_id", ""),
            "published":     (v.get("published_at") or "")[:10],
            "views":         views,
            "likes":         likes,
            "comments":      v.get("comments", 0),
            "like_rate_pct": round(likes / views * 100, 2) if views > 0 else 0,
            "avg_watch_pct": v.get("avg_watch_pct", 0),
        })

    strategy = get_strategy()
    strategy_text = strategy if isinstance(strategy, str) else json.dumps(strategy)

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

Be SPECIFIC. Base every directive on the data. Return ONLY valid JSON."""


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
