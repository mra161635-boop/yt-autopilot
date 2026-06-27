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

Every component uses an open-source LLM (Ollama by default, with Llama 3.1).
The Review Agent feeds audience insights back into the Idea Engine so the
system gets smarter over time.

---

## Setup (15 minutes)

### 1. Install & start Ollama (the free open-source LLM)

```bash
# Download from https://ollama.com, then:
ollama pull llama3.1
ollama serve
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Get your API keys (all free)

| Service | Where to get it | Cost |
|---|---|---|
| **LLM (Ollama)** | ollama.com (run `ollama pull llama3.1`) | 100% free, local |
| **YouTube Data API** | console.cloud.google.com | Free (10,000 units/day) |
| **Pexels API** | pexels.com/api | Free (200 req/hr) |

### 4. YouTube OAuth setup

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a project → Enable **YouTube Data API v3**
3. Create OAuth 2.0 credentials (Desktop app type)
4. Download `client_secret.json` and put it in this folder
5. Also enable **YouTube Analytics API** (for the review agent)

### 5. Configure your channel

Edit `config.py`:

```python
CHANNEL_NICHE    = "your niche here"         # e.g. "vegan cooking for beginners"
CHANNEL_STYLE    = "friendly and informative" 
TARGET_AUDIENCE  = "describe your audience"
CHANNEL_NAME     = "YourChannelName"
VIDEOS_PER_WEEK  = 3
PUBLISH_DAYS     = ["Monday", "Wednesday", "Friday"]
```

### 5. Set up the LLM

**Option A — Ollama (recommended, fully free):**

```bash
# Install Ollama from https://ollama.com
ollama pull llama3.1
# Optional: configure via environment variables (these are the defaults)
export LLM_PROVIDER="ollama"
export LLM_MODEL="llama3.1"
export LLM_BASE_URL="http://localhost:11434"
```

**Option B — OpenRouter (cloud, many free models):**

```bash
export LLM_PROVIDER="openai_compat"
export LLM_MODEL="meta-llama/llama-3.1-8b-instruct"
export LLM_API_KEY="sk-or-..."
export LLM_BASE_URL="https://openrouter.ai/api"
```

**Option C — Groq (cloud, free tier):**

```bash
export LLM_PROVIDER="openai_compat"
export LLM_MODEL="llama-3.1-8b-instant"
export LLM_API_KEY="gsk_..."
export LLM_BASE_URL="https://api.groq.com/openai"
```

Then set your media API keys:

```bash
export PEXELS_API_KEY="your-pexels-key"
# YT auth is handled via OAuth (see step 4)
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
│   ├── llm.py                 # Open-source LLM interface (Ollama / OpenAI-compat)
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

- **Niche matters**: The more specific your `CHANNEL_NICHE`, the better the
  LLM's ideas will be. "Finance" → bad. "Tax tips for freelancers" → great.

- **Costs**: With Ollama everything is 100% free. With cloud providers like
  OpenRouter/Groq, their free tiers cover thousands of requests.

- **Run on a server**: For 24/7 operation, deploy on a free Oracle Cloud
  instance or a $5/month VPS. Use `nohup python main.py &` or set up systemd.
