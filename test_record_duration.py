import subprocess
import time
import os
import sys
from pathlib import Path

# Create plugins directory
plugins_dir = Path("plugins")
plugins_dir.mkdir(exist_ok=True)

# Fetch stripchat.py plugin
import urllib.request
plugin_url = "https://raw.githubusercontent.com/nbtu/Streamlink-Stripchat-Plugin/master/stripchat.py"
req = urllib.request.Request(plugin_url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req) as resp:
    plugin_code = resp.read().decode("utf-8")

(plugins_dir / "stripchat.py").write_text(plugin_code, encoding="utf-8")
print(f"Saved stripchat plugin to {plugins_dir / 'stripchat.py'} ({len(plugin_code)} chars)")

# Test target
target = sys.argv[1] if len(sys.argv) > 1 else "https://stripchat.com/sashapearl23"
out_path = Path("test_stripchat.mp4")

cmd = [
    "streamlink",
    "--plugin-dirs", "plugins",
    "--loglevel", "info",
    target,
    "best",
    "-o", str(out_path),
]

print(f"Running command: {' '.join(cmd)}", flush=True)
p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

start = time.time()
while time.time() - start < 35:
    ret = p.poll()
    sz = out_path.stat().st_size if out_path.exists() else 0
    print(f"Elapsed: {time.time()-start:.1f}s, size: {sz/1024:.1f} KB, ret: {ret}", flush=True)
    if ret is not None:
        print("Streamlink exited!")
        break
    time.sleep(3)

if p.poll() is None:
    print("STILL RECORDING AFTER 35s! SUCCESS! Sending termination...", flush=True)
    p.terminate()
    try:
        p.wait(timeout=5)
    except:
        p.kill()

out, _ = p.communicate()
print("--- STREAMLINK LOG ---", flush=True)
print(out[-3000:], flush=True)

final_sz = out_path.stat().st_size if out_path.exists() else 0
print(f"FINAL FILE SIZE: {final_sz / (1024*1024):.2f} MB", flush=True)
