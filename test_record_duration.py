import json
import re
import urllib.request
import urllib.parse
from yt_dlp.extractor.stripchat import lowercase_escape
from yt_dlp.utils import traverse_obj

ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'
url = 'https://stripchat.com/TUNDEROSE1'

req = urllib.request.Request(url, headers={'User-Agent': ua})
with urllib.request.urlopen(req) as resp:
    html = resp.read().decode('utf-8', errors='replace')

m = re.search(r'<script\b[^>]*>\s*window\.__PRELOADED_STATE__\s*=\s*({.*?})\s*;</script>', html, re.DOTALL)
if m:
    raw = lowercase_escape(m.group(1))
    data = json.loads(raw)
    
    # Save a filtered summary
    print('--- viewCam.model ---')
    print(json.dumps(data.get('viewCam', {}).get('model', {}), indent=2)[:1000])
    
    print('--- viewCam.stream ---')
    print(json.dumps(data.get('viewCam', {}).get('stream', {}), indent=2)[:1000])

    print('--- fallbackDomains & hlsStreamHost ---')
    hosts = traverse_obj(data, ((('config', 'data'), ('configV3', 'static')), (
                (('features', 'featuresV2'), 'hlsFallback', 'fallbackDomains', ...), 'hlsStreamHost')))
    print('Hosts:', hosts)

    # Search for all occurrences of .m3u8 or hls in data
    data_str = json.dumps(data)
    for m in re.finditer(r'https?://[^\s"]+?(?:m3u8|hls)[^\s"]*', data_str):
        print('Found URL in state:', m.group(0))

    # Also check what WebSocket or API URLs exist
    for m in re.finditer(r'https?://[^\s"]+?(?:api|edge|live|stream)[^\s"]*', data_str):
        if 'doppio' in m.group(0) or 'stripchat' in m.group(0):
            print('Interesting URL:', m.group(0)[:120])
