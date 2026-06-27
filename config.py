"""
YouTube Autopilot - Configuration
Set your API keys and channel preferences here.
"""

import os

# ── API Keys ──────────────────────────────────────────────────────────────────
YOUTUBE_CLIENT_SECRET_FILE = os.getenv("YT_CLIENT_SECRET", "YT.json")
PEXELS_API_KEY      = os.getenv("PEXELS_API_KEY", "")
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

# ── Open-Source LLM ──────────────────────────────────────────────────────────
# Provider: "ollama" (default, fully free, local) or "openai_compat" (OpenRouter, Groq, etc.)
LLM_PROVIDER  = os.getenv("LLM_PROVIDER", "openai_compat")
LLM_MODEL     = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
LLM_API_KEY   = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL  = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai")
# For OpenRouter: LLM_BASE_URL=https://openrouter.ai/api, LLM_API_KEY=your_key, LLM_MODEL=meta-llama/llama-3.1-8b-instruct
# For Groq:        LLM_BASE_URL=https://api.groq.com/openai,   LLM_API_KEY=your_key, LLM_MODEL=llama-3.1-8b-instant
