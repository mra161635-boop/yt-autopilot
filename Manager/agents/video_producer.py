"""
agents/video_producer.py — assembles the final video file.

Pipeline:
  1. Convert each script section's voiceover to audio via edge-tts (100% free)
  2. Fetch relevant free stock video clips from Pexels (free API, 200 req/hr)
  3. Assemble clips + audio + title cards using MoviePy
  4. Export final .mp4

Requirements:
  pip install edge-tts moviepy requests imageio-ffmpeg
  (ffmpeg is bundled with imageio-ffmpeg — no separate install needed)
"""

import asyncio, os, json, tempfile, requests
from pathlib import Path
import edge_tts
from moviepy.editor import (VideoFileClip, AudioFileClip, TextClip,
                             CompositeVideoClip, concatenate_videoclips,
                             ColorClip)
from config import PEXELS_API_KEY, OUTPUT_VIDEO_DIR


# ── Text-to-Speech (edge-tts — completely free) ───────────────────────────────

VOICE = "en-US-ChristopherNeural"  # Change to any edge-tts voice

async def _tts_section(text: str, out_path: str):
    communicate = edge_tts.Communicate(text, VOICE)
    await communicate.save(out_path)


def text_to_speech(text: str, out_path: str):
    asyncio.run(_tts_section(text, out_path))


# ── Stock Video (Pexels — free tier: 200 req/hr, no watermark) ───────────────

def fetch_stock_clip(query: str, duration_sec: int, out_path: str) -> bool:
    """Download a Pexels stock video matching the query. Returns True on success."""
    if not PEXELS_API_KEY:
        print("[Producer] No Pexels key — using colour fill instead.")
        return False

    headers = {"Authorization": PEXELS_API_KEY}
    url = f"https://api.pexels.com/videos/search?query={requests.utils.quote(query)}&per_page=5&orientation=landscape"

    try:
        resp = requests.get(url, headers=headers, timeout=15).json()
        videos = resp.get("videos", [])
        if not videos:
            return False

        # Pick first video with a file close to the needed duration
        for v in videos:
            for f in sorted(v["video_files"], key=lambda x: -x.get("width", 0)):
                if f.get("link") and "hd" in f.get("quality",""):
                    r = requests.get(f["link"], timeout=60, stream=True)
                    with open(out_path, "wb") as fp:
                        for chunk in r.iter_content(65536):
                            fp.write(chunk)
                    return True
    except Exception as e:
        print(f"[Producer] Pexels error: {e}")
    return False


# ── Fallback: Coloured title card ─────────────────────────────────────────────

SECTION_COLORS = {
    "Hook":    "#1a1a2e",
    "Intro":   "#16213e",
    "Outro":   "#0f3460",
    "default": "#1a1a1a",
}

def make_title_card(text: str, duration: float, section: str = "default") -> ColorClip:
    color_hex = SECTION_COLORS.get(section, SECTION_COLORS["default"])
    # Convert hex to RGB
    r, g, b = tuple(int(color_hex.lstrip("#")[i:i+2], 16) for i in (0, 2, 4))
    clip = ColorClip(size=(1920, 1080), color=(r, g, b), duration=duration)
    try:
        txt = TextClip(text, fontsize=60, color="white", font="Arial-Bold",
                       size=(1600, None), method="caption")
        txt = txt.set_position("center").set_duration(duration)
        return CompositeVideoClip([clip, txt])
    except Exception:
        return clip  # fallback if ImageMagick not available


# ── Main Assembly ─────────────────────────────────────────────────────────────

def produce_video(script_sections: list[dict], idea_id: int,
                  channel_name: str = "My Channel") -> str | None:
    """
    Assemble full video from script sections.
    Returns path to the output .mp4 file, or None on failure.
    """
    os.makedirs(OUTPUT_VIDEO_DIR, exist_ok=True)
    clips = []
    tmp_files = []

    with tempfile.TemporaryDirectory() as tmpdir:
        for i, section in enumerate(script_sections):
            voiceover = section.get("voiceover", "")
            visual_desc = section.get("visual", section.get("section", "background"))
            duration_sec = section.get("duration_sec", 30)
            sec_name = section.get("section", "default")

            # 1. Generate TTS audio
            audio_path = os.path.join(tmpdir, f"audio_{i}.mp3")
            try:
                text_to_speech(voiceover, audio_path)
                audio_clip = AudioFileClip(audio_path)
                actual_duration = audio_clip.duration
            except Exception as e:
                print(f"[Producer] TTS failed section {i}: {e}")
                actual_duration = duration_sec
                audio_clip = None

            # 2. Get video background
            video_path = os.path.join(tmpdir, f"stock_{i}.mp4")
            has_stock = fetch_stock_clip(visual_desc, int(actual_duration), video_path)

            if has_stock:
                try:
                    bg = VideoFileClip(video_path)
                    # Loop if stock clip is shorter than audio
                    if bg.duration < actual_duration:
                        loops = int(actual_duration / bg.duration) + 1
                        from moviepy.editor import concatenate_videoclips as concat
                        bg = concat([bg] * loops).subclip(0, actual_duration)
                    else:
                        bg = bg.subclip(0, actual_duration)
                    bg = bg.resize((1920, 1080))
                except Exception as e:
                    print(f"[Producer] Stock clip error: {e}")
                    bg = make_title_card(sec_name, actual_duration, sec_name)
            else:
                bg = make_title_card(f"{sec_name}\n\n{voiceover[:80]}...", actual_duration, sec_name)

            # 3. Attach audio to background
            if audio_clip:
                final_section = bg.set_audio(audio_clip)
            else:
                final_section = bg

            clips.append(final_section)
            tmp_files.append(audio_path)

        if not clips:
            print("[Producer] No clips to assemble.")
            return None

        # 4. Concatenate all sections
        print(f"[Producer] Concatenating {len(clips)} sections...")
        final_video = concatenate_videoclips(clips, method="compose")

        out_path = os.path.join(OUTPUT_VIDEO_DIR, f"video_{idea_id}.mp4")
        final_video.write_videofile(
            out_path,
            fps=24,
            codec="libx264",
            audio_codec="aac",
            logger=None,
            preset="ultrafast",  # fast encode; change to "medium" for quality
        )
        print(f"[Producer] Video saved: {out_path}")
        return out_path


# ── Main callable ─────────────────────────────────────────────────────────────

def run_video_producer(script_path: str, idea_id: int, channel_name: str) -> str | None:
    with open(script_path) as f:
        package = json.load(f)
    return produce_video(package["script"], idea_id, channel_name)


if __name__ == "__main__":
    # Quick test with a minimal script
    test_script = [
        {"section": "Hook", "voiceover": "Did you know most people overpay on taxes every single year?",
         "visual": "money cash finance", "duration_sec": 5},
        {"section": "Main", "voiceover": "Here are three ways to keep more of your money.",
         "visual": "savings bank piggy", "duration_sec": 8},
    ]
    produce_video(test_script, idea_id=0, channel_name="TestChannel")
