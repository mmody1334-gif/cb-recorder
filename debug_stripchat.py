
import json
import re
import sys
from yt_dlp import YoutubeDL
from yt_dlp.extractor.stripchat import StripchatIE, lowercase_escape
from yt_dlp.utils import traverse_obj

ydl = YoutubeDL({'quiet': True})
ie = StripchatIE(ydl)
url = 'https://stripchat.com/TUNDEROSE1'

webpage = ie._download_webpage(url, 'TUNDEROSE1', headers=ie.geo_verification_headers())
data = ie._search_json(
    r'<script\b[^>]*>\s*window\.__PRELOADED_STATE__\s*=',
    webpage, 'data', 'TUNDEROSE1', transform_source=lowercase_escape)

model_id = traverse_obj(data, ('viewCam', 'model', 'id'))
print('MODEL_ID:', model_id)

# Print all hlsStreamHost or fallbackDomains
hosts = []
for h in traverse_obj(data, ('configV3', 'static', 'features', 'hlsFallback', 'fallbackDomains', ...)):
    hosts.append(h)
print('ConfigV3 fallbackDomains:', hosts)

hls_host = traverse_obj(data, ('configV3', 'static', 'hlsStreamHost'))
print('ConfigV3 hlsStreamHost:', hls_host)

# Check all keys in configV3.static
print('ConfigV3.static keys:', list(traverse_obj(data, ('configV3', 'static', {dict})) or {}))

# Test constructing HLS url with model_id
test_hosts = hosts or ['doppiocdn.com', 'b-hls-11.doppiocdn.com', 'b-hls-12.doppiocdn.com', 'b-hls-1.doppiocdn.com']
for th in test_hosts:
    candidate = f'https://edge-hls.{th}/hls/{model_id}/master/{model_id}_auto.m3u8' if not th.startswith('edge-') else f'https://{th}/hls/{model_id}/master/{model_id}_auto.m3u8'
    try:
        import urllib.request
        req = urllib.request.Request(candidate, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=4) as resp:
            print('SUCCESS URL:', candidate, 'STATUS:', resp.status)
            break
    except Exception as e:
        print('FAILED:', candidate, e)
