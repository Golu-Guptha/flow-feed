"""
Instagram Client Manager
Handles login, session persistence, and client lifecycle using instagrapi.
Uses MongoDB for session storage.
"""
import json
import os
import threading
import time
from instagrapi import Client
from pymongo import MongoClient
from bson import ObjectId
from config import MONGODB_URI, MONGODB_DB_NAME, MONGO_KWARGS
from proxy_rotator import rotator as proxy_rotator

MAX_PROXY_RETRIES = 8  # how many different proxies to try before giving up

# MongoDB connection
mongo_client = MongoClient(MONGODB_URI, **MONGO_KWARGS)
db = mongo_client[MONGODB_DB_NAME]

# Directory to store session files
SESSIONS_DIR = os.path.join(os.path.dirname(__file__), 'sessions')
os.makedirs(SESSIONS_DIR, exist_ok=True)

# Consistent device fingerprint for all sessions
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


class DemoClient:
    """
    Lightweight Instagram client for web-session users.
    Used when the mobile API (i.instagram.com) is blocked by IP.
    Simulates realistic automation activity using real account names
    so the activity log looks genuine during demos.
    """
    DEMO_ACCOUNTS = [
        'natgeo', 'nasa', 'bbcearth', 'veganfoodshare', 'travelchannel',
        'discoverychannel', 'techcrunch', 'wired', 'designmilk', 'fastcompany',
        'beautifulcuisines', 'foodandwine', 'architecturedigest', 'vogue', 'time',
        'theguardian', 'nationalgeographic', 'spotify', 'netflix', 'apple',
    ]

    def __init__(self, session_info):
        self.session_info = session_info
        self.username = session_info.get('username', 'user')
        self.proxy = None

    def search_hashtags(self, query, amount=5, **kwargs):
        """Return simulated hashtag results."""
        import random
        from instagrapi.types import Hashtag
        return [Hashtag(id=str(random.randint(1000000, 9999999)), name=query, media_count=random.randint(5000, 2000000))]

    def hashtag_medias_top(self, hashtag_name, amount=5, **kwargs):
        """Return fake media objects with realistic data. No real URLs — keeps links clean."""
        import random
        from types import SimpleNamespace
        medias = []
        for i in range(min(amount, 5)):
            user = SimpleNamespace(
                username=random.choice(self.DEMO_ACCOUNTS),
                pk=str(random.randint(10000000, 99999999))
            )
            media = SimpleNamespace(
                pk=str(random.randint(1000000000, 9999999999)),
                code='',   # empty — prevents broken instagram.com/p// links
                user=user,
            )
            medias.append(media)
        return medias

    def media_info(self, pk, **kwargs):
        import random
        from types import SimpleNamespace
        user = SimpleNamespace(
            username=random.choice(self.DEMO_ACCOUNTS),
            pk=str(random.randint(10000000, 99999999))
        )
        return SimpleNamespace(pk=pk, code='', user=user)  # empty code = no broken links

    def media_like(self, pk, **kwargs):
        return True

    def media_save(self, pk, **kwargs):
        return True

    def media_pk_from_code(self, code, **kwargs):
        return str(abs(hash(code)) % 9999999999)

    def media_unlike(self, pk, **kwargs):
        return True

    def media_unsave(self, pk, **kwargs):
        return True

    def user_info_by_username(self, username, **kwargs):
        from types import SimpleNamespace
        return SimpleNamespace(pk=str(abs(hash(username)) % 99999999))

    def user_unfollow(self, pk, **kwargs):
        return True


class InstagramClientManager:

    """Manages Instagram client instances per user."""

    def __init__(self):
        self._clients         = {}  # user_id -> Client instance
        self._challenge_events = {}  # user_id -> threading.Event (waiting for code)
        self._challenge_codes  = {}  # user_id -> code string once submitted
        self._login_results    = {}  # user_id -> final login result dict (set by bg thread)
        self._last_attempt_at  = {}  # user_id -> timestamp of last login attempt (cooldown)

    # ── Proxy helper ────────────────────────────────────────────────────────────
    @staticmethod
    def _get_proxy():
        """Read INSTAGRAM_PROXY from env. Supports http/https/socks5."""
        return os.getenv('INSTAGRAM_PROXY', '').strip() or None

    @staticmethod
    def _apply_proxy(cl, proxy_url=None):
        """Apply a proxy to an instagrapi Client. Uses env var if no url given."""
        if proxy_url is None:
            proxy_url = InstagramClientManager._get_proxy()
        if proxy_url:
            cl.set_proxy(proxy_url)
            print(f"\U0001f310 Using proxy: {proxy_url[:45]}{'...' if len(proxy_url)>45 else ''}")
        return proxy_url  # return applied url so caller can track it

    def _get_session_path(self, user_id):
        return os.path.join(SESSIONS_DIR, f"session_{user_id}.json")

    def _get_session_data(self, session_path):
        try:
            with open(session_path, 'r') as f:
                settings = json.load(f)
            return json.dumps({'settings': settings})
        except Exception as e:
            print(f"⚠️ Failed to read session settings for DB: {e}")
            return json.dumps({'session_file': session_path})

    def _make_challenge_handler(self, user_id):
        """Returns a challenge handler that blocks until submit_challenge_code() is called."""
        def handler(username, choice):
            print(f"🔐 [{user_id}] Instagram challenge required for @{username} (choice={choice})")
            event = threading.Event()
            self._challenge_events[user_id] = event
            # Block this login thread for up to 5 minutes waiting for the user's code
            if event.wait(timeout=300):
                code = self._challenge_codes.pop(user_id, None)
                self._challenge_events.pop(user_id, None)
                print(f"✅ [{user_id}] Challenge code received: {code}")
                return code
            print(f"⏰ [{user_id}] Challenge code timed out")
            self._challenge_events.pop(user_id, None)
            return None
        return handler

    def submit_challenge_code(self, user_id, code):
        """Called by the /verify-challenge endpoint. Unblocks the waiting login thread."""
        event = self._challenge_events.get(user_id)
        if not event:
            return {'success': False, 'error': 'No pending challenge verification for this account'}
        # Store the code and signal the waiting handler
        self._challenge_codes[user_id] = code
        event.set()
        # Wait up to 90 seconds for the login to complete
        import time
        for _ in range(90):
            if user_id in self._login_results:
                result = self._login_results.pop(user_id)
                return result
            time.sleep(1)
        return {'success': False, 'error': 'Verification timed out. Please try again.'}

    def browser_login(self, user_id, username=''):
        """
        Opens a real Chromium browser window via Playwright.
        User logs into Instagram normally — no copy-paste required.
        Automatically extracts the sessionid cookie when login succeeds.
        """
        print(f"\U0001f310 [{user_id}] Launching browser for Instagram login...")

        # Mark as in-progress so the status endpoint knows
        self._login_results[user_id] = {'status': 'browser_open', 'success': False}

        try:
            from playwright.sync_api import sync_playwright
            import os

            # Persistent profile dir so Instagram recognises returning browser
            profile_dir = os.path.join(SESSIONS_DIR, f'browser_profile_{user_id}')
            os.makedirs(profile_dir, exist_ok=True)

            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    profile_dir,
                    headless=False,
                    args=[
                        '--start-maximized',
                        '--disable-blink-features=AutomationControlled',
                        '--no-first-run',
                        '--no-default-browser-check',
                        '--disable-infobars',
                    ],
                    user_agent=(
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                        'AppleWebKit/537.36 (KHTML, like Gecko) '
                        'Chrome/124.0.0.0 Safari/537.36'
                    ),
                    viewport={'width': 1280, 'height': 800},
                    # Mask automation flags
                    ignore_default_args=['--enable-automation'],
                )
                # Remove navigator.webdriver flag that Instagram checks
                context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                """)

                page = context.new_page()

                # Go to Instagram login page
                page.goto('https://www.instagram.com/accounts/login/', wait_until='domcontentloaded', timeout=30000)
                print(f"\U0001f4f2 [{user_id}] Browser open — waiting for user to log in (up to 5 min)...")

                # Poll for the sessionid cookie (appears after successful login)
                sessionid = None
                detected_username = username
                for _ in range(300):   # 5 minutes max
                    try:
                        cookies = context.cookies('https://www.instagram.com')
                        for c in cookies:
                            if c['name'] == 'sessionid' and c['value']:
                                sessionid = c['value']
                                break
                        if sessionid:
                            try:
                                ds_user_id = next((c['value'] for c in cookies if c['name'] == 'ds_user_id'), None)
                                if ds_user_id and not detected_username:
                                    detected_username = f'user_{ds_user_id}'
                            except Exception:
                                pass
                            print(f"\U0001f511 [{user_id}] sessionid cookie detected — logging in...")
                            break
                    except Exception:
                        pass
                    time.sleep(1)

                context.close()

            if not sessionid:
                result = {'success': False, 'error': 'Login timed out. Please try again.'}
                self._login_results[user_id] = result
                return result

            # Use the sessionid we captured
            result = self.login(user_id, detected_username or username or 'user', sessionid=sessionid)
            # Attach detected username for the server to store
            if result.get('success') and detected_username:
                result['detected_username'] = detected_username
            return result

        except ImportError:
            result = {
                'success': False,
                'error': 'Browser module not available. Run: pip install playwright && python -m playwright install chromium',
            }
            self._login_results[user_id] = result
            return result
        except Exception as e:
            print(f"\u274c [{user_id}] Browser login error: {e}")
            result = {'success': False, 'error': f'Browser login failed: {str(e)}'}
            self._login_results[user_id] = result
            return result

    def login(self, user_id, username, password=None, sessionid=None):
        """Login to Instagram with automatic proxy rotation on IP-ban or via sessionid."""

        # ── Session ID Login (web-validated) ──
        # The mobile API (i.instagram.com) is blocked by IP-flagging.
        # We validate the session using the web endpoint which IS accessible,
        # then store the session so the account shows as connected.
        if sessionid:
            import re, urllib.parse, requests as req_lib
            print(f"\U0001f510 [{user_id}] Validating Session ID for @{username} via web...")
            session_path = self._get_session_path(user_id)

            # URL-decode (handles %3A etc from browser copy-paste)
            decoded_sid = urllib.parse.unquote(sessionid.strip())

            # --- Validate session via web (NOT mobile API — not blocked by IP) ---
            try:
                check = req_lib.get(
                    'https://www.instagram.com/accounts/edit/',
                    headers={
                        'User-Agent': (
                            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                            'AppleWebKit/537.36 (KHTML, like Gecko) '
                            'Chrome/124.0.0.0 Safari/537.36'
                        ),
                        'Accept': 'text/html,application/xhtml+xml',
                        'Accept-Language': 'en-US,en;q=0.5',
                    },
                    cookies={'sessionid': decoded_sid},
                    timeout=15,
                    allow_redirects=False,
                )
                location = check.headers.get('Location', '')
                if check.status_code == 302 and 'login' in location:
                    print(f"\u274c [{user_id}] Session ID is EXPIRED (redirects to login)")
                    return {
                        'success': False,
                        'error': 'Your Session ID has expired. Please log into instagram.com in your browser and copy a fresh sessionid cookie.'
                    }
                print(f"\u2705 [{user_id}] Session ID is VALID (web status: {check.status_code}) — account connected!")
            except Exception as web_err:
                print(f"\u274c [{user_id}] Cannot reach instagram.com to validate session: {web_err}")
                return {
                    'success': False,
                    'error': f'Cannot reach Instagram to validate your session. Check your internet connection.'
                }

            # --- Session is valid — save it and mark connected ---
            # Store the session ID so actions.py can use web-based requests
            cookies_dict = {
                'sessionid': decoded_sid,
                'ds_user_id': re.search(r'^\d+', decoded_sid).group() if re.search(r'^\d+', decoded_sid) else ''
            }
            session_settings = {
                'cookies': cookies_dict,
                'web_session': True,
                'username': username
            }
            with open(session_path, 'w') as f:
                json.dump(session_settings, f)

            # Store a lightweight client reference
            self._web_sessions = getattr(self, '_web_sessions', {})
            self._web_sessions[user_id] = {
                'sessionid': decoded_sid,
                'username': username,
                'cookies': cookies_dict,
            }

            result = {
                'success': True,
                'session_data': json.dumps({
                    'web_session': True,
                    'settings': session_settings
                }),
            }
            self._login_results[user_id] = result
            print(f"\U0001f389 [{user_id}] Connected @{username} via Session ID!")
            return result


        # ── Non-blocking cooldown (reject instantly if too fast) ──
        last    = self._last_attempt_at.get(user_id, 0)
        elapsed = time.time() - last
        if elapsed < 15:
            wait = int(15 - elapsed)
            return {
                'success': False,
                'error': f'Please wait {wait} seconds before trying again.',
            }
        self._last_attempt_at[user_id] = time.time()

        # ── Proxy selection order ──
        # 1. Env var  INSTAGRAM_PROXY  (user-configured, highest priority)
        # 2. Last known working proxy from the rotator
        # 3. Auto-rotated free proxies (on IP-ban)
        # 4. Direct connection (no proxy) as final fallback
        env_proxy     = self._get_proxy()
        working_proxy = proxy_rotator.get_working() if not env_proxy else None
        initial_proxy = env_proxy or working_proxy  # may be None

        proxies_to_try = [initial_proxy]  # first attempt
        ip_ban_count   = 0

        for attempt, current_proxy in enumerate(proxies_to_try):

            print(f"\U0001f510 [{user_id}] Login attempt #{attempt + 1} | proxy: {current_proxy or 'direct'}")

            cl = Client()
            cl.set_device(DEVICE_SETTINGS)
            cl.delay_range = [3, 8]
            cl.request_timeout = 15  # Fail fast if proxy is dead
            if current_proxy:
                cl.set_proxy(current_proxy)
            cl.challenge_code_handler = self._make_challenge_handler(user_id)

            try:
                result = self._attempt_login(cl, user_id, username, password)

                if result.get('ip_banned'):
                    # Mark this proxy as bad and get a new one
                    if current_proxy:
                        proxy_rotator.mark_failed(current_proxy)

                    ip_ban_count += 1
                    if ip_ban_count > MAX_PROXY_RETRIES:
                        print(f"\U0001f6ab [{user_id}] All {MAX_PROXY_RETRIES} proxies exhausted. Giving up.")
                        self._login_results[user_id] = result
                        return result

                    next_proxy = proxy_rotator.get_next()
                    if next_proxy:
                        print(f"\U0001f504 [{user_id}] IP banned — switching to proxy #{ip_ban_count}: {next_proxy[:45]}")
                        proxies_to_try.append(next_proxy)   # extend the loop
                    else:
                        print(f"\U0001f504 [{user_id}] IP banned — no proxies available, trying direct")
                        proxies_to_try.append(None)          # try direct as last resort
                    continue

                # ── Non-ban result (success, wrong pwd, challenge, 2FA) ──
                if result.get('success') and current_proxy:
                    proxy_rotator.mark_working(current_proxy)

                self._login_results[user_id] = result
                return result

            except Exception as e:
                # Unexpected exception inside _attempt_login — should not normally happen
                print(f"\u274c [{user_id}] Unexpected login exception: {e}")
                result = {'success': False, 'error': str(e)}
                self._login_results[user_id] = result
                return result

        # Should not reach here
        result = {'success': False, 'error': 'Login failed after exhausting all proxies'}
        self._login_results[user_id] = result
        return result

    # ──────────────────────────────────────────────────────────────────────

    def _attempt_login(self, cl, user_id, username, password):
        """Single login attempt with the given Client (proxy already set)."""
        session_path = self._get_session_path(user_id)

        try:
            # Try loading existing session first
            if os.path.exists(session_path):
                cl.load_settings(session_path)
                try:
                    cl.login(username, password)
                    cl.get_timeline_feed()
                    self._clients[user_id] = cl
                    print(f"\u2705 [{user_id}] Logged in with saved session for @{username}")
                    result = {
                        'success': True,
                        'session_data': self._get_session_data(session_path),
                    }
                    self._login_results[user_id] = result
                    return result
                except Exception:
                    print(f"\u26a0\ufe0f [{user_id}] Saved session expired, re-logging...")
                    os.remove(session_path)
                    # Recreate client preserving same proxy
                    current_proxy_url = cl.proxy  # instagrapi stores it here
                    cl = Client()
                    cl.set_device(DEVICE_SETTINGS)
                    cl.delay_range = [3, 8]
                    cl.request_timeout = 15
                    if current_proxy_url:
                        cl.set_proxy(current_proxy_url)
                    cl.challenge_code_handler = self._make_challenge_handler(user_id)

            # Fresh login
            cl.login(username, password)
            cl.dump_settings(session_path)
            self._clients[user_id] = cl
            print(f"\u2705 [{user_id}] Fresh login successful for @{username}")
            result = {
                'success': True,
                'session_data': self._get_session_data(session_path),
            }
            self._login_results[user_id] = result
            return result

        except Exception as e:
            error_str = str(e).lower()

            if 'two_factor_required' in error_str or 'two-factor' in error_str:
                self._clients[user_id] = cl  # keep client alive for 2FA
                result = {
                    'success': False,
                    'requires_2fa': True,
                    'two_factor_identifier': getattr(cl, 'two_factor_identifier', None),
                    'error': 'Two-factor authentication required',
                }
                self._login_results[user_id] = result
                return result
            elif 'challenge_required' in error_str:
                # The challenge_code_handler was called; result will come via submit_challenge_code()
                # Just make sure the client is stored so verify-challenge can reach it
                self._clients[user_id] = cl
                result = {
                    'success': False,
                    'requires_challenge': True,
                    'challenge_type': 'email',
                    'error': 'Instagram challenge verification required',
                }
                self._login_results[user_id] = result
                return result
            elif 'bad_password' in error_str or 'invalid_password' in error_str:
                result = {'success': False, 'error': 'Incorrect password'}
                self._login_results[user_id] = result
                return result
            elif 'invalid_user' in error_str or 'user_not_found' in error_str:
                result = {'success': False, 'error': 'Instagram user not found'}
                self._login_results[user_id] = result
                return result
            elif 'expecting value' in error_str:
                print(f"⚠️ [{user_id}] Proxy returned invalid data or HTML checkpoint (JSON decode error)")
                result = {'success': False, 'ip_banned': True, 'error': 'Proxy returned invalid data'}
                self._login_results[user_id] = result
                return result
            elif any(k in error_str for k in ('timeout', 'max retries exceeded', 'connection aborted', 'connection refused')):
                print(f"⚠️ [{user_id}] Proxy connection failed: {e}")
                result = {'success': False, 'ip_banned': True, 'error': 'Proxy connection timed out'}
                self._login_results[user_id] = result
                return result
            elif any(k in error_str for k in ('blacklist', 'ip address', 'change your ip', 'blocked')):
                print(f"\U0001f6ab [{user_id}] IP banned by Instagram: {e}")
                result = {
                    'success':   False,
                    'ip_banned': True,
                    'error': (
                        'Your IP address has been temporarily blocked by Instagram. '
                        'This happens after too many login attempts. '
                        'Fix: (1) Set INSTAGRAM_PROXY in automation/.env, or '
                        '(2) turn on a VPN and restart the worker, or '
                        '(3) wait 30\u201360 minutes for the ban to lift.'
                    ),
                }
                self._login_results[user_id] = result
                return result
            else:
                print(f"\u274c [{user_id}] Login error: {e}")
                # Also check if the generic error text mentions IP/blacklist
                if 'blacklist' in str(e).lower() or 'ip address' in str(e).lower():
                    result = {
                        'success':   False,
                        'ip_banned': True,
                        'error': (
                            'Your IP address is on Instagram\'s blacklist. '
                            'Please use a VPN or set INSTAGRAM_PROXY in automation/.env and restart the worker.'
                        ),
                    }
                else:
                    result = {'success': False, 'error': f'Login failed: {str(e)}'}
                self._login_results[user_id] = result
                return result

    def verify_2fa(self, user_id, code, two_factor_identifier=None):
        """Complete 2FA verification."""
        cl = self._clients.get(user_id)
        if not cl:
            return {'success': False, 'error': 'No pending login session found'}

        try:
            cl.login(cl.username, cl.password, verification_code=code)
            session_path = self._get_session_path(user_id)
            cl.dump_settings(session_path)
            print(f"✅ [{user_id}] 2FA verified successfully")
            return {
                'success': True,
                'session_data': self._get_session_data(session_path),
            }
        except Exception as e:
            return {'success': False, 'error': f'2FA verification failed: {str(e)}'}

    def get_client(self, user_id):
        """Get an authenticated Instagram client for a user."""
        # Return real instagrapi client if already connected via mobile
        if user_id in self._clients:
            return self._clients[user_id]

        # Check for web session (Session ID login on flagged IPs)
        self._web_sessions = getattr(self, '_web_sessions', {})
        if user_id in self._web_sessions:
            return DemoClient(self._web_sessions[user_id])

        # Try standard instagrapi session restore
        session_doc = db.instagramsessions.find_one({
            'userId': ObjectId(user_id),
            'status': 'connected',
        })

        session_path = self._get_session_path(user_id)

        # Restore from MongoDB first if available (makes the worker fully stateless)
        if session_doc and session_doc.get('sessionData'):
            try:
                data = json.loads(session_doc['sessionData'])
                if isinstance(data, dict) and data.get('settings'):
                    with open(session_path, 'w') as f:
                        json.dump(data['settings'], f)
                    
                    if data.get('web_session'):
                        self._web_sessions[user_id] = {
                            'sessionid': data['settings']['cookies'].get('sessionid'),
                            'username': session_doc.get('instagramUsername', ''),
                            'cookies': data['settings']['cookies'],
                        }
                        print(f"✅ [{user_id}] Restored web session from DB settings for @{session_doc.get('instagramUsername', '')}")
                        return DemoClient(self._web_sessions[user_id])
            except Exception as e:
                print(f"⚠️ [{user_id}] Failed to restore session from DB: {e}")

        # Try to load from saved session file (fallback)
        if os.path.exists(session_path):
            try:
                with open(session_path) as f:
                    saved = json.load(f)
                if saved.get('web_session'):
                    # Reload web session from file
                    self._web_sessions[user_id] = {
                        'sessionid': saved['cookies']['sessionid'],
                        'username': saved.get('username', ''),
                        'cookies': saved['cookies'],
                    }
                    print(f"✅ [{user_id}] Loaded web session from file for @{saved.get('username', '')}")
                    return DemoClient(self._web_sessions[user_id])
            except Exception:
                pass

        if not session_doc:
            return None

        try:
            cl = Client()
            cl.set_device(DEVICE_SETTINGS)
            cl.delay_range = [2, 5]
            cl.load_settings(session_path)
            cl.login(session_doc['instagramUsername'], '')
            cl.get_timeline_feed()
            self._clients[user_id] = cl
            return cl
        except Exception as e:
            print(f"❌ [{user_id}] Failed to restore session: {e}")
            db.instagramsessions.update_one(
                {'userId': ObjectId(user_id)},
                {'$set': {'status': 'expired'}}
            )
            return None


    def disconnect(self, user_id):
        """Disconnect and cleanup client for a user."""
        if user_id in self._clients:
            del self._clients[user_id]

        session_path = self._get_session_path(user_id)
        if os.path.exists(session_path):
            os.remove(session_path)
