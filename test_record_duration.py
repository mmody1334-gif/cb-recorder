import subprocess
import time
import urllib.request
import os
from pathlib import Path

ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'

# 1. Inspect m3u8 playlist contents
master_url = 'https://edge-hls.doppiocdn.com/hls/131766698/master/131766698_auto.m3u8'
print('=== 1. Inspect Master M3U8 ===', flush=True)
try:
    req = urllib.request.Request(master_url, headers={'User-Agent': ua})
    with urllib.request.urlopen(req, timeout=10) as resp:
        m3u8_text = resp.read().decode('utf-8', errors='replace')
        print(m3u8_text, flush=True)
        # Find first sub-playlist
        for line in m3u8_text.splitlines():
            line = line.strip()
            if line and not line.startswith('#'):
                sub_url = line if line.startswith('http') else urllib.parse.urljoin(master_url, line)
                print('--- Sub Playlist URL:', sub_url, flush=True)
                req_sub = urllib.request.Request(sub_url, headers={'User-Agent': ua})
                with urllib.request.urlopen(req_sub, timeout=10) as resp_sub:
                    print(resp_sub.read().decode('utf-8', errors='replace'), flush=True)
                break
except Exception as e:
    print('Error fetching m3u8:', e, flush=True)

# 2. Test Streamlink directly on stripchat URL
print('=== 2. Test Streamlink on stripchat URL ===', flush=True)
cmd_sl = ['streamlink', '--loglevel', 'info', 'https://stripchat.com/TUNDEROSE1', 'best', '-o', 'test_streamlink.mp4']
p_sl = subprocess.Popen(cmd_sl, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
start = time.time()
while time.time() - start < 15:
    if p_sl.poll() is not None:
        print(f'Streamlink exited at {time.time() - start:.1f}s with code {p_sl.poll()}!', flush=True)
        break
    time.sleep(3)
    sz = Path('test_streamlink.mp4').stat().st_size if Path('test_streamlink.mp4').exists() else 0
    print(f'Streamlink: elapsed={time.time() - start:.1f}s, size={sz / 1024:.1f} KB', flush=True)

if p_sl.poll() is None:
    print('Streamlink SUCCESS! Kept recording! Stopping it...', flush=True)
    p_sl.terminate()
    try:
        p_sl.wait(timeout=5)
    except Exception:
        p_sl.kill()

out_sl, _ = p_sl.communicate()
print('Streamlink output tail:
', out_sl[-1000:], flush=True)

# 3. Test yt-dlp on master_url
print('=== 3. Test yt-dlp on master_url ===', flush=True)
cmd_ydl = ['yt-dlp', '--no-part', '--hls-use-mpegts', master_url, '-o', 'test_ytdlp.mp4']
p_ydl = subprocess.Popen(cmd_ydl, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
start = time.time()
while time.time() - start < 15:
    if p_ydl.poll() is not None:
        print(f'yt-dlp exited at {time.time() - start:.1f}s with code {p_ydl.poll()}!', flush=True)
        break
    time.sleep(3)
    sz = Path('test_ytdlp.mp4').stat().st_size if Path('test_ytdlp.mp4').exists() else 0
    print(f'yt-dlp: elapsed={time.time() - start:.1f}s, size={sz / 1024:.1f} KB', flush=True)

if p_ydl.poll() is None:
    print('yt-dlp SUCCESS! Kept recording! Stopping it...', flush=True)
    p_ydl.terminate()
    try:
        p_ydl.wait(timeout=5)
    except Exception:
        p_ydl.kill()

out_ydl, _ = p_ydl.communicate()
print('yt-dlp output tail:
', out_ydl[-1000:], flush=True)
