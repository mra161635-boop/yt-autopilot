"""
utils/youtube_api.py — wraps YouTube Data API v3 and YouTube Analytics API v2.

Authentication: OAuth 2.0 (run once to get token, then reuses refresh token).
Scopes needed:
  - https://www.googleapis.com/auth/youtube.upload
  - https://www.googleapis.com/auth/youtube.force-ssl
  - https://www.googleapis.com/auth/yt-analytics.readonly
"""

import os, json, pickle
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from config import YOUTUBE_CLIENT_SECRET_FILE

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
TOKEN_FILE = "data/yt_token.pickle"


def _load_credentials():
    """Load or refresh OAuth credentials. Returns google.oauth2.credentials.Credentials."""
    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(YOUTUBE_CLIENT_SECRET_FILE, SCOPES)
            creds = flow.run_local_server(port=8080, open_browser=True)
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)

    return creds


def get_youtube_service():
    return build("youtube", "v3", credentials=_load_credentials())


def get_analytics_service():
    return build("youtubeAnalytics", "v2", credentials=_load_credentials())


def upload_video(video_path: str, title: str, description: str, tags: list[str],
                 thumbnail_path: str = None, publish_at: str = None) -> str:
    """Upload a video. Returns YouTube video ID."""
    yt = get_youtube_service()

    status = "private" if publish_at else "public"
    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags[:500],
            "categoryId": "22",  # People & Blogs — change if needed
        },
        "status": {
            "privacyStatus": status,
            "selfDeclaredMadeForKids": False,
        }
    }
    if publish_at:
        body["status"]["publishAt"] = publish_at  # ISO 8601 UTC

    request = yt.videos().insert(
        part="snippet,status",
        body=body,
        media_body=MediaFileUpload(video_path, chunksize=-1, resumable=True)
    )

    response = None
    while response is None:
        status_obj, response = request.next_chunk()
        if status_obj:
            print(f"  Upload progress: {int(status_obj.progress() * 100)}%")

    video_id = response["id"]
    print(f"[YT] Uploaded: https://youtu.be/{video_id}")

    if thumbnail_path and os.path.exists(thumbnail_path):
        yt.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(thumbnail_path)).execute()
        print("[YT] Thumbnail set.")

    return video_id


def get_video_stats(video_ids: list[str]) -> list[dict]:
    """Fetch views, likes, comment count for a list of video IDs."""
    yt = get_youtube_service()
    resp = yt.videos().list(
        part="statistics",
        id=",".join(video_ids)
    ).execute()

    stats = []
    for item in resp.get("items", []):
        s = item["statistics"]
        stats.append({
            "youtube_id": item["id"],
            "views":      int(s.get("viewCount", 0)),
            "likes":      int(s.get("likeCount", 0)),
            "comments":   int(s.get("commentCount", 0)),
        })
    return stats


def get_channel_stats() -> dict:
    """Fetch subscriber count and total views for the authenticated channel."""
    yt = get_youtube_service()
    resp = yt.channels().list(part="statistics", mine=True).execute()
    item = resp.get("items", [{}])[0]
    s = item.get("statistics", {})
    return {
        "subscribers": int(s.get("subscriberCount", 0)),
        "total_views": int(s.get("viewCount", 0)),
        "total_videos": int(s.get("videoCount", 0)),
    }


# ── YouTube Analytics API v2 ────────────────────────────────────────────────────


def _get_channel_id() -> str | None:
    try:
        yt = get_youtube_service()
        resp = yt.channels().list(part="id", mine=True).execute()
        return resp["items"][0]["id"] if resp.get("items") else None
    except Exception:
        return None


def _query_analytics(metrics: list[str], dimensions: list[str] = None,
                     filters: str = None, days: int = 28) -> dict:
    analytics = get_analytics_service()
    channel_id = _get_channel_id()
    if not channel_id:
        return {}
    end_date = datetime.utcnow().strftime("%Y-%m-%d")
    start_date = (datetime.utcnow() - timedelta(days=days)).strftime("%Y-%m-%d")
    params = {
        "ids": f"channel=={channel_id}",
        "startDate": start_date,
        "endDate": end_date,
        "metrics": ",".join(metrics),
    }
    if dimensions:
        params["dimensions"] = ",".join(dimensions)
    if filters:
        params["filters"] = filters
    try:
        return analytics.reports().query(**params).execute()
    except Exception as e:
        print(f"[YT Analytics] Query failed ({metrics[0]}): {e}")
        return {}


def _parse_analytics_rows(response: dict) -> list[dict]:
    headers = [h["name"] for h in response.get("columnHeaders", [])]
    return [dict(zip(headers, row)) for row in response.get("rows", [])]


def get_channel_overview(days: int = 28) -> dict:
    """Channel-level KPIs: views, watch time, subscriber net, likes, comments.
    Note: shares + impressions require a dimension, fetched separately."""
    resp = _query_analytics(
        metrics=["views", "estimatedMinutesWatched", "averageViewDuration",
                 "subscribersGained", "subscribersLost", "likes", "comments"],
        days=days
    )
    rows = _parse_analytics_rows(resp)
    result = rows[0] if rows else {}
    # Fetch impression data separately (requires video dimension)
    imp = _query_analytics(
        metrics=["views", "videoThumbnailImpressions", "videoThumbnailImpressionsClickRate"],
        dimensions=["video"],
        days=days
    )
    imp_rows = _parse_analytics_rows(imp)
    if imp_rows:
        result["videoThumbnailImpressions"] = sum(int(r.get("videoThumbnailImpressions", 0)) for r in imp_rows)
        ctr_vals = [float(r.get("videoThumbnailImpressionsClickRate", 0)) for r in imp_rows if r.get("videoThumbnailImpressionsClickRate")]
        result["videoThumbnailImpressionsClickRate"] = (sum(ctr_vals) / len(ctr_vals)) if ctr_vals else 0
    return result


def get_traffic_sources(days: int = 28) -> list[dict]:
    """Where views come from: YT search, suggested, browse, Shorts feed, etc."""
    resp = _query_analytics(
        metrics=["views", "estimatedMinutesWatched"],
        dimensions=["insightTrafficSourceType"],
        days=days
    )
    return _parse_analytics_rows(resp)


def get_device_breakdown(days: int = 28) -> list[dict]:
    """Views by device type: mobile, desktop, tablet, tv."""
    resp = _query_analytics(
        metrics=["views", "estimatedMinutesWatched"],
        dimensions=["deviceType"],
        days=days
    )
    return _parse_analytics_rows(resp)


def get_content_type_performance(days: int = 28) -> dict:
    """Shorts vs long-form performance comparison."""
    resp = _query_analytics(
        metrics=["views", "estimatedMinutesWatched", "averageViewDuration"],
        dimensions=["creatorContentType"],
        days=days
    )
    result = {}
    for row in _parse_analytics_rows(resp):
        ctype = row.pop("creatorContentType", "unknown")
        result[ctype] = row
    return result


def get_video_analytics(video_id: str, days: int = 90) -> dict:
    """Per-video analytics: avg view duration, avg view %, thumbnail CTR."""
    resp = _query_analytics(
        metrics=["views", "averageViewDuration", "averageViewPercentage",
                 "likes", "comments",
                 "videoThumbnailImpressions", "videoThumbnailImpressionsClickRate"],
        filters=f"video=={video_id}",
        days=days
    )
    rows = _parse_analytics_rows(resp)
    result = rows[0] if rows else {}
    if result:
        result.pop("filters", None)
    return result


def get_recent_comments(video_id: str, max_results: int = 50) -> list[str]:
    """Return a list of top-level comment texts for a video."""
    yt = get_youtube_service()
    try:
        resp = yt.commentThreads().list(
            part="snippet",
            videoId=video_id,
            maxResults=max_results,
            order="relevance"
        ).execute()
        return [
            item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
            for item in resp.get("items", [])
        ]
    except Exception as e:
        print(f"[YT] Could not fetch comments for {video_id}: {e}")
        return []
