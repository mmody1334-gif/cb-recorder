import json
import re
from yt_dlp import YoutubeDL
from yt_dlp.extractor.stripchat import StripchatIE, lowercase_escape
from yt_dlp.utils import traverse_obj

username = 'TUNDEROSE1'
ydl = YoutubeDL({"quiet": True, "no_warnings": True})
ie = StripchatIE(ydl)
url = f"https://stripchat.com/{username}"
webpage = ie._download_webpage(url, username, headers=ie.geo_verification_headers())
data = ie._search_json(
    r'<script\b[^>]*>\s*window\.__PRELOADED_STATE__\s*=',
    webpage, 'data', username, transform_source=lowercase_escape)

model_id = traverse_obj(data, ('viewCam', 'model', 'id'))
is_live = traverse_obj(data, ('viewCam', 'model', 'isLive'))
status = traverse_obj(data, ('viewCam', 'model', 'status'))
show = traverse_obj(data, ('viewCam', 'show', {dict}))
print(f"model_id: {model_id}, is_live: {is_live}, status: {status}, show: {show}")

# Find all hosts
hosts = traverse_obj(data, ((('config', 'data'), ('configV3', 'static')), (
            (('features', 'featuresV2'), 'hlsFallback', 'fallbackDomains', ...), 'hlsStreamHost')))
print("Hosts in data:", hosts)

# Also check features related to hls or mouflon
features = traverse_obj(data, (('config', 'data'), ('configV3', 'static'), 'features'))
print("Features keys:", list(features.keys()) if isinstance(features, dict) else features)

# Check stream info
stream = traverse_obj(data, ('viewCam', 'stream'))
print("Stream object:", stream)

# Check user object
user = traverse_obj(data, ('user', {dict}))
print("User keys:", list(user.keys()) if isinstance(user, dict) else user)

# Look for m3u8 or b-hls in entire data
data_str = json.dumps(data)
urls = re.findall(r'https?://[^\s"]+?(?:m3u8|doppio|hls)[^\s"]*', data_str)
print("URLs found in data:", list(set(urls)))
