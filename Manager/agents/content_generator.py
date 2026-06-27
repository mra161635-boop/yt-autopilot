"""
agents/content_generator.py — script + thumbnail generator.
Respects Gemini Manager directives: script instructions, hook style, CTA, thumbnail style.
"""

import json, re, os, requests
from anthropic import Anthropic
from config import (ANTHROPIC_API_KEY, CHANNEL_NICHE, CHANNEL_STYLE,
                    TARGET_AUDIENCE, CHANNEL_NAME, VIDEO_LENGTH_MIN,
                    VIDEO_LENGTH_MAX, CLAUDE_MODEL, OUTPUT_THUMB_DIR)
from utils.overrides import get_overrides, override

client = Anthropic(api_key=ANTHROPIC_API_KEY)


def generate_script(idea: dict, overrides: dict = None) -> dict:
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

Write a complete production-ready video package. Return ONLY valid JSON:
{{
  "title": "Final YouTube title",
  "description": "Full YouTube description (400-600 words) with timestamps, CTA, hashtags",
  "tags": ["tag1","tag2",...],
  "thumbnail_prompt": "Detailed image-gen prompt for thumbnail{'. Style: ' + thumb_style if thumb_style else ''}",
  "script": [
    {{
      "section": "Hook",
      "timestamp": "0:00",
      "voiceover": "Exact narrator words",
      "visual": "B-roll / on-screen description",
      "duration_sec": 15
    }}
  ]
}}
Script sections: Hook → Intro → [3-5 main points] → Summary → CTA/Outro"""

    resp = client.messages.create(
        model=CLAUDE_MODEL, max_tokens=4000,
        messages=[{"role": "user", "content": prompt}]
    )
    raw = resp.content[0].text.strip()
    raw = re.sub(r"^```json\s*|```$", "", raw, flags=re.MULTILINE).strip()

    try:
        package = json.loads(raw)
        print(f"[ContentGen] Script ready: '{package['title']}'")
        return package
    except json.JSONDecodeError:
        return {
            "title": idea["title"],
            "description": idea.get("hook", ""),
            "tags": idea.get("keywords", []),
            "thumbnail_prompt": f"YouTube thumbnail for: {idea['title']}",
            "script": [{"section": "Full", "timestamp": "0:00",
                        "voiceover": raw[:2000], "visual": "talking head", "duration_sec": 300}]
        }


def generate_thumbnail(prompt: str, idea_id: int) -> str | None:
    encoded = requests.utils.quote(
        f"YouTube thumbnail, {prompt}, high contrast, bold colors, eye-catching, professional, 16:9"
    )
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=1280&height=720&nologo=true"
    os.makedirs(OUTPUT_THUMB_DIR, exist_ok=True)
    out_path = os.path.join(OUTPUT_THUMB_DIR, f"thumb_{idea_id}.jpg")
    try:
        resp = requests.get(url, timeout=60, stream=True)
        if resp.status_code == 200:
            with open(out_path, "wb") as f:
                for chunk in resp.iter_content(8192):
                    f.write(chunk)
            return out_path
    except Exception as e:
        print(f"[ContentGen] Thumbnail error: {e}")
    return None


def save_script(package: dict, idea_id: int) -> str:
    os.makedirs("data/scripts", exist_ok=True)
    path = f"data/scripts/script_{idea_id}.json"
    with open(path, "w") as f:
        json.dump(package, f, indent=2)
    return path


def run_content_generator(idea: dict, overrides: dict = None) -> dict:
    OV = overrides or get_overrides()
    package        = generate_script(idea, overrides=OV)
    script_path    = save_script(package, idea["id"])
    thumbnail_path = generate_thumbnail(package.get("thumbnail_prompt", idea["title"]), idea["id"])
    return {"package": package, "script_path": script_path, "thumbnail_path": thumbnail_path}
