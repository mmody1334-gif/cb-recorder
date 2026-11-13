
import json
import sys
from yt_dlp import YoutubeDL
from yt_dlp.extractor.stripchat import StripchatIE

ydl = YoutubeDL({'quiet': False})
ie = StripchatIE(ydl)
url = 'https://stripchat.com/TUNDEROSE1'

print('=== Downloading and Parsing with StripchatIE ===')
try:
    webpage = ie._download_webpage(url, 'TUNDEROSE1', headers=ie.geo_verification_headers())
    from yt_dlp.extractor.stripchat import lowercase_escape
    from yt_dlp.utils import traverse_obj
    data = ie._search_json(
        r'<script\b[^>]*>\s*window\.__PRELOADED_STATE__\s*=',
        webpage, 'data', 'TUNDEROSE1', transform_source=lowercase_escape)
    
    print('MODEL ID:', traverse_obj(data, ('viewCam', 'model', 'id')))
    print('IS LIVE:', traverse_obj(data, ('viewCam', 'model', 'isLive')))
    print('MODEL STATUS:', traverse_obj(data, ('viewCam', 'model', 'status')))
    print('BROADCAST GENDER:', traverse_obj(data, ('viewCam', 'model', 'broadcastGender')))
    print('SHOW OBJECT:', json.dumps(traverse_obj(data, ('viewCam', 'show', {dict})), indent=2))
    
    # Check HLS hosts
    model_id = traverse_obj(data, ('viewCam', 'model', 'id'))
    for host in traverse_obj(data, ((('config', 'data'), ('configV3', 'static')), (
            (('features', 'featuresV2'), 'hlsFallback', 'fallbackDomains', ...), 'hlsStreamHost'))):
        print('FOUND HLS HOST:', host)
        hls_url = f'https://edge-hls.{host}/hls/{model_id}/master/{model_id}_auto.m3u8'
        print('CANDIDATE HLS URL:', hls_url)
        # Test if HLS URL responds
        try:
            import urllib.request
            req = urllib.request.Request(hls_url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=5) as resp:
                print('HLS STATUS:', resp.status, 'LENGTH:', len(resp.read()))
        except Exception as e:
            print('HLS TEST FAILED:', e)
except Exception as e:
    print('PARSE ERROR:', e)
