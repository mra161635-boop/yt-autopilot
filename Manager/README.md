# YouTube Autopilot

A fully automated YouTube channel system. Generates ideas, writes scripts,
produces videos, uploads them, and learns from audience data — all for free.

---

## Architecture

```
Idea Engine ──► Content Generator ──► Video Producer ──► Upload Agent
     ▲                                                         │
     └──────────── Review Agent (weekly) ◄────────────────────┘
```

Every component uses Claude AI. The Review Agent feeds audience insights back
into the Idea Engine so the system gets smarter over time.

---

## Setup (15 minutes)

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Get your API keys (all free)

| Service | Where to get it | Cost |
|---|---|---|
| **Claude API** | console.anthropic.com | Pay-per-use (~$0.01-0.05/video) |
| **YouTube Data API** | console.cloud.google.com | Free (10,000 units/day) |
| **Pexels API** | pexels.com/api | Free (200 req/hr) |

### 3. YouTube OAuth setup

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project → Enable **YouTube Data API v3**
3. Create OAuth 2.0 credentials (Desktop app type)
4. Download `client_secret.json` and put it in this folder
5. Also enable **YouTube Analytics API** (for the review agent)

### 4. Configure your channel

Edit `config.py`:

```python
CHANNEL_NICHE    = "your niche here"         # e.g. "vegan cooking for beginners"
CHANNEL_STYLE    = "friendly and informative" 
TARGET_AUDIENCE  = "describe your audience"
CHANNEL_NAME     = "YourChannelName"
VIDEOS_PER_WEEK  = 3
PUBLISH_DAYS     = ["Monday", "Wednesday", "Friday"]
```

### 5. Set environment variables

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export PEXELS_API_KEY="your-pexels-key"
# YT auth is handled via OAuth (see step 3)
```

### 6. First-time setup

```bash
python main.py --setup
```

This initialises the database and opens a browser for YouTube OAuth.

---

## Running the Bot

```bash
# Start the autopilot (runs forever, scheduled)
python main.py

# Run one production cycle right now (for testing)
python main.py --now

# Just generate new ideas
python main.py --ideas

# Run the weekly review immediately
python main.py --review
```

---

## How It Learns

Every Sunday, the **Review Agent**:
1. Fetches fresh YouTube analytics for all published videos
2. Reads recent comments using sentiment analysis
3. Identifies what topics/formats performed best
4. Updates a "Strategy Memo" in the database

The **Idea Engine** reads this memo before generating new ideas, so it
automatically shifts toward topics your audience responds to.

---

## File Structure

```
yt_autopilot/
├── main.py                    # Orchestrator + scheduler
├── config.py                  # Your settings
├── requirements.txt
├── client_secret.json         # YouTube OAuth (you add this)
├── agents/
│   ├── idea_engine.py         # Generates ranked video ideas
│   ├── content_generator.py   # Script + thumbnail
│   ├── video_producer.py      # TTS + stock video + MoviePy
│   ├── upload_agent.py        # YouTube upload + scheduling
│   └── review_agent.py        # Weekly analytics + strategy update
├── utils/
│   ├── db.py                  # SQLite persistence
│   └── youtube_api.py         # YouTube API wrapper
├── data/
│   ├── autopilot.db           # SQLite database (auto-created)
│   └── scripts/               # Generated scripts (JSON)
└── output/
    ├── videos/                # Produced .mp4 files
    └── thumbnails/            # Generated thumbnails
```

---

## Tips

- **Voice quality**: edge-tts is free but robotic. For better quality,
  add an ElevenLabs API key (`ELEVENLABS_API_KEY`) — they have a free tier
  (10,000 chars/month).

- **Video quality**: Without a Pexels key, videos use colored title cards.
  Get a free Pexels key for real stock footage.

- **Niche matters**: The more specific your `CHANNEL_NICHE`, the better
  Claude's ideas will be. "Finance" → bad. "Tax tips for freelancers" → great.

- **Costs**: Running 3 videos/week costs roughly $0.10-0.50/week in Claude API
  usage. Everything else is free.

- **Run on a server**: For 24/7 operation, deploy on a free Oracle Cloud
  instance or a $5/month VPS. Use `nohup python main.py &` or set up systemd.

---

## Gemini Manager (new)

The Gemini Manager runs every 12 hours and has full authority over the pipeline.

### What it does
- Reads all channel performance data (views, likes, comments, watch time)
- Diagnoses what's hurting growth with specific reasoning
- Writes "directives" — live config overrides every agent respects
- Logs every decision so you can audit it

### Setup
```bash
export GEMINI_API_KEY="your-gemini-api-key"
```

Get a free Gemini API key at: https://aistudio.google.com/app/apikey

### Running
```bash
python main.py --manager    # Run immediately
python main.py --status     # See current directives
python main.py              # Scheduler (runs automatically every 12h)
```

### What the manager can change
The manager writes overrides to `data/manager_overrides.json`. Every agent
reads this file before running. Directives include:

- **Content**: hook style, CTA format, script instructions, thumbnail style
- **SEO**: title rules, required keywords, banned topics  
- **Schedule**: publish days, publish hour, videos per week
- **Format**: video length min/max

The manager never breaks the pipeline — directives are soft overrides.
If Gemini API is down, agents fall back to config.py defaults.
