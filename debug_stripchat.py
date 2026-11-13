
import json
import re
import sys
import urllib.request
import requests

username = 'TUNDEROSE1'
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,application/json,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}

print('=== 1. Testing Stripchat Cam API ===')
try:
    api_url = f'https://stripchat.com/api/front/v2/models/username/{username}/cam'
    r = requests.get(api_url, headers=headers, timeout=10)
    print('API Status:', r.status_code)
    if r.status_code == 200:
        data = r.json()
        print('Cam keys:', list(data.get('cam', {}).keys()))
        print('isLive:', data.get('cam', {}).get('isLive'))
        print('show:', data.get('cam', {}).get('show'))
        print('streamName:', data.get('cam', {}).get('streamName'))
        print('viewServers:', data.get('cam', {}).get('viewServers'))
        print('servers:', list(data.get('servers', {}).keys()) if isinstance(data.get('servers'), dict) else data.get('servers'))
except Exception as e:
    print('API Error:', e)

print('=== 2. Testing Stripchat Webpage __PRELOADED_STATE__ ===')
try:
    page_url = f'https://stripchat.com/{username}'
    r2 = requests.get(page_url, headers=headers, timeout=10)
    print('Page Status:', r2.status_code)
    m = re.search(r'<script[^>]*>\s*window\.__PRELOADED_STATE__\s*=\s*({.*?});</script>', r2.text, re.DOTALL)
    if m:
        ps = json.loads(m.group(1))
        vc = ps.get('viewCam', {})
        print('viewCam keys:', list(vc.keys()))
        print('vc.model.isLive:', vc.get('model', {}).get('isLive'))
        print('vc.model.id:', vc.get('model', {}).get('id'))
        print('vc.model.status:', vc.get('model', {}).get('status'))
        print('vc.show:', vc.get('show'))
        cf = ps.get('configV3', {}).get('static', {}) or ps.get('config', {}).get('data', {})
        print('fallbackDomains:', cf.get('features', {}).get('hlsFallback', {}).get('fallbackDomains'))
except Exception as e:
    print('Page Error:', e)
