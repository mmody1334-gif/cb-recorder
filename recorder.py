"""Live Stream Recorder Daemon & Multi-Host Uploader (Chaturbate & TikTok Live).

Records live streams in the background, finalizes the MP4 when stopped or
when the broadcast ends, uploads the result to high-capacity hosting (Pixeldrain / Gofile / Local),
and sends the download link directly to the user's Telegram chat.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
import urllib.request
import urllib.parse

logger = logging.getLogger("recorder")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

MEDIA_DIR = Path(os.getenv("MEDIA_DIR", "./recordings_data"))
RECORDINGS_DIR = MEDIA_DIR / "recordings"
RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)

# Active recording jobs: identifier -> RecordingJob
active_jobs: Dict[str, "RecordingJob"] = {}
jobs_lock = threading.Lock()


def parse_stream_target(target: str) -> Tuple[str, str, str]:
    """
    Parses input and returns (platform, identifier, stream_url).
    platform: 'tiktok' | 'chaturbate' | 'unknown'
    identifier: e.g. 'visceratio' or 'shad.208'
    stream_url: full URL passed to yt-dlp
    """
    clean = target.strip()
    if not clean:
        return "unknown", "", ""

    # 1. TikTok short or live URL
    if "tiktok.com" in clean:
        if "vt.tiktok.com" in clean or "vm.tiktok.com" in clean or "/t/" in clean:
            try:
                req = urllib.request.Request(
                    clean,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
                    },
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    clean = resp.geturl()
            except Exception as e:
                logger.warning(f"Could not resolve short TikTok URL redirect: {e}")

        m = re.search(r"@([a-zA-Z0-9_.-]+)", clean)
        user = m.group(1) if m else "tiktok_live"
        live_url = clean if "/live" in clean else f"https://www.tiktok.com/@{user}/live"
        return "tiktok", user, live_url

    # 2. Starts with @ (e.g. @shad.208) -> TikTok live
    if clean.startswith("@"):
        user = clean.lstrip("@").strip()
        return "tiktok", user, f"https://www.tiktok.com/@{user}/live"

    # 3. Chaturbate URL
    cb_match = re.search(r"chaturbate\.com/(?:b/)?([a-zA-Z0-9_.-]+)", clean)
    if cb_match:
        model = cb_match.group(1).lower()
        return "chaturbate", model, f"https://chaturbate.com/{model}/"

    # 4. Default alphanumeric: assume Chaturbate model name
    if re.fullmatch(r"[a-zA-Z0-9_.-]{3,60}", clean):
        return "chaturbate", clean.lower(), f"https://chaturbate.com/{clean.lower()}/"

    return "unknown", clean, clean


def upload_to_pixeldrain(file_path: Path) -> Optional[str]:
    """Uploads file to Pixeldrain (supports up to 10GB per file, free, no auth)."""
    try:
        filename = file_path.name
        url = f"https://pixeldrain.com/api/file/{urllib.parse.quote(filename)}"
        
        req = urllib.request.Request(
            url,
            method="PUT",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) savelink-recorder/1.0",
            },
        )
        with open(file_path, "rb") as f:
            with urllib.request.urlopen(req, data=f, timeout=600) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("success"):
                    file_id = data.get("id")
                    return f"https://pixeldrain.com/u/{file_id}"
    except Exception as e:
        logger.error(f"Pixeldrain upload failed: {e}")
    return None


def upload_to_gofile(file_path: Path) -> Optional[str]:
    """Uploads file to Gofile (supports unlimited size, free)."""
    try:
        srv_req = urllib.request.Request(
            "https://api.gofile.io/servers",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        with urllib.request.urlopen(srv_req, timeout=15) as resp:
            srv_data = json.loads(resp.read().decode("utf-8"))
            server = srv_data.get("data", {}).get("servers", [{}])[0].get("name")
            if not server:
                return None

        import requests
        with open(file_path, "rb") as f:
            up_resp = requests.post(
                f"https://{server}.gofile.io/contents/uploadfile",
                files={"file": (file_path.name, f)},
                timeout=600,
            )
            up_data = up_resp.json()
            if up_data.get("status") == "ok":
                return up_data.get("data", {}).get("downloadPage")
    except Exception as e:
        logger.error(f"Gofile upload failed: {e}")
    return None


def notify_telegram(bot_token: str, chat_id: int | str, text: str, download_url: Optional[str] = None) -> None:
    """Send completion notification to user with direct download button."""
    if not bot_token or not chat_id:
        return
    try:
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
        if download_url:
            payload["reply_markup"] = {
                "inline_keyboard": [
                    [{"text": "🚀 تحميل ومشاهدة البث المسجل", "url": download_url}],
                ]
            }
        
        req = urllib.request.Request(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            headers={"Content-Type": "application/json"},
            data=json.dumps(payload).encode("utf-8"),
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
    except Exception as e:
        logger.error(f"Failed to send Telegram notification: {e}")


class RecordingJob:
    def __init__(self, platform: str, identifier: str, stream_url: str, chat_id: int | str, bot_token: str = ""):
        self.platform = platform
        self.identifier = identifier
        self.stream_url = stream_url
        self.chat_id = chat_id
        self.bot_token = bot_token
        self.start_time = time.time()
        self.stop_requested = False
        self.process: Optional[subprocess.Popen] = None
        
        now_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.filename = f"{self.platform}_{self.identifier}_{now_str}.mp4"
        self.output_path = RECORDINGS_DIR / self.filename
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.final_url: Optional[str] = None
        self.error: Optional[str] = None

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_requested = True
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass

    def _run(self):
        logger.info(f"Starting recording for {self.identifier} on {self.platform} -> {self.output_path}")

        # Command to record with yt-dlp
        cmd = [
            sys.executable,
            "-m",
            "yt_dlp",
            "--no-part",
            "--no-warnings",
            "-o",
            str(self.output_path),
            self.stream_url,
        ]

        log_path = RECORDINGS_DIR / f"{self.filename}.log"
        try:
            with open(log_path, "w", encoding="utf-8", errors="replace") as log_file:
                self.process = subprocess.Popen(cmd, stdout=log_file, stderr=subprocess.STDOUT)
                self.process.wait()
        except Exception as e:
            self.error = str(e)
            logger.error(f"Error recording {self.identifier}: {e}")

        # Job completed or stopped
        with jobs_lock:
            if self.identifier in active_jobs:
                del active_jobs[self.identifier]

        file_exists = self.output_path.exists() and self.output_path.stat().st_size > 50 * 1024
        platform_name = "TikTok Live" if self.platform == "tiktok" else "Chaturbate"

        if not file_exists:
            logger.warning(f"Recording for {self.identifier} on {platform_name} resulted in empty or non-existent file.")
            notify_telegram(
                self.bot_token,
                self.chat_id,
                f"⚠️ انتهت جلسة البث أو كان حساب <b>{self.identifier}</b> على {platform_name} غير مباشر حالياً (Offline).",
            )
            return

        size_bytes = self.output_path.stat().st_size
        size_mb = size_bytes / (1024 * 1024)
        size_str = f"{size_mb:.1f} MB" if size_mb < 1024 else f"{(size_mb / 1024):.2f} GB"
        duration_sec = int(time.time() - self.start_time)
        hours, rem = divmod(duration_sec, 3600)
        minutes, seconds = divmod(rem, 60)
        duration_str = f"{hours}h {minutes}m {seconds}s" if hours else f"{minutes}m {seconds}s"

        logger.info(f"Recording finished for {self.identifier} on {platform_name}: {size_str}, uploading...")

        # 1. Try Pixeldrain
        download_url = upload_to_pixeldrain(self.output_path)
        # 2. Try Gofile if Pixeldrain failed
        if not download_url:
            download_url = upload_to_gofile(self.output_path)

        self.final_url = download_url
        if download_url:
            msg = (
                f"✅ <b>تم اكتمال تسجيل بث {platform_name} بنجاح!</b>\n\n"
                f"👤 <b>الحساب:</b> <code>{self.identifier}</code>\n"
                f"⏱️ <b>المدة:</b> {duration_str}\n"
                f"📦 <b>الحجم:</b> {size_str}\n"
                f"🔗 <b>الرابط المباشر للمشاهدة والتحميل السريع:</b>\n{download_url}"
            )
        else:
            msg = (
                f"✅ <b>تم إنهاء تسجيل بث {platform_name} محلياً!</b>\n\n"
                f"👤 <b>الحساب:</b> <code>{self.identifier}</code>\n"
                f"⏱️ <b>المدة:</b> {duration_str}\n"
                f"📦 <b>الحجم:</b> {size_str}\n"
                f"📁 <b>اسم الملف:</b> <code>{self.filename}</code>"
            )

        notify_telegram(self.bot_token, self.chat_id, msg, download_url)


def start_recording(model_or_url: str, chat_id: int | str, bot_token: str = "") -> Dict[str, Any]:
    platform, identifier, stream_url = parse_stream_target(model_or_url)
    if platform == "unknown":
        return {"ok": False, "error": "الرابط أو اسم الحساب غير صالح"}

    with jobs_lock:
        if identifier in active_jobs:
            return {"ok": False, "error": f"التسجيل قيد العمل بالفعل لـ: {identifier}"}

        job = RecordingJob(platform, identifier, stream_url, chat_id, bot_token)
        active_jobs[identifier] = job
        job.start()

    return {"ok": True, "model": identifier, "platform": platform, "start_time": job.start_time}


def stop_recording(model_or_url: str) -> Dict[str, Any]:
    platform, identifier, _ = parse_stream_target(model_or_url)
    key = identifier if platform != "unknown" else model_or_url.strip()

    with jobs_lock:
        job = active_jobs.get(key)
        if not job:
            return {"ok": False, "error": f"لا يوجد تسجيل نشط حالياً لـ: {key}"}
        job.stop()

    return {"ok": True, "model": key, "message": "جاري إيقاف التسجيل وتجهيز الفيديو للرفع..."}


def list_active_recordings() -> Dict[str, Any]:
    with jobs_lock:
        items = []
        for key, job in active_jobs.items():
            elapsed = int(time.time() - job.start_time)
            size = job.output_path.stat().st_size if job.output_path.exists() else 0
            size_mb = size / (1024 * 1024)
            items.append({
                "model": job.identifier,
                "platform": job.platform,
                "elapsed_seconds": elapsed,
                "size_mb": round(size_mb, 2),
            })
    return {"ok": True, "recordings": items}


if __name__ == "__main__":
    import signal

    if len(sys.argv) < 3:
        print("Usage: python recorder.py <target_url_or_user> <chat_id> [bot_token]")
        sys.exit(1)

    cli_target = sys.argv[1]
    cli_chat = sys.argv[2]
    cli_token = sys.argv[3] if len(sys.argv) > 3 else os.getenv("BOT_TOKEN", "")

    platform, identifier, stream_url = parse_stream_target(cli_target)
    if platform == "unknown":
        print(f"Error: Invalid stream target: {cli_target}")
        sys.exit(1)

    print(f"Starting CLI recording for {identifier} on {platform} (chat_id: {cli_chat})...")
    cli_job = RecordingJob(platform, identifier, stream_url, cli_chat, cli_token)

    def _sig_handler(sig, frame):
        print("\nInterrupt received, stopping recording and uploading...")
        cli_job.stop()

    signal.signal(signal.SIGINT, _sig_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _sig_handler)

    cli_job._run()
