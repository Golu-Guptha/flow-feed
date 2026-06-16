import os
import re
from dotenv import load_dotenv

load_dotenv()

# MongoDB
MONGODB_URI = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/feedflow')

# Extract DB name from URI (e.g. .../insta-feed?... → 'insta-feed')
_uri_db = re.search(r'/([^/?]+)(\?|$)', MONGODB_URI)
MONGODB_DB_NAME = os.getenv('MONGODB_DB_NAME', _uri_db.group(1) if _uri_db else 'insta-feed')

# pymongo connection kwargs — certifi CA bundle fixes Atlas TLS on Windows
try:
    import certifi
    _tls_ca = certifi.where()
except ImportError:
    _tls_ca = None

MONGO_KWARGS = {
    'serverSelectionTimeoutMS': 20000,
    'connectTimeoutMS':         20000,
    'socketTimeoutMS':          30000,
    # Keep connections alive — prevents Atlas from closing idle connections
    'heartbeatFrequencyMS':     10000,   # ping every 10s
    'minPoolSize':              1,        # keep at least 1 connection open
    'maxIdleTimeMS':            45000,    # close idle connections after 45s (before Atlas's 60s limit)
    'retryWrites':              True,
    'retryReads':               True,
}
if _tls_ca:
    MONGO_KWARGS['tlsCAFile'] = _tls_ca

# Worker API
WORKER_PORT = int(os.getenv('WORKER_PORT', '5000'))

# Test mode — shortens delays for local testing
TEST_MODE = os.getenv('TEST_MODE', 'false').lower() == 'true'

# Automation defaults
DEFAULT_ACTIONS_PER_SESSION = 10
MAX_ACTIONS_PER_DAY = 50
SESSION_COOLDOWN_MIN = 120  # Minutes between sessions
SESSION_COOLDOWN_MAX = 300

# Anti-detection settings (very short in TEST_MODE)
MIN_ACTION_DELAY = 1   if TEST_MODE else 30   # Seconds
MAX_ACTION_DELAY = 3   if TEST_MODE else 180
MIN_SESSION_DURATION = 5   if TEST_MODE else 600
MAX_SESSION_DURATION = 10  if TEST_MODE else 1800

# Daily limits per action type
DAILY_LIMITS = {
    'search': 30,
    'view': 50,
    'like': 40,
    'save': 20,
    'follow': 10,
}

# Session warmup schedule (days -> max actions per session)
WARMUP_SCHEDULE = {
    1: 5  if not TEST_MODE else 3,
    2: 8,
    3: 10,
    4: 12,
    5: 15,
    6: 18,
    7: 20,
}
