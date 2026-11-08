import subprocess, sys, json
import curl_cffi.requests as creq

print("=== 1. Testing Affiliate Public API ===")
try:
    r_aff = creq.get(
        "https://chaturbate.com/api/public/affiliates/onlinerooms/?wm=Z977X&client_ip=request_ip&limit=5",
        impersonate="chrome120",
        timeout=15,
    )
    print("Affiliate API status:", r_aff.status_code, "len:", len(r_aff.text))
    if r_aff.status_code == 200:
        data = r_aff.json()
        rooms = data.get("results", [])
        print("Online rooms count:", data.get("count"), "Sample:", [x.get("username") for x in rooms[:5]])
        if rooms:
            live_model = rooms[0].get("username")
        else:
            live_model = "bunnyblondy"
    else:
        print("Affiliate body:", r_aff.text[:300])
        live_model = "bunnyblondy"
except Exception as e:
    print("Affiliate API err:", e)
    live_model = "bunnyblondy"

for model in [live_model, "bunnyblondy", "sports_woman5"]:
    print(f"\n================ {model} ================")
    for imp in ["chrome120", "chrome124", "safari17_0", "firefox"]:
        try:
            s = creq.Session(impersonate=imp)
            r1 = s.get(
                f"https://chaturbate.com/api/chatvideocontext/{model}/",
                headers={"Accept": "application/json", "Referer": f"https://chaturbate.com/{model}/"},
                timeout=10,
            )
            print(f"[{imp} chatvideocontext] status={r1.status_code} len={len(r1.text)}")
            if r1.status_code == 200:
                d = r1.json()
                print("  room_status:", d.get("room_status"), "hls_source:", d.get("hls_source", "")[:100])
                break
            else:
                print("  body:", r1.text[:150].replace("\n", " "))
        except Exception as e:
            print(f"[{imp} chatvideocontext] err: {e}")

    # Test Page + CSRF + AJAX
    try:
        s = creq.Session(impersonate="chrome120")
        rp = s.get(f"https://chaturbate.com/{model}/", timeout=10)
        csrf = s.cookies.get("csrftoken", "")
        print(f"[page GET] status={rp.status_code} csrf={csrf[:10]} len={len(rp.text)} has_dossier={'initialRoomDossier' in rp.text}")
        r2 = s.post(
            "https://chaturbate.com/get_edge_hls_url_ajax/",
            data={"room_slug": model},
            headers={
                "X-Requested-With": "XMLHttpRequest",
                "X-CSRFToken": csrf,
                "Accept": "application/json",
                "Referer": f"https://chaturbate.com/{model}/",
                "Origin": "https://chaturbate.com",
            },
            timeout=10,
        )
        print(f"[ajax POST] status={r2.status_code} body={r2.text[:200]}")
    except Exception as e:
        print(f"[page/ajax] err: {e}")

    # 3. yt-dlp verbose simulate
    res = subprocess.run(
        [sys.executable, "-m", "yt_dlp", "--simulate", "--verbose", f"https://chaturbate.com/{model}/"],
        capture_output=True, text=True
    )
    print("[yt-dlp stdout]:", res.stdout[-400:])
    print("[yt-dlp stderr]:", res.stderr[-800:])
