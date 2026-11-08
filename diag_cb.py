import subprocess, sys, json, time, os, signal
import curl_cffi.requests as creq

TARGETS = ["safari17_0", "safari15_5", "safari15_3", "chrome110", "chrome116", "chrome120", "chrome124", "edge101"]

print("=== Testing Impersonation Targets on get_edge_hls_url_ajax ===", flush=True)
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
                    "Origin": f"https://chaturbate.{tld}",
                    "Referer": f"https://chaturbate.{tld}/bunnyblondy/",
                },
                impersonate=imp,
                timeout=10,
            )
            is_json = r.text.strip().startswith("{")
            print(f"[{tld} | {imp}] status={r.status_code} json={is_json} body={r.text[:160].replace(chr(10), ' ')}", flush=True)
            if r.status_code == 200 and is_json:
                data = r.json()
                if data.get("url"):
                    m3u8_found = data["url"]
        except Exception as e:
            print(f"[{tld} | {imp}] err={e}", flush=True)
    if m3u8_found:
        break

print("\nFound m3u8_url:", m3u8_found, flush=True)

if m3u8_found:
    # Also test standard non-LLHLS / non-CMAF m3u8 if applicable
    print("\n=== Fetching m3u8 playlist content ===", flush=True)
    r_m3u8 = creq.get(m3u8_found, timeout=10)
    print("m3u8 status:", r_m3u8.status_code, "content:\n", r_m3u8.text[:1000], flush=True)

    # Check if replacing cmaf/llhls gives standard single-stream ts m3u8!
    std_m3u8 = m3u8_found.replace("live-cmaf", "live-hls").replace("llhls.m3u8", "playlist.m3u8").replace("_fast", "")
    if std_m3u8 != m3u8_found:
        print("\n=== Testing converted standard HLS URL:", std_m3u8, "===", flush=True)
        r_std = creq.get(std_m3u8, timeout=10)
        print("std_m3u8 status:", r_std.status_code, "content:\n", r_std.text[:1000], flush=True)

    target_m3u8 = std_m3u8 if (std_m3u8 != m3u8_found and r_std.status_code == 200) else m3u8_found
    print("\n=== Testing direct ffmpeg 8s recording on target_m3u8 ===", flush=True)
    p2 = subprocess.run(
        ["ffmpeg", "-y", "-i", target_m3u8, "-t", "8", "-c", "copy", "-bsf:a", "aac_adtstoasc", "test_ffmpeg.mp4"],
        capture_output=True, text=True, timeout=30
    )
    print("ffmpeg returncode:", p2.returncode, flush=True)
    print("ffmpeg stderr tail:", p2.stderr[-800:], flush=True)
    if os.path.exists("test_ffmpeg.mp4"):
        print("test_ffmpeg.mp4 size:", os.path.getsize("test_ffmpeg.mp4"), flush=True)
