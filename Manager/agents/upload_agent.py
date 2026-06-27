"""
agents/upload_agent.py — uploads the produced video to YouTube and records it in the DB.
"""

import json
from datetime import datetime, timezone
from config import PUBLISH_HOUR
from utils.db import save_video, mark_published, update_idea_status
from utils.youtube_api import upload_video


def get_next_publish_time(publish_days: list[str]) -> str:
    """Returns ISO 8601 UTC string for the next target publish day at PUBLISH_HOUR."""
    from datetime import timedelta
    day_map = {"Monday":0,"Tuesday":1,"Wednesday":2,"Thursday":3,
               "Friday":4,"Saturday":5,"Sunday":6}
    now = datetime.now(timezone.utc)
    targets = sorted([day_map[d] for d in publish_days])

    for days_ahead in range(1, 8):
        candidate = now + timedelta(days=days_ahead)
        if candidate.weekday() in targets:
            publish_dt = candidate.replace(hour=PUBLISH_HOUR, minute=0, second=0, microsecond=0)
            return publish_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    # Fallback: 24h from now
    return (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def run_upload_agent(idea: dict, content: dict, video_path: str,
                     publish_days: list[str], schedule: bool = True) -> str | None:
    """
    Upload video to YouTube.
    Returns YouTube video ID on success, None on failure.
    """
    package = content["package"]
    thumbnail_path = content.get("thumbnail_path")
    script_path = content.get("script_path")

    tags = package.get("tags", [])
    if isinstance(tags, list):
        tags_str = json.dumps(tags)
    else:
        tags_str = str(tags)

    # Schedule or publish immediately
    publish_at = get_next_publish_time(publish_days) if schedule else None

    try:
        yt_id = upload_video(
            video_path=video_path,
            title=package["title"],
            description=package["description"],
            tags=package.get("tags", []),
            thumbnail_path=thumbnail_path,
            publish_at=publish_at,
        )
    except Exception as e:
        print(f"[UploadAgent] Upload failed: {e}")
        return None

    # Record in DB
    video_db_id = save_video({
        "idea_id": idea["id"],
        "title": package["title"],
        "description": package["description"],
        "tags": tags_str,
        "script_path": script_path,
        "video_path": video_path,
        "thumbnail_path": thumbnail_path,
    })
    mark_published(video_db_id, yt_id)
    update_idea_status(idea["id"], "published")

    action = f"scheduled for {publish_at}" if publish_at else "published immediately"
    print(f"[UploadAgent] Video {yt_id} {action}.")
    return yt_id
