"""
proxy_rotator.py
Fetches free public proxies, pre-tests them, and rotates on failure.
"""
import random
import time
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# Multiple free proxy APIs
PROXY_SOURCES = [
    {
        'url': 'https://api.proxyscrape.com/v2/?request=displayproxies'
               '&protocol=http&timeout=3000&country=all&ssl=yes&anonymity=elite,anonymous',
        'format': 'plain',
        'prefix': 'http://',
    },
    {
        'url': 'https://api.proxyscrape.com/v2/?request=displayproxies'
               '&protocol=socks5&timeout=3000&country=all&ssl=all&anonymity=elite,anonymous',
        'format': 'plain',
        'prefix': 'socks5://',
    },
    {
        'url': 'https://api.proxyscrape.com/v2/?request=displayproxies'
               '&protocol=http&timeout=5000&country=US,GB,DE,NL,FR,CA,JP'
               '&ssl=all&anonymity=all',
        'format': 'plain',
        'prefix': 'http://',
    },
    {
        'url': 'https://proxylist.geonode.com/api/proxy-list'
               '?limit=50&page=1&sort_by=lastChecked&sort_type=desc'
               '&filterUpTime=90&protocols=http,https',
        'format': 'geonode',
        'prefix': 'http://',
    },
    {
        'url': 'https://proxylist.geonode.com/api/proxy-list'
               '?limit=50&page=1&sort_by=lastChecked&sort_type=desc'
               '&filterUpTime=90&protocols=socks5',
        'format': 'geonode',
        'prefix': 'socks5://',
    },
]

_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
_TEST_URL = 'https://httpbin.org/ip'


def _test_proxy(proxy_url, timeout=6):
    """Test if a proxy can reach the internet. Returns (proxy_url, True/False, latency_ms)."""
    try:
        start = time.time()
        r = requests.get(
            _TEST_URL,
            proxies={'http': proxy_url, 'https': proxy_url},
            timeout=timeout,
            headers={'User-Agent': _UA},
        )
        latency = int((time.time() - start) * 1000)
        return (proxy_url, r.status_code == 200, latency)
    except Exception:
        return (proxy_url, False, 99999)


class ProxyRotator:
    """Thread-safe rotating proxy pool with pre-validation."""

    def __init__(self, refresh_interval=300, max_pool=200, max_verified=20):
        self._raw_pool = []
        self._verified = []          # pre-tested working proxies
        self._failed = set()
        self._working = None         # last known good proxy
        self._lock = threading.Lock()
        self._last_refresh = 0.0
        self._refresh_interval = refresh_interval
        self._max_pool = max_pool
        self._max_verified = max_verified

    # ── Fetching ─────────────────────────────────────────────────────────

    def _fetch_raw(self):
        proxies = []
        for src in PROXY_SOURCES:
            try:
                r = requests.get(src['url'], timeout=12, headers={'User-Agent': _UA})
                if r.status_code != 200:
                    continue

                if src['format'] == 'plain':
                    for line in r.text.strip().split('\n'):
                        line = line.strip()
                        if ':' in line and len(line) < 50:
                            proxies.append(src['prefix'] + line)

                elif src['format'] == 'geonode':
                    data = r.json()
                    for item in data.get('data', []):
                        ip = item.get('ip', '')
                        port = item.get('port', '')
                        if ip and port:
                            proxies.append(f"{src['prefix']}{ip}:{port}")

            except Exception as e:
                print(f"[proxy] Fetch error from {src['url'][:50]}: {e}")

        random.shuffle(proxies)
        unique = list(dict.fromkeys(proxies))
        print(f"[proxy] Fetched {len(unique)} raw proxies from {len(PROXY_SOURCES)} sources")
        return unique[:self._max_pool]

    def _verify_batch(self, proxies, max_workers=30, timeout=6):
        """Test proxies in parallel, return the fastest working ones."""
        verified = []
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(_test_proxy, p, timeout): p for p in proxies}
            for future in as_completed(futures, timeout=20):
                try:
                    proxy_url, ok, latency = future.result()
                    if ok:
                        verified.append((proxy_url, latency))
                except Exception:
                    pass

        # Sort by latency (fastest first)
        verified.sort(key=lambda x: x[1])
        top = [p for p, _ in verified[:self._max_verified]]
        print(f"[proxy] Verified {len(verified)} working proxies (keeping top {len(top)})")
        if top:
            for p, lat in verified[:5]:
                print(f"  -> {p[:45]}  ({lat}ms)")
        return top

    def refresh(self, force=False):
        """Fetch and pre-test proxies. Thread-safe."""
        now = time.time()
        if not force and (now - self._last_refresh < self._refresh_interval) and self._verified:
            return
        with self._lock:
            # Double-check inside lock
            if not force and (now - self._last_refresh < self._refresh_interval) and self._verified:
                return
            print("[proxy] Refreshing proxy pool...")
            self._raw_pool = self._fetch_raw()
            self._verified = self._verify_batch(self._raw_pool)
            self._failed.clear()
            self._last_refresh = time.time()
            if not self._verified:
                print("[proxy] WARNING: No working proxies found!")

    # ── Public API ───────────────────────────────────────────────────────

    def get_next(self):
        """Return the next untried verified proxy, refreshing if needed."""
        self.refresh()
        with self._lock:
            for proxy in self._verified:
                if proxy not in self._failed:
                    return proxy
            # All verified proxies failed — force refresh
            self._failed.clear()
        self.refresh(force=True)
        with self._lock:
            return self._verified[0] if self._verified else None

    def mark_failed(self, proxy):
        with self._lock:
            self._failed.add(proxy)
            if self._working == proxy:
                self._working = None
        print(f"[proxy] Marked failed: {proxy[:45]}")

    def mark_working(self, proxy):
        with self._lock:
            self._working = proxy
        print(f"[proxy] Cached working: {proxy[:45]}")

    def get_working(self):
        return self._working

    def pool_size(self):
        return len(self._verified)


# Module singleton
rotator = ProxyRotator()
