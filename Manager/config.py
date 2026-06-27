"""
YouTube Autopilot - Configuration
Set your API keys and channel preferences here.
"""

import os

# ── API Keys ──────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY   = os.getenv("ANTHROPIC_API_KEY", "YOUR_KEY_HERE")
YOUTUBE_CLIENT_SECRET_FILE = os.getenv("YT_CLIENT_SECRET", "client_secret.json")
PEXELS_API_KEY      = os.getenv("PEXELS_API_KEY", "")      # free at pexels.com/api
ELEVENLABS_API_KEY  = os.getenv("ELEVENLABS_API_KEY", "")  # optional; falls back to edge-tts

# ── Channel Identity ──────────────────────────────────────────────────────────
CHANNEL_NICHE       = "personal finance tips for beginners"   # <-- change this
CHANNEL_STYLE       = "friendly, energetic, short and punchy" # tone of voice
TARGET_AUDIENCE     = "18-35 year olds interested in saving and investing"
CHANNEL_NAME        = "MoneyMoves"  # used in scripts / branding

# ── Content Settings ─────────────────────────────────────────────────────────
VIDEOS_PER_WEEK     = 3             # how many videos to publish per week
VIDEO_LENGTH_MIN    = 5             # target video length in minutes
VIDEO_LENGTH_MAX    = 10
PUBLISH_DAYS        = ["Monday", "Wednesday", "Friday"]  # days to publish
PUBLISH_HOUR        = 14            # 2 PM (UTC) — adjust for your audience timezone

# ── Paths ─────────────────────────────────────────────────────────────────────
DB_PATH             = "data/autopilot.db"
OUTPUT_VIDEO_DIR    = "output/videos"
OUTPUT_THUMB_DIR    = "output/thumbnails"

# ── Claude Model ─────────────────────────────────────────────────────────────
CLAUDE_MODEL        = "claude-sonnet-4-6"
