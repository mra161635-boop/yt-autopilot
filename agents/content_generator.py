"""
agents/content_generator.py — turns an idea into a full production package:
  - Full video script (with timestamps)
  - Optimised YouTube title, description, tags
  - Thumbnail concept + generated image (Pollinations AI — free, no API key)
"""

import json, re, os, requests
from PIL import Image, ImageDraw, ImageFont
from config import (CHANNEL_NICHE, CHANNEL_STYLE,
                    TARGET_AUDIENCE, CHANNEL_NAME, VIDEO_LENGTH_MIN,
                    VIDEO_LENGTH_MAX, OUTPUT_THUMB_DIR)
from utils.llm import llm_complete
from utils.overrides import get_overrides, override


# ── Script Generation ─────────────────────────────────────────────────────────

def generate_script(idea: dict, overrides: dict = None) -> dict:
    """Returns a dict with: script, title, description, tags, thumbnail_prompt."""
    OV = overrides or get_overrides()
    style            = override(OV, "channel_style", CHANNEL_STYLE)
    length_min       = override(OV, "video_length_min", VIDEO_LENGTH_MIN)
    length_max       = override(OV, "video_length_max", VIDEO_LENGTH_MAX)
    hook_style       = override(OV, "hook_style", "")
    cta_instruction  = override(OV, "cta_instruction", "")
    title_rules      = override(OV, "title_rules", "")
    thumb_style      = override(OV, "thumbnail_style", "")
    script_override  = override(OV, "script_instruction_override", "")

    hook_clause   = f"\nHOOK STYLE (manager directive): {hook_style}" if hook_style else ""
    cta_clause    = f"\nCTA INSTRUCTION (manager directive): {cta_instruction}" if cta_instruction else ""
    title_clause  = f"\nTITLE RULES (manager directive): {title_rules}" if title_rules else ""
    script_clause = f"\nSCRIPT RULE (manager directive): {script_override}" if script_override else ""
    thumb_clause  = f"\nTHUMBNAIL STYLE (manager directive): {thumb_style}" if thumb_style else ""

    prompt = f"""You are a YouTube scriptwriter for "{CHANNEL_NAME}", a channel about {CHANNEL_NICHE}.
Style: {style}
Audience: {TARGET_AUDIENCE}
Target length: {length_min}–{length_max} minutes
{hook_clause}{cta_clause}{title_clause}{script_clause}

IDEA:
Title: {idea['title']}
Hook concept: {idea.get('hook', '')}
Keywords: {json.dumps(idea.get('keywords', []))}

Write a complete, production-ready video package. Return ONLY valid JSON, no markdown:
{{
  "title": "Final YouTube title (≤70 chars, keyword-rich)",
  "description": "Full YouTube description (400-600 words). Include timestamps, CTA, relevant hashtags at end.",
  "tags": ["tag1","tag2","tag3",...],  // 10-15 tags
  "thumbnail_prompt": "Detailed text-to-image prompt for an eye-catching YouTube thumbnail. Describe style, colors, text overlay, facial expression if person shown.",
  "script": [
    {{
      "section": "Hook",
      "timestamp": "0:00",
      "voiceover": "Exact words the narrator says",
      "visual": "What's on screen / B-roll description",
      "duration_sec": 15
    }},
    {{
      "section": "Intro",
      "timestamp": "0:15",
      "voiceover": "...",
      "visual": "...",
      "duration_sec": 30
    }}
    // ... continue for all sections through Outro/CTA
  ]
}}

Script sections should be: Hook → Intro → [3-5 main points] → Summary → CTA/Outro
Each voiceover section should read naturally at speaking pace.
Include B-roll suggestions in the visual field.
"""

    raw = llm_complete(prompt, max_tokens=4000)
    raw = re.sub(r"^```json\s*|```$", "", raw, flags=re.MULTILINE).strip()
    raw = re.sub(r"[\x00-\x1f]", "", raw)  # strip control characters

    try:
        package = json.loads(raw)
        print(f"[ContentGen] Script ready: '{package['title']}'")
        return package
    except json.JSONDecodeError as e:
        print(f"[ContentGen] JSON parse error: {e}")
        # Return a minimal fallback
        return {
            "title": idea["title"],
            "description": idea.get("hook", ""),
            "tags": idea.get("keywords", []),
            "thumbnail_prompt": f"YouTube thumbnail for: {idea['title']}",
            "script": [{"section": "Full", "timestamp": "0:00",
                        "voiceover": raw[:2000], "visual": "talking head", "duration_sec": 300}]
        }


# ── Thumbnail Generation ──────────────────────────────────────────────────────

def generate_thumbnail(prompt: str, video_title: str, idea_id: int) -> str | None:
    os.makedirs(OUTPUT_THUMB_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_THUMB_DIR, f"thumb_{idea_id}.jpg")

    # 1. Generate background image via Pollinations
    full_prompt = (
        f"YouTube thumbnail background, {prompt}, "
        "high contrast, bold colors, 16:9, vibrant, hyper-realistic, 4k"
    )
    encoded = requests.utils.quote(full_prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=1280&height=720&nologo=true"

    try:
        resp = requests.get(url, timeout=60, stream=True)
        if resp.status_code == 200:
            bg_path = out_path.replace(".jpg", "_bg.jpg")
            with open(bg_path, "wb") as f:
                for chunk in resp.iter_content(8192):
                    f.write(chunk)
            img = Image.open(bg_path).convert("RGB").resize((1280, 720))
        else:
            img = Image.new("RGB", (1280, 720), (20, 30, 60))
    except Exception:
        img = Image.new("RGB", (1280, 720), (20, 30, 60))

    draw = ImageDraw.Draw(img)

    # 2. Add semi-transparent overlay for readability
    overlay = Image.new("RGBA", (1280, 720), (0, 0, 0, 80))
    img.paste(overlay, (0, 0), overlay)

    # 3. Add text
    try:
        font_title = ImageFont.truetype("arialbd.ttf", 60)
        font_sub = ImageFont.truetype("arial.ttf", 36)
    except (OSError, IOError):
        try:
            font_title = ImageFont.truetype("arial.ttf", 60)
            font_sub = ImageFont.truetype("arial.ttf", 36)
        except (OSError, IOError):
            font_title = ImageFont.load_default()
            font_sub = ImageFont.load_default()

    # Title text (bold, centered)
    title = video_title[:50]
    try:
        bbox = draw.textbbox((0, 0), title, font=font_title)
        tw = bbox[2] - bbox[0]
    except Exception:
        tw = len(title) * 30
    tx = (1280 - tw) // 2
    ty = 360 - 30

    # Draw text shadow
    draw.text((tx + 3, ty + 3), title, fill="black", font=font_title)
    draw.text((tx, ty), title, fill="white", font=font_title)

    # Subtitle line
    subtitle = "Watch Now \u25B6"
    try:
        bbox = draw.textbbox((0, 0), subtitle, font=font_sub)
        sw = bbox[2] - bbox[0]
    except Exception:
        sw = len(subtitle) * 18
    sx = (1280 - sw) // 2
    sy = ty + 80
    draw.text((sx + 2, sy + 2), subtitle, fill="black", font=font_sub)
    draw.text((sx, sy), subtitle, fill="#FFD700", font=font_sub)

    img.save(out_path, quality=92)
    if os.path.exists(bg_path):
        os.remove(bg_path)
    print(f"[ContentGen] Thumbnail saved: {out_path}")
    return out_path


# ── Save Script to Disk ───────────────────────────────────────────────────────

def save_script(package: dict, idea_id: int) -> str:
    os.makedirs("data/scripts", exist_ok=True)
    path = f"data/scripts/script_{idea_id}.json"
    with open(path, "w") as f:
        json.dump(package, f, indent=2)
    return path


# ── Main callable ─────────────────────────────────────────────────────────────

def run_content_generator(idea: dict, overrides: dict = None) -> dict:
    """
    Given an idea dict (from DB), produce the full content package.
    Returns: {package, script_path, thumbnail_path}
    """
    OV = overrides or get_overrides()
    package = generate_script(idea, overrides=OV)
    script_path = save_script(package, idea["id"])
    thumbnail_path = generate_thumbnail(
        package.get("thumbnail_prompt", idea["title"]),
        package["title"],
        idea["id"]
    )
    return {
        "package": package,
        "script_path": script_path,
        "thumbnail_path": thumbnail_path,
    }


if __name__ == "__main__":
    # Quick test
    test_idea = {
        "id": 999,
        "title": "5 Money Mistakes That Keep You Broke in Your 20s",
        "hook": "Are you making these 5 money mistakes? Most people don't even know.",
        "keywords": ["money mistakes", "personal finance 20s", "saving money tips"]
    }
    result = run_content_generator(test_idea)
    print(json.dumps(result["package"], indent=2)[:1000])
