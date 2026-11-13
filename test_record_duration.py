import subprocess
import time
import os
import sys
from pathlib import Path

url = 'https://edge-hls.doppiocdn.com/hls/131766698/master/131766698_auto.m3u8'
out_path = Path('test_recording.mp4')
ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'

print('=== Test 1: ffmpeg with -reconnect_at_eof 1 ===', flush=True)
cmd = [
    'ffmpeg',
    '-y',
    '-hide_banner',
    '-loglevel', 'info',
    '-user_agent', ua,
    '-reconnect', '1',
    '-reconnect_at_eof', '1',
    '-reconnect_streamed', '1',
    '-reconnect_delay_max', '5',
    '-fflags', '+nobuffer+discardcorrupt',
    '-i', url,
    '-c', 'copy',
    '-bsf:a', 'aac_adtstoasc',
    '-movflags', '+faststart',
    str(out_path),
]

p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
start = time.time()
while time.time() - start < 35:
    ret = p.poll()
    if ret is not None:
        print(f'FFMPEG EXITED PREMATURELY at {time.time() - start:.1f}s with code {ret}!', flush=True)
        out, _ = p.communicate()
        print('--- FFMPEG OUTPUT ---', flush=True)
        print(out[-2000:], flush=True)
        break
    time.sleep(3)
    sz = out_path.stat().st_size if out_path.exists() else 0
    print(f'Recording: elapsed={time.time() - start:.1f}s, size={sz / 1024:.1f} KB', flush=True)

if p.poll() is None:
    print('Still running after 35s! Success! Sending graceful stop...', flush=True)
    try:
        p.stdin.write('q\\n')
        p.stdin.flush()
    except Exception as e:
        print('Error writing q:', e, flush=True)
    try:
        p.wait(timeout=10)
    except Exception:
        p.kill()
    print('Stopped gracefully!', flush=True)

final_sz = out_path.stat().st_size if out_path.exists() else 0
print(f'Final file size: {final_sz / (1024*1024):.2f} MB', flush=True)
