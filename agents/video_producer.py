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

import os, sys, json, tempfile, time, subprocess, traceback, requests
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import numpy as np
from moviepy import (VideoFileClip, AudioFileClip,
                     CompositeVideoClip, concatenate_videoclips)
from moviepy.video.VideoClip import ColorClip, ImageClip
from imageio_ffmpeg import get_ffmpeg_exe
from config import PEXELS_API_KEY, OUTPUT_VIDEO_DIR


# ── Text-to-Speech (edge-tts — completely free) ───────────────────────────────

VOICE = "en-US-ChristopherNeural"  # Change to any edge-tts voice

def text_to_speech(text: str, out_path: str):
    result = subprocess.run(
        [sys.executable, "-m", "edge_tts", "--voice", VOICE, "--text", text, "--write-media", out_path],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120
    )
    if result.returncode != 0:
        raise RuntimeError(f"TTS failed (rc={result.returncode})")
    if not os.path.exists(out_path):
        raise RuntimeError("TTS produced no output file")


# ── Stock Video (Pexels — free tier: 200 req/hr, no watermark) ───────────────

def fetch_stock_clip(query: str, duration_sec: int, out_path: str) -> bool:
    """Download a Pexels stock video matching the query. Returns True on success."""
    if not PEXELS_API_KEY:
        print("[Producer] No Pexels key — using colour fill instead.")
        return False

    headers = {"Authorization": PEXELS_API_KEY}
    url = f"https://api.pexels.com/videos/search?query={requests.utils.quote(query)}&per_page=5&orientation=landscape"

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        data = resp.json()
        if not isinstance(data, dict):
            print(f"[Producer] Pexels: unexpected response type: {type(data).__name__}")
            return False
        videos = data.get("videos") or []
        if not videos:
            return False

        for v in videos:
            files = v.get("video_files") or []
            for f in sorted(files, key=lambda x: -(x.get("width") or 0)):
                link = f.get("link")
                quality = f.get("quality", "")
                if link and quality and "hd" in quality:
                    r = requests.get(link, timeout=60, stream=True)
                    with open(out_path, "wb") as fp:
                        for chunk in r.iter_content(65536):
                            fp.write(chunk)
                    return True
    except Exception as e:
        print(f"[Producer] Pexels error: {e}")
        traceback.print_exc()
    return False


# ── Fallback: Coloured title card ─────────────────────────────────────────────

SECTION_COLORS = {
    "Hook":    (26, 26, 46),
    "Intro":   (22, 33, 62),
    "Outro":   (15, 52, 96),
    "default": (26, 26, 26),
}

def make_title_card(text: str, duration: float, section: str = "default") -> ImageClip:
    bg_color = SECTION_COLORS.get(section, SECTION_COLORS["default"])
    img = Image.new("RGB", (1280, 720), bg_color)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 48)
    except (OSError, IOError):
        font = ImageFont.load_default()
    lines = text.split("\n")
    y_start = 540 - (len(lines) * 30)
    for line in lines:
        try:
            bbox = draw.textbbox((0, 0), line, font=font)
            w = bbox[2] - bbox[0]
        except Exception:
            w = len(line) * 24
        x = (1280 - w) // 2
        draw.text((x, y_start), line, fill="white", font=font)
        y_start += 60
    frame = np.array(img)
    clip = ImageClip(frame, duration=duration)
    return clip


# ── Main Assembly ─────────────────────────────────────────────────────────────

def produce_video(script_sections: list[dict], idea_id: int,
                  channel_name: str = "My Channel") -> str | None:
    """
    Assemble full video from script sections.
    Returns path to the output .mp4 file, or None on failure.
    """
    os.makedirs(OUTPUT_VIDEO_DIR, exist_ok=True)
    work_dir = os.path.join(OUTPUT_VIDEO_DIR, f"work_{idea_id}")
    os.makedirs(work_dir, exist_ok=True)
    clips = []

    try:
        for i, section in enumerate(script_sections):
            voiceover = section.get("voiceover", "")
            visual_desc = section.get("visual", section.get("section", "background"))
            duration_sec = section.get("duration_sec", 30)
            sec_name = section.get("section", "default")

            # 1. Generate TTS audio
            audio_path = os.path.join(work_dir, f"audio_{i}.mp3")
            try:
                print(f"[Producer] TTS section {i}...", flush=True)
                text_to_speech(voiceover, audio_path)
                audio_clip = AudioFileClip(audio_path)
                actual_duration = audio_clip.duration
                print(f"[Producer] Section {i} audio: {actual_duration:.1f}s", flush=True)
            except Exception as e:
                print(f"[Producer] TTS failed section {i}: {e}")
                actual_duration = duration_sec
                audio_clip = None

            # 2. Get video background
            video_path = os.path.join(work_dir, f"stock_{i}.mp4")
            has_stock = fetch_stock_clip(visual_desc, int(actual_duration), video_path)

            if has_stock:
                try:
                    bg = VideoFileClip(video_path)
                    if bg.duration < actual_duration:
                        loops = int(actual_duration / bg.duration) + 1
                        bg = concatenate_videoclips([bg] * loops).with_duration(actual_duration)
                    else:
                        bg = bg.with_duration(actual_duration)
                    bg_preview = bg.resized(height=720).to_RGB()
                    bg.close()
                    bg = bg_preview
                except Exception as e:
                    print(f"[Producer] Stock clip error: {e}")
                    bg = make_title_card(sec_name, actual_duration, sec_name)
            else:
                bg = make_title_card(f"{sec_name}\n\n{voiceover[:80]}...", actual_duration, sec_name)

            # 3. Attach audio to background
            if audio_clip:
                final_section = bg.with_audio(audio_clip)
            else:
                final_section = bg

            clips.append(final_section)

        if not clips:
            print("[Producer] No clips to assemble.")
            return None

        # 4. Concatenate all sections
        print(f"[Producer] Concatenating {len(clips)} sections...")
        final_video = concatenate_videoclips(clips, method="compose")

        out_path = os.path.join(OUTPUT_VIDEO_DIR, f"video_{idea_id}.mp4")
        print(f"[Producer] Rendering video to {out_path}...", flush=True)
        final_video.write_videofile(
            out_path,
            fps=24,
            codec="libx264",
            audio_codec="aac",
            logger=None,
            preset="ultrafast",
        )
        print(f"[Producer] Video saved: {out_path}", flush=True)
        final_video.close()
        for c in clips:
            try:
                c.close()
            except Exception:
                pass
        return out_path
    finally:
        # Clean up working files
        for f in os.listdir(work_dir):
            try:
                os.remove(os.path.join(work_dir, f))
            except Exception:
                pass
        try:
            os.rmdir(work_dir)
        except Exception:
            pass


# ── Shorts Clipping ────────────────────────────────────────────────────────────

def clip_short_from_long(video_path: str, script_path: str, idea_id: int,
                         max_sec: int = 60) -> str | None:
    """
    Extract the hook section from a long video and crop to 9:16 portrait for Shorts.
    Returns path to the Shorts clip, or None on failure.
    """
    with open(script_path) as f:
        package = json.load(f)
    sections = package.get("script", [])
    if not sections:
        print("[Producer] No sections found for short clip.")
        return None

    hook = sections[0]
    hook_duration = min(hook.get("duration_sec", 30), max_sec)

    out_dir = os.path.join(OUTPUT_VIDEO_DIR, f"work_{idea_id}")
    os.makedirs(out_dir, exist_ok=True)
    short_path = os.path.join(OUTPUT_VIDEO_DIR, f"short_{idea_id}.mp4")

    ffmpeg_path = get_ffmpeg_exe()
    # Use ffmpeg: cut first N sec, center-crop to 9:16 portrait, scale to 1080x1920
    cmd = [
        ffmpeg_path, "-y",
        "-ss", "0",
        "-i", video_path,
        "-t", str(hook_duration),
        "-vf", "crop=ih*9/16:ih,scale=1080:1920",
        "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac",
        short_path
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        if os.path.exists(short_path):
            print(f"[Producer] Short clipped: {short_path} ({hook_duration}s)")
            return short_path
    except Exception as e:
        print(f"[Producer] Short clip error: {e}")
    return None


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
