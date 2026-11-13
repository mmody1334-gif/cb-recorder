import urllib.request
import json
import subprocess
import time
from pathlib import Path

ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'

# Get live public models
api_url = 'https://stripchat.com/api/front/v2/models?limit=10&sortBy=popularity'
req = urllib.request.Request(api_url, headers={'User-Agent': ua})
with urllib.request.urlopen(req) as resp:
    data = json.loads(resp.read().decode())
    models = data.get('models', [])

public_model = None
for m in models:
    u = m.get('user', {})
    status = u.get('status')
    is_live = u.get('isLive')
    show = m.get('show')
    print(f"Model: {u.get('username')}, id: {u.get('id')}, status: {status}, is_live: {is_live}, show: {show}")
    if is_live and status == 'public' and not show:
        public_model = m
        break

if not public_model:
    print("No purely public model found in first 10, taking first with status == 'public'")
    for m in models:
        if m.get('user', {}).get('status') == 'public':
            public_model = m
            break

if public_model:
    m_user = public_model['user']['username']
    m_id = public_model['user']['id']
    print(f"\n>>> TESTING TRULY PUBLIC MODEL: {m_user} (ID: {m_id}) <<<")
    
    # Check HLS
    hls_url = f"https://edge-hls.doppiocdn.com/hls/{m_id}/master/{m_id}_auto.m3u8"
    print(f"HLS URL: {hls_url}")
    
    # Record for 20 seconds with ffmpeg
    out_file = Path("test_public.mp4")
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel", "info",
        "-user_agent", ua,
        "-reconnect", "1",
        "-reconnect_at_eof", "1",
        "-reconnect_streamed", "1",
        "-reconnect_delay_max", "5",
        "-fflags", "+nobuffer+discardcorrupt",
        "-i", hls_url,
        "-c", "copy",
        "-bsf:a", "aac_adtstoasc",
        "-movflags", "+faststart",
        str(out_file),
    ]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    start = time.time()
    for _ in range(8):
        time.sleep(3)
        ret = p.poll()
        sz = out_file.stat().st_size if out_file.exists() else 0
        print(f"Elapsed: {time.time()-start:.1f}s, size: {sz/1024:.1f} KB, ret: {ret}")
        if ret is not None:
            print("FFMPEG exited early!")
            out, _ = p.communicate()
            print("Output tail:\n", out[-1000:])
            break
    
    if p.poll() is None:
        print("STILL RUNNING PERFECTLY! Gracefully stopping...")
        try:
            p.stdin.write('q\n')
            p.stdin.flush()
        except:
            p.terminate()
        p.wait(timeout=5)
        final_sz = out_file.stat().st_size if out_file.exists() else 0
        print(f"SUCCESS! Recorded public stream! Final size: {final_sz/(1024*1024):.2f} MB")
