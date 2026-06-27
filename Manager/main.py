"""
main.py — YouTube Autopilot Orchestrator (with Gemini Manager)

Jobs:
  • Daily idea top-up       (idea_engine)
  • 3x/week production      (content_gen → video_producer → upload_agent)
  • Bi-daily manager check  (gemini_manager — analyses KPIs, rewrites directives)
  • Weekly deep review      (review_agent)

Usage:
  python main.py              # Run continuously
  python main.py --now        # One full production cycle immediately
  python main.py --manager    # Run Gemini Manager check immediately
  python main.py --review     # Run review agent immediately
  python main.py --ideas      # Top up idea queue immediately
  python main.py --setup      # First-time setup
  python main.py --status     # Print current manager directives and channel status
"""

import sys
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

import config
from utils.db import init_db, get_next_idea, update_idea_status
from utils.overrides import get_overrides, override
from agents.idea_engine import run_idea_engine
from agents.content_generator import run_content_generator
from agents.video_producer import run_video_producer
from agents.upload_agent import run_upload_agent
from agents.review_agent import run_review_agent
from agents.gemini_manager import run_gemini_manager, get_directives, format_manager_report, build_channel_report


# ── Core Production Pipeline ──────────────────────────────────────────────────

def run_production_cycle():
    """
    Full pipeline — respects live manager directives at every step.
    """
    # Load live manager overrides
    OV = get_overrides()

    publish_days = override(OV, "publish_days", config.PUBLISH_DAYS)
    channel_name = config.CHANNEL_NAME

    print("\n" + "="*60)
    print("[Autopilot] Starting production cycle...")
    if OV:
        print(f"[Autopilot] Manager directives active: {list(OV.keys())}")
    print("="*60)

    # 1. Top up idea queue
    run_idea_engine(target_pending=15)

    # 2. Pick next idea
    idea = get_next_idea()
    if not idea:
        print("[Autopilot] No pending ideas. Skipping cycle.")
        return

    print(f"\n[Autopilot] Processing: '{idea['title']}'")
    update_idea_status(idea["id"], "scripted")

    # 3. Generate script + thumbnail (passes overrides in)
    try:
        content = run_content_generator(idea, overrides=OV)
        if not content or not content.get("script_path"):
            print("[Autopilot] Content generation failed.")
            update_idea_status(idea["id"], "skipped")
            return
    except Exception as e:
        print(f"[Autopilot] Content gen error: {e}")
        update_idea_status(idea["id"], "skipped")
        return

    # 4. Produce video
    update_idea_status(idea["id"], "produced")
    try:
        video_path = run_video_producer(
            script_path=content["script_path"],
            idea_id=idea["id"],
            channel_name=channel_name,
            overrides=OV
        )
        if not video_path:
            print("[Autopilot] Video production failed.")
            update_idea_status(idea["id"], "skipped")
            return
    except Exception as e:
        print(f"[Autopilot] Video prod error: {e}")
        update_idea_status(idea["id"], "skipped")
        return

    # 5. Upload
    try:
        yt_id = run_upload_agent(
            idea=idea,
            content=content,
            video_path=video_path,
            publish_days=publish_days,
            schedule=True
        )
        if yt_id:
            print(f"\n[Autopilot] ✅ Published: https://youtu.be/{yt_id}")
    except Exception as e:
        print(f"[Autopilot] Upload error: {e}")

    print("[Autopilot] Cycle complete.\n")


# ── Scheduler ─────────────────────────────────────────────────────────────────

def start_scheduler():
    OV = get_overrides()
    publish_days = override(OV, "publish_days", config.PUBLISH_DAYS)
    publish_hour = override(OV, "publish_hour", config.PUBLISH_HOUR)

    scheduler = BlockingScheduler(timezone="UTC")

    # Daily idea top-up at 6am
    scheduler.add_job(run_idea_engine, CronTrigger(hour=6, minute=0),
                      id="idea_engine", kwargs={"target_pending": 20},
                      name="Idea Engine", misfire_grace_time=3600)

    # Gemini Manager check: every 12 hours
    scheduler.add_job(run_gemini_manager, CronTrigger(hour="6,18", minute=30),
                      id="gemini_manager", name="Gemini Manager",
                      misfire_grace_time=3600)

    # Production on publish days
    for day in publish_days:
        scheduler.add_job(
            run_production_cycle,
            CronTrigger(day_of_week=day[:3].lower(), hour=max(0, publish_hour - 4), minute=0),
            id=f"produce_{day}", name=f"Production: {day}", misfire_grace_time=3600
        )

    # Weekly deep review: Sunday 8am
    scheduler.add_job(run_review_agent, CronTrigger(day_of_week="sun", hour=8, minute=0),
                      id="weekly_review", name="Weekly Review", misfire_grace_time=7200)

    print(f"\n[Autopilot] Scheduler running.")
    print(f"  • Publish days: {publish_days} at {publish_hour}:00 UTC")
    print(f"  • Gemini Manager: every 12h")
    print(f"  • Weekly review: Sunday 08:00 UTC")
    print(f"  • Press Ctrl+C to stop.\n")

    try:
        scheduler.start()
    except KeyboardInterrupt:
        print("\n[Autopilot] Stopped.")


# ── Status Report ─────────────────────────────────────────────────────────────

def print_status():
    OV = get_overrides()
    report = build_channel_report()
    kpis = report.get("kpis", {})

    print("\n── Channel Status ────────────────────────────────────")
    print(f"  Videos published: {kpis.get('total_videos_published', 0)}")
    print(f"  Total views:      {kpis.get('total_views', 0):,}")
    print(f"  Growth trend:     {kpis.get('growth_trend', 'no data')}")
    print(f"  Pending ideas:    {kpis.get('pending_ideas_in_queue', 0)}")

    print("\n── Active Manager Directives ─────────────────────────")
    if OV:
        for k, v in OV.items():
            print(f"  {k}: {v}")
    else:
        print("  No directives set — using config.py defaults.")
    print()


# ── Setup ─────────────────────────────────────────────────────────────────────

def setup():
    print("[Setup] Initialising database...")
    init_db()
    print("[Setup] Authenticating with YouTube (browser will open)...")
    from utils.youtube_api import get_youtube_service
    get_youtube_service()
    print("[Setup] Running initial Gemini Manager analysis...")
    run_gemini_manager()
    print("[Setup] ✅ Complete. Run `python main.py` to start.")


# ── Entry ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    args = sys.argv[1:]

    if "--setup"   in args: setup()
    elif "--now"   in args: run_production_cycle()
    elif "--manager" in args: run_gemini_manager()
    elif "--review" in args: run_review_agent()
    elif "--ideas" in args: run_idea_engine(target_pending=20)
    elif "--status" in args: print_status()
    else: start_scheduler()
