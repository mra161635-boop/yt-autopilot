"""
utils/youtube_api.py — thin wrapper around YouTube Data API v3.

Authentication: OAuth 2.0 (run once to get token, then reuses refresh token).
Scopes needed:
  - https://www.googleapis.com/auth/youtube.upload
  - https://www.googleapis.com/auth/youtube.readonly
  - https://www.googleapis.com/auth/yt-analytics.readonly
"""

import os, json, pickle
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


def get_youtube_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(YOUTUBE_CLIENT_SECRET_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "wb") as f:
            pickle.dump(creds, f)

    return build("youtube", "v3", credentials=creds)


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
