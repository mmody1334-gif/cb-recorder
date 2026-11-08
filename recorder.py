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

CB_IMPERSONATE_TARGETS = [
    "safari17_0",
    "safari15_5",
    "safari15_3",
    "chrome110",
    "chrome116",
    "edge101",
    "chrome120",
]


def resolve_chaturbate_stream(model: str) -> Dict[str, Any]:
    """
    Directly resolves Chaturbate live stream HLS/LL-HLS endpoints using curl_cffi
    with proven browser TLS fingerprints and Origin/Referer headers.
    Returns:
      {"ok": True, "room_status": "public", "video_url": ..., "audio_url": ..., "tld": ...}
      or {"ok": False, "room_status": "offline"|"private"|"away"|..., "error": ...}
    """
    try:
        import curl_cffi.requests as creq
    except ImportError:
        return {"ok": False, "room_status": "unknown", "error": "curl_cffi not installed"}

    last_status = "unknown"
    for tld in ["com", "eu", "global"]:
        for imp in CB_IMPERSONATE_TARGETS:
            try:
                s = creq.Session(impersonate=imp)
                headers = {
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json",
                    "Origin": f"https://chaturbate.{tld}",
                    "Referer": f"https://chaturbate.{tld}/{model}/",
                }
                r = s.post(
                    f"https://chaturbate.{tld}/get_edge_hls_url_ajax/",
                    data={"room_slug": model},
                    headers=headers,
                    timeout=10,
                )
                if r.status_code != 200 or not r.text.strip().startswith("{"):
                    continue

                data = r.json()
                room_status = (data.get("room_status") or "").strip().lower()
                m3u8_url = (data.get("url") or "").strip()

                if room_status:
                    last_status = room_status

                if not m3u8_url:
                    if room_status in ("offline", "private", "away", "hidden", "password protected"):
                        return {"ok": False, "room_status": room_status}
                    continue

                # Fetch master playlist once to extract session-bound video + audio chunklists
                r_pl = s.get(
                    m3u8_url,
                    headers={
                        "Referer": f"https://chaturbate.{tld}/{model}/",
                        "Origin": f"https://chaturbate.{tld}",
                    },
                    timeout=10,
                )
                if r_pl.status_code == 200 and "#EXTM3U" in r_pl.text:
                    base_host = "https://" + m3u8_url.split("/")[2]
                    vid_paths = re.findall(r'(/v1/edge/streams/[^\s"\']+_video_[^\s"\']+)', r_pl.text)
                    aud_paths = re.findall(r'URI="(/v1/edge/streams/[^\s"\']+_audio_[^\s"\']+)"', r_pl.text)
                    if vid_paths:
                        video_url = base_host + vid_paths[-1]
                        audio_url = (base_host + aud_paths[0]) if aud_paths else None
                        return {
                            "ok": True,
                            "room_status": "public",
                            "video_url": video_url,
                            "audio_url": audio_url,
                            "tld": tld,
                        }

                # Fallback: request a fresh unconsumed m3u8_url for direct ffmpeg input
                r_fresh = s.post(
                    f"https://chaturbate.{tld}/get_edge_hls_url_ajax/",
                    data={"room_slug": model},
                    headers=headers,
                    timeout=10,
                )
                if r_fresh.status_code == 200 and r_fresh.text.strip().startswith("{"):
                    fresh_url = (r_fresh.json().get("url") or "").strip()
                    if fresh_url:
                        return {
                            "ok": True,
                            "room_status": "public",
                            "video_url": fresh_url,
                            "audio_url": None,
                            "tld": tld,
                        }
            except Exception as e:
                logger.debug(f"Chaturbate resolve attempt ({tld}/{imp}) error: {e}")
                continue

    return {"ok": False, "room_status": last_status}


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
    cb_match = re.search(r"chaturbate\.(?:com|eu|global)/(?:b/)?([a-zA-Z0-9_.-]+)", clean, re.I)
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
                data = json.loads(resp.read().decode())
                file_id = data.get("id")
                if file_id:
                    return f"https://pixeldrain.com/u/{file_id}"
    except Exception as e:
        logger.error(f"Failed to upload to Pixeldrain: {e}")
    return None


def upload_to_gofile(file_path: Path) -> Optional[str]:
    """Fallback upload to Gofile (supports unlimited size)."""
    try:
        # 1. Get best server
        server_req = urllib.request.Request(
            "https://api.gofile.io/servers",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        )
        with urllib.request.urlopen(server_req, timeout=15) as resp:
            s_data = json.loads(resp.read().decode())
            servers = s_data.get("data", {}).get("servers", [])
            server = servers[0].get("name", "store1") if servers else "store1"

        # 2. Upload with curl multipart
        upload_url = f"https://{server}.gofile.io/contents/uploadfile"
        curl_cmd = [
            "curl",
            "-s",
            "-X", "POST",
            "-F", f"file=@{str(file_path)}",
            upload_url,
        ]
        res = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=600)
        if res.returncode == 0:
            up_data = json.loads(res.stdout)
            page_link = up_data.get("data", {}).get("downloadPage")
            if page_link:
                return page_link
    except Exception as e:
        logger.error(f"Failed to upload to Gofile: {e}")
    return None


def send_telegram_video(bot_token: str, chat_id: int | str, video_path: Path, caption: str) -> bool:
    """Sends video file directly to Telegram chat via multipart curl (works up to 50MB)."""
    if not bot_token or not chat_id or str(chat_id) == "0" or not video_path.exists():
        return False
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendVideo"
        curl_cmd = [
            "curl",
            "-s",
            "-X", "POST",
            url,
            "-F", f"chat_id={chat_id}",
            "-F", f"video=@{str(video_path)}",
            "-F", f"caption={caption}",
            "-F", "parse_mode=HTML",
            "-F", "supports_streaming=true",
        ]
        res = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=180)
        if res.returncode == 0 and '"ok":true' in res.stdout:
            logger.info(f"Direct video successfully sent to Telegram chat {chat_id}")
            return True
        else:
            logger.warning(f"Direct video upload failed: {res.stdout[:200]}")
    except Exception as e:
        logger.error(f"Failed sending video to Telegram: {e}")
    return False


def create_preview_clip(input_path: Path, output_preview_path: Path, duration_sec: int = 30) -> bool:
    """Creates a fast 30-second low-bitrate preview clip using ffmpeg for Telegram preview."""
    try:
        cmd = [
            "ffmpeg",
            "-y",
            "-ss", "00:00:05",
            "-i", str(input_path),
            "-t", str(duration_sec),
            "-vf", "scale=-2:480",
            "-c:v", "libx264",
            "-b:v", "500k",
            "-preset", "veryfast",
            "-c:a", "aac",
            "-b:a", "64k",
            str(output_preview_path),
        ]
        res = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        return res.returncode == 0 and output_preview_path.exists() and output_preview_path.stat().st_size > 10 * 1024
    except Exception as e:
        logger.error(f"Failed to create preview clip: {e}")
        return False


def notify_telegram(bot_token: str, chat_id: int | str, text: str, download_url: Optional[str] = None) -> None:
    """Send completion notification to user with direct download button."""
    if not bot_token or not chat_id or str(chat_id) == "0":
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

    def _poll_remote_stop(self):
        """Polls Cloudflare Worker signal to gracefully stop when user clicks Stop in Telegram."""
        worker_base = os.getenv("WORKER_URL", "https://savelink.ain-app.workers.dev").rstrip("/")
        poll_url = f"{worker_base}/api/record/signal?target={urllib.parse.quote(self.identifier)}"
        while not self.stop_requested and (self.process is None or self.process.poll() is None):
            try:
                req = urllib.request.Request(poll_url, headers={"User-Agent": "SaveLink-Recorder/1.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode())
                    if data.get("stop"):
                        logger.info(f"Stop signal received for {self.identifier}. Stopping recording gracefully...")
                        self.stop()
                        break
            except Exception:
                pass
            time.sleep(3)

    def stop(self):
        self.stop_requested = True
        if self.process and self.process.poll() is None:
            try:
                logger.info(f"Gracefully stopping recording process for {self.identifier}...")
                if self.process.stdin:
                    try:
                        self.process.stdin.write(b"q\n")
                        self.process.stdin.flush()
                    except Exception:
                        pass
                self.process.wait(timeout=12)
            except Exception:
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

        # Start remote stop poll thread
        poll_thread = threading.Thread(target=self._poll_remote_stop, daemon=True)
        poll_thread.start()

        log_path = RECORDINGS_DIR / f"{self.filename}.log"
        cb_room_status = "unknown"

        if self.platform == "chaturbate":
            info = resolve_chaturbate_stream(self.identifier)
            cb_room_status = info.get("room_status", "unknown")

            # If in Private Show or Away, wait up to 45 minutes for public stream to resume
            if not info.get("ok") and cb_room_status in ("private", "away", "hidden"):
                status_ar = "عرض خاص (Private Show)" if cb_room_status == "private" else "استراحة قصيرة (Away)"
                logger.info(f"{self.identifier} is currently in {cb_room_status}. Waiting automatically for public stream...")
                notify_telegram(
                    self.bot_token,
                    self.chat_id,
                    f"⏳ <b>الحساب <code>{self.identifier}</code> في {status_ar} حالياً!</b>\n\n"
                    f"🔄 السيرفر السحابي في <b>وضع الانتظار الذكي</b> الآن — سيبدأ تسجيل البث العام تلقائياً وبأعلى دقة (1080p) فور انتهاء العرض الخاص دون أي تدخل منك!",
                )
                for _ in range(180):  # 180 * 15s = 45 minutes
                    if self.stop_requested:
                        break
                    for _ in range(15):
                        if self.stop_requested:
                            break
                        time.sleep(1)
                    if self.stop_requested:
                        break
                    info = resolve_chaturbate_stream(self.identifier)
                    cb_room_status = info.get("room_status", cb_room_status)
                    if info.get("ok"):
                        logger.info(f"{self.identifier} is now PUBLIC! Starting recording...")
                        notify_telegram(
                            self.bot_token,
                            self.chat_id,
                            f"🟢 <b>انتهى العرض الخاص وعاد حساب <code>{self.identifier}</code> للبث العام! بدأ التسجيل السحابي الآن...</b>",
                        )
                        self.start_time = time.time()
                        break
                    if cb_room_status == "offline":
                        break

            if info.get("ok"):
                tld = info.get("tld", "com")
                ua = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
                hdrs = f"Referer: https://chaturbate.{tld}/{self.identifier}/\r\nOrigin: https://chaturbate.{tld}\r\n"
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel", "info",
                    "-user_agent", ua,
                    "-headers", hdrs,
                    "-reconnect", "1",
                    "-reconnect_streamed", "1",
                    "-reconnect_delay_max", "5",
                    "-i", info["video_url"],
                ]
                if info.get("audio_url"):
                    cmd += [
                        "-user_agent", ua,
                        "-headers", hdrs,
                        "-reconnect", "1",
                        "-reconnect_streamed", "1",
                        "-reconnect_delay_max", "5",
                        "-i", info["audio_url"],
                        "-map", "0:v:0",
                        "-map", "1:a:0",
                    ]
                cmd += [
                    "-c", "copy",
                    "-bsf:a", "aac_adtstoasc",
                    "-movflags", "+faststart",
                    str(self.output_path),
                ]
                try:
                    with open(log_path, "w", encoding="utf-8", errors="replace") as log_file:
                        self.process = subprocess.Popen(
                            cmd,
                            stdin=subprocess.PIPE,
                            stdout=log_file,
                            stderr=subprocess.STDOUT,
                        )
                        self.process.wait()
                except Exception as e:
                    self.error = str(e)
                    logger.error(f"Error recording {self.identifier} with ffmpeg: {e}")
        else:
            # TikTok Live or other platforms via yt-dlp
            cmd = [
                sys.executable,
                "-m",
                "yt_dlp",
                "--no-part",
                "--no-warnings",
                "--retries", "10",
                "--fragment-retries", "10",
                "--retry-sleep", "3",
                "-o",
                str(self.output_path),
                self.stream_url,
            ]
            try:
                with open(log_path, "w", encoding="utf-8", errors="replace") as log_file:
                    self.process = subprocess.Popen(
                        cmd,
                        stdin=subprocess.PIPE,
                        stdout=log_file,
                        stderr=subprocess.STDOUT,
                    )
                    self.process.wait()
            except Exception as e:
                self.error = str(e)
                logger.error(f"Error recording {self.identifier}: {e}")

        # Clear stop signal in worker so future recordings are unaffected
        try:
            worker_base = os.getenv("WORKER_URL", "https://savelink.ain-app.workers.dev").rstrip("/")
            clear_url = f"{worker_base}/api/record/signal/clear?target={urllib.parse.quote(self.identifier)}"
            req = urllib.request.Request(clear_url, headers={"User-Agent": "SaveLink-Recorder/1.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                resp.read()
        except Exception:
            pass

        # Job completed or stopped
        with jobs_lock:
            if self.identifier in active_jobs:
                del active_jobs[self.identifier]

        file_exists = self.output_path.exists() and self.output_path.stat().st_size > 50 * 1024
        platform_name = "TikTok Live" if self.platform == "tiktok" else "Chaturbate"

        if not file_exists:
            if cb_room_status == "private":
                err_reason = "في عرض خاص مستمر (Private Show / PVT) ولم يعد للبث العام خلال فترة الانتظار"
            elif cb_room_status == "away":
                err_reason = "متوقف مؤقتاً (Away)"
            elif cb_room_status == "password protected":
                err_reason = "محمي بكلمة مرور (Password Protected)"
            else:
                err_reason = "غير مباشر حالياً (Offline)"

            try:
                if log_path.exists():
                    log_text = log_path.read_text(encoding="utf-8", errors="ignore")
                    logger.info(f"Recorder log tail for {self.identifier}:\n{log_text[-800:]}")
                    if "private show" in log_text.lower() or "room is private" in log_text.lower():
                        err_reason = "في عرض خاص مشفر (Private Show / PVT)"
                    elif "offline" in log_text.lower():
                        err_reason = "غير مباشر حالياً (Offline)"
            except Exception:
                pass

            logger.warning(f"Recording for {self.identifier} on {platform_name} ended without file: {err_reason}")
            notify_telegram(
                self.bot_token,
                self.chat_id,
                f"⚠️ <b>تنبيه التسجيل ({platform_name}):</b>\n\n👤 الحساب: <code>{self.identifier}</code>\n❌ <b>الحالة:</b> {err_reason}.\n\n💡 <b>الحل التلقائي:</b> استخدم أمر المراقبة <code>/watch {self.identifier}</code> وسيسجل البوت تلقائياً أول ما يبدأ البث العام المجاني!",
            )
            return

        size_bytes = self.output_path.stat().st_size
        size_mb = size_bytes / (1024 * 1024)
        size_str = f"{size_mb:.1f} MB" if size_mb < 1024 else f"{(size_mb / 1024):.2f} GB"
        duration_sec = max(1, int(time.time() - self.start_time))
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
        logger.info(f"Uploaded URL for {self.identifier}: {download_url}")

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

        uploaded_direct = False
        if size_bytes <= 50 * 1024 * 1024:
            uploaded_direct = send_telegram_video(self.bot_token, self.chat_id, self.output_path, msg)
        else:
            preview_path = RECORDINGS_DIR / f"preview_{self.filename}"
            if create_preview_clip(self.output_path, preview_path):
                preview_caption = (
                    f"🎬 <b>معاينة سريعة للبث (30 ثانية):</b>\n"
                    f"👤 <code>{self.identifier}</code> | {size_str}\n\n"
                    f"🔗 <b>تحميل البث كاملاً بأعلى دقة:</b>\n{download_url}"
                )
                send_telegram_video(self.bot_token, self.chat_id, preview_path, preview_caption)
                try:
                    preview_path.unlink()
                except Exception:
                    pass

        # If not sent directly as full video, send message with download button
        if not uploaded_direct:
            notify_telegram(self.bot_token, self.chat_id, msg, download_url)

        if download_url:
            try:
                self.output_path.unlink()
            except Exception:
                pass


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

    print(f"Starting CLI recording for {identifier} on {platform} (chat_id: {cli_chat})...", flush=True)
    cli_job = RecordingJob(platform, identifier, stream_url, cli_chat, cli_token)

    def _sig_handler(sig, frame):
        print("\nInterrupt received, stopping recording and uploading...", flush=True)
        cli_job.stop()

    signal.signal(signal.SIGINT, _sig_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _sig_handler)

    cli_job._run()
