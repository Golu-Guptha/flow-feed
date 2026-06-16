import re, urllib.parse, json, sys
sys.path.insert(0, '.')
from instagrapi import Client

DEVICE_SETTINGS = {
    "app_version": "269.0.0.18.75",
    "android_version": 31,
    "android_release": "12.0",
    "dpi": "480dpi",
    "resolution": "1080x2400",
    "manufacturer": "Samsung",
    "device": "SM-G991B",
    "model": "samsung",
    "cpu": "exynos2100",
    "version_code": "314665256",
}

sessionid = '15411850302%3ADAH6QBOk48Boz9%3A23%3AAYgM5JK_jJOtDJt86-sBNhOct_fWZmzTetRPiD5CYA'
decoded_sid = urllib.parse.unquote(sessionid.strip())
username = 'kukun2520@gmail.com'

insta_uid_match = re.search(r'^\d+', decoded_sid)
insta_uid = insta_uid_match.group() if insta_uid_match else '0'
print(f"Instagram UID: {insta_uid}")

cl = Client()
cl.set_device(DEVICE_SETTINGS)
cl.delay_range = [2, 5]
cl.request_timeout = 20

print("Injecting cookies...")
cl.set_settings({
    'cookies': {
        'sessionid': decoded_sid,
        'ds_user_id': insta_uid,
    },
    'authorization_data': {
        'ds_user_id': insta_uid,
        'sessionid': decoded_sid,
    },
    'uuids': {
        'phone_id': cl.generate_uuid(),
        'uuid': cl.generate_uuid(),
        'client_session_id': cl.generate_uuid(),
        'advertising_id': cl.generate_uuid(),
        'android_device_id': f'android-{cl.generate_uuid()[:16]}',
    },
    'device_settings': DEVICE_SETTINGS,
    'user_agent': cl.user_agent,
})
cl.username = username

print("Testing hashtag search...")
try:
    results = cl.search_hashtags('photography')
    print(f"SUCCESS! Found {len(results)} hashtags")
    print("Login via cookie injection WORKS!")
except Exception as e:
    print(f"FAILED: {e}")
    import traceback
    traceback.print_exc()
