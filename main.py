"""
main.py — YouTube Autopilot Orchestrator (with Gemini Manager)

Jobs:
  - Daily idea top-up       (idea_engine)
  - 3x/week production      (content_gen -> video_producer -> upload_agent)
  - Bi-daily manager check  (gemini_manager - analyses KPIs, rewrites directives)
  - Weekly deep review      (review_agent)

Usage:
  python main.py                       # Scheduler (runs on publish days)
  python main.py --now                 # One full production cycle immediately
  python main.py --loop                # Keep producing until all goals are met
  python main.py --loop --interval=2   # Same, but wait 2h between cycles
  python main.py --manager             # Run Gemini Manager check immediately
  python main.py --review              # Run review agent immediately
  python main.py --ideas               # Top up idea queue immediately
  python main.py --setup               # First-time setup
  python main.py --status              # Print current manager directives and channel status
"""

import sys, time
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from config import PUBLISH_DAYS, PUBLISH_HOUR, VIDEOS_PER_WEEK, CHANNEL_NAME
from utils.db import init_db, get_next_idea, update_idea_status, pending_idea_count
from utils.overrides import get_overrides, override
from agents.idea_engine import run_idea_engine
from agents.content_generator import run_content_generator
from agents.video_producer import run_video_producer, clip_short_from_long
from agents.upload_agent import run_upload_agent
from agents.review_agent import run_review_agent
from agents.gemini_manager import run_gemini_manager, get_directives, format_manager_report, build_channel_report, goals_met, get_current_goal


def run_production_cycle():
    """
    Full pipeline - respects live manager directives at every step.
    Produces 1 long video, then auto-clips a Short from its hook section.
    """
    OV = get_overrides()
    publish_days = override(OV, "publish_days", PUBLISH_DAYS)
    channel_name = CHANNEL_NAME
    auto_clip = override(OV, "auto_clip_shorts_from_long", False)
    short_max_sec = override(OV, "short_length_sec", 60)

    print("\n" + "="*60)
    print("[Autopilot] Starting production cycle...")
    if OV:
        print(f"[Autopilot] Manager directives active: {list(OV.keys())}")
    print("="*60)

    run_idea_engine(target_pending=15)

    idea = get_next_idea()
    if not idea:
        print("[Autopilot] No pending ideas. Skipping cycle.")
        return

    print(f"\n[Autopilot] Processing: '{idea['title']}'")
    update_idea_status(idea["id"], "scripted")

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

    update_idea_status(idea["id"], "produced")
    try:
        video_path = run_video_producer(
            script_path=content["script_path"],
            idea_id=idea["id"],
            channel_name=channel_name,
        )
        if not video_path:
            print("[Autopilot] Video production failed.")
            update_idea_status(idea["id"], "skipped")
            return
    except Exception as e:
        print(f"[Autopilot] Video prod error: {e}")
        update_idea_status(idea["id"], "skipped")
        return

    # Upload long video
    try:
        yt_id = run_upload_agent(
            idea=idea,
            content=content,
            video_path=video_path,
            publish_days=publish_days,
            schedule=True,
            is_short=False
        )
        if yt_id:
            print(f"\n[Autopilot] Published long video: https://youtu.be/{yt_id}")
    except Exception as e:
        print(f"[Autopilot] Upload error: {e}")

    # Auto-clip Short from hook section if enabled
    short_path = None
    if auto_clip:
        print(f"\n[Autopilot] Clipping Short from hook section...")
        short_path = clip_short_from_long(
            video_path=video_path,
            script_path=content["script_path"],
            idea_id=idea["id"],
            max_sec=short_max_sec,
        )
        if short_path:
            print(f"[Autopilot] Short clipped: {short_path}")

    # Upload Short
    if short_path and auto_clip:
        try:
            short_yt_id = run_upload_agent(
                idea=idea,
                content=content,
                video_path=short_path,
                publish_days=publish_days,
                schedule=True,
                is_short=True
            )
            if short_yt_id:
                print(f"[Autopilot] Published Short: https://youtu.be/{short_yt_id}")
        except Exception as e:
            print(f"[Autopilot] Short upload error: {e}")

    print("[Autopilot] Cycle complete.\n")


def start_scheduler():
    OV = get_overrides()
    publish_days = override(OV, "publish_days", PUBLISH_DAYS)
    publish_hour = override(OV, "publish_hour", PUBLISH_HOUR)
    long_per_week = override(OV, "long_videos_per_week", override(OV, "videos_per_week", VIDEOS_PER_WEEK))
    shorts_per_week = override(OV, "shorts_per_week", 0)

    scheduler = BlockingScheduler(timezone="UTC")

    scheduler.add_job(run_idea_engine, CronTrigger(hour=6, minute=0),
                      id="idea_engine", kwargs={"target_pending": 20},
                      name="Idea Engine", misfire_grace_time=3600)

    scheduler.add_job(run_gemini_manager, CronTrigger(hour="6,18", minute=30),
                      id="gemini_manager", name="Gemini Manager",
                      misfire_grace_time=3600)

    for day in publish_days:
        scheduler.add_job(
            run_production_cycle,
            CronTrigger(day_of_week=day[:3].lower(), hour=max(0, publish_hour - 4), minute=0),
            id=f"produce_{day}", name=f"Production: {day}", misfire_grace_time=3600
        )

    scheduler.add_job(run_review_agent, CronTrigger(day_of_week="sun", hour=8, minute=0),
                      id="weekly_review", name="Weekly Review", misfire_grace_time=7200)

    print(f"\n[Autopilot] Scheduler running.")
    print(f"  - Long videos/week: {long_per_week}")
    print(f"  - Shorts/week: {shorts_per_week}")
    print(f"  - Publish days: {publish_days} at {publish_hour}:00 UTC")
    print(f"  - Gemini Manager: every 12h")
    print(f"  - Weekly review: Sunday 08:00 UTC")
    print(f"  - Press Ctrl+C to stop.\n")

    try:
        scheduler.start()
    except KeyboardInterrupt:
        print("\n[Autopilot] Stopped.")


def run_loop(interval_hours: float = 4):
    """
    Continuous loop: produce videos until all goals are met.
    Runs Manager before each cycle, waits `interval_hours` between cycles.
    """
    print("\n" + "="*60)
    print("[Autopilot] GOAL LOOP MODE — will keep producing until milestones are hit")
    print("="*60)

    while True:
        report = build_channel_report()
        kpis = report.get("kpis", {})

        if goals_met(report):
            print("\n[Autopilot] All goals achieved!")
            print(f"  Subs: {kpis.get('subscribers',0):,}")
            print(f"  Stage: {kpis.get('channel_stage','?')}")
            break

        goal = get_current_goal(report)
        print(f"\n[Autopilot] Current goal: {goal['label']} ({kpis.get('subscribers',0)}/{goal['subs']} subs)")

        run_gemini_manager(print_report=False)
        run_production_cycle()

        print(f"\n[Autopilot] Waiting {interval_hours}h before next cycle...")
        print(f"  Press Ctrl+C to stop.\n")
        try:
            time.sleep(interval_hours * 3600)
        except KeyboardInterrupt:
            print("\n[Autopilot] Loop stopped.")
            break


def print_status():
    OV = get_overrides()
    report = build_channel_report()
    kpis = report.get("kpis", {})

    print("\n-- Channel Status -------------------------------------")
    print(f"  Subscribers:      {kpis.get('subscribers', '?')}")
    print(f"  Stage:            {kpis.get('channel_stage', '?')}")
    print(f"  Next goal:        {kpis.get('next_goal', '?')}")
    print(f"  Videos published: {kpis.get('total_videos_published', 0)}")
    print(f"  Total views:      {kpis.get('total_views', 0):,}")
    print(f"  Growth trend:     {kpis.get('growth_trend', 'no data')}")
    print(f"  Pending ideas:    {kpis.get('pending_ideas_in_queue', 0)}")

    print("\n-- Active Manager Directives -------------------------")
    if OV:
        for k, v in OV.items():
            print(f"  {k}: {v}")
    else:
        print("  No directives set - using config.py defaults.")
    print()


def setup():
    print("[Setup] Initialising database...")
    init_db()
    print("[Setup] Authenticating with YouTube (browser will open)...")
    from utils.youtube_api import get_youtube_service
    get_youtube_service()
    print("[Setup] Running initial Gemini Manager analysis...")
    run_gemini_manager()
    print("[Setup] Complete. Run `python main.py` to start.")


if __name__ == "__main__":
    init_db()
    args = sys.argv[1:]

    if "--setup"   in args: setup()
    elif "--now"   in args:
        run_gemini_manager(print_report=True)
        run_production_cycle()
    elif "--loop"  in args:
        interval = 4
        for a in args:
            if a.startswith("--interval="):
                interval = float(a.split("=")[1])
        run_loop(interval_hours=interval)
    elif "--manager" in args: run_gemini_manager()
    elif "--review" in args: run_review_agent()
    elif "--ideas" in args: run_idea_engine(target_pending=20)
    elif "--status" in args: print_status()
    else: start_scheduler()
