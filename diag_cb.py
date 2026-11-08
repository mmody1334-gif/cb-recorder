import subprocess, sys, json, time
import curl_cffi.requests as creq

TARGETS = ["safari17_0", "safari15_5", "safari15_3", "chrome110", "chrome116", "chrome120", "chrome124", "edge101"]

print("=== Testing Impersonation Targets on get_edge_hls_url_ajax ===")
m3u8_found = None
for tld in ["com", "eu", "global"]:
    for imp in TARGETS:
        try:
            r = creq.post(
                f"https://chaturbate.{tld}/get_edge_hls_url_ajax/",
                data={"room_slug": "bunnyblondy"},
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json",
                },
                impersonate=imp,
                timeout=10,
            )
            print(f"[{tld} | {imp}] status={r.status_code} body={r.text[:180]}")
            if r.status_code == 200 and r.text.strip().startswith("{"):
                data = r.json()
                if data.get("url"):
                    m3u8_found = data["url"]
        except Exception as e:
            print(f"[{tld} | {imp}] err={e}")
    if m3u8_found:
        break

print("\nFound m3u8_url:", m3u8_found)

print("\n=== Testing actual yt-dlp 10s recording on bunnyblondy ===")
p = subprocess.Popen(
    [
        sys.executable, "-m", "yt_dlp",
        "--no-part", "--verbose",
        "-o", "test_ytdlp.mp4",
        "https://chaturbate.com/bunnyblondy/"
    ],
    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
)
try:
    out, _ = p.communicate(timeout=12)
    print("[yt-dlp exited early with code", p.returncode, "]")
    print(out)
except subprocess.TimeoutExpired:
    p.terminate()
    out, _ = p.communicate()
    print("[yt-dlp ran for 12s! Output]:")
    print(out[-1500:])

import os
if os.path.exists("test_ytdlp.mp4"):
    print("test_ytdlp.mp4 size:", os.path.getsize("test_ytdlp.mp4"))

if m3u8_found:
    print("\n=== Testing direct ffmpeg 10s recording on m3u8_found ===")
    p2 = subprocess.run(
        ["ffmpeg", "-y", "-i", m3u8_found, "-t", "8", "-c", "copy", "-bsf:a", "aac_adtstoasc", "test_ffmpeg.mp4"],
        capture_output=True, text=True, timeout=25
    )
    print("ffmpeg returncode:", p2.returncode)
    print("ffmpeg stderr tail:", p2.stderr[-800:])
    if os.path.exists("test_ffmpeg.mp4"):
        print("test_ffmpeg.mp4 size:", os.path.getsize("test_ffmpeg.mp4"))
