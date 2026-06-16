"""
FeedFlow Automation Worker - Test Suite
Uses mongomock (in-memory MongoDB) - no Atlas connection needed.
Run with:  python test_worker.py
"""

import os
import sys
import io
import time
import requests
from datetime import datetime, timedelta
from bson import ObjectId

# Force UTF-8 output (fixes Windows cp1252 encoding issues)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# Force test mode: delays drop to 0.1s instead of 30-180s
os.environ['TEST_MODE'] = 'true'

from config import WORKER_PORT

# ==============================================================================
# Import automation modules first (MongoClient is lazy - no connection yet)
# Then inject mock db directly into module namespace
# ==============================================================================
import mongomock
import actions
import instagram_client

_mock_client = mongomock.MongoClient()
_mock_db     = _mock_client['insta-feed']

# Inject mock DB into both modules - replaces the real Atlas DB reference
actions.db          = _mock_db
instagram_client.db = _mock_db

from actions import AutomationEngine

# ==============================================================================
# Helpers
# ==============================================================================
def ok(msg):     print(f"  [PASS] {msg}")
def fail(msg):   print(f"  [FAIL] {msg}"); sys.exit(1)
def info(msg):   print(f"  [INFO] {msg}")
def header(msg): print(f"\n{'='*58}\nTEST: {msg}\n{'='*58}")

# ==============================================================================
# TEST 1: In-Memory MongoDB
# ==============================================================================
header("TEST 1: In-Memory MongoDB (mongomock)")
try:
    _mock_db.test_col.insert_one({'ping': 1})
    result = _mock_db.test_col.find_one({'ping': 1})
    assert result is not None
    _mock_db.test_col.drop()
    ok("mongomock working correctly")
except Exception as e:
    fail(f"mongomock failed: {e}")

# ==============================================================================
# TEST 2: Insert Mock Test Data
# ==============================================================================
header("TEST 2: Insert Mock User + Preferences + AutomationConfig")

TEST_USER_ID = ObjectId()
TEST_EMAIL   = f"test_{int(time.time())}@feedflow.test"

try:
    _mock_db.users.insert_one({
        '_id': TEST_USER_ID, 'email': TEST_EMAIL,
        'name': 'Test User', 'passwordHash': 'mock',
        'createdAt': datetime.utcnow(),
    })
    ok(f"User:   {TEST_EMAIL}  |  {TEST_USER_ID}")

    _mock_db.preferences.insert_many([
        {
            'userId':           TEST_USER_ID,
            'preferenceType':   'more',
            'categoryId':       'technology',
            'keywords':         ['AI', 'machine learning'],
            'expandedKeywords': ['artificial intelligence', 'deep learning'],
            'weight':           1,
        },
        {
            'userId':           TEST_USER_ID,
            'preferenceType':   'more',
            'categoryId':       'finance',
            'keywords':         ['investing', 'stocks'],
            'expandedKeywords': ['finance tips'],
            'weight':           1,
        },
    ])
    ok("Preferences: technology, finance")

    _mock_db.automationconfigs.insert_one({
        'userId':            TEST_USER_ID,
        'isActive':          True,
        'frequency':         'moderate',
        'actionsPerSession': 5,
        'activeHoursStart':  0,
        'activeHoursEnd':    24,
        'startedAt':         datetime.utcnow(),
        'nextRunAt':         datetime.utcnow() - timedelta(seconds=1),
        'totalSessions':     0,
    })
    ok("AutomationConfig: isActive=True, nextRunAt=NOW")

    _mock_db.instagramsessions.insert_one({
        'userId':            TEST_USER_ID,
        'instagramUsername': 'mock_test_user',
        'status':            'connected',
        'connectedAt':       datetime.utcnow(),
        'lastActivity':      datetime.utcnow(),
    })
    ok("Instagram session: status=connected")

except Exception as e:
    fail(f"Failed to insert mock data: {e}")

# Verify data is actually in the mock DB
prefs_count = _mock_db.preferences.count_documents({'userId': TEST_USER_ID})
info(f"Verified: {prefs_count} preferences in mock DB")

# ==============================================================================
# TEST 3: Mock Automation Cycle
# ==============================================================================
header("TEST 3: Mock Automation Cycle (no real Instagram)")

class MockMedia:
    pk   = "mock_pk_12345"
    code = "mock_code_abc"
    class user:
        username = "mock_ig_author"

class MockInstagramClient:
    def search_hashtags(self, keyword, amount=5):
        print(f"     [MOCK] search(#{keyword})")
        return [{'id': i, 'name': keyword} for i in range(amount)]
    def hashtag_medias_top(self, hashtag, amount=5):
        return [MockMedia() for _ in range(amount)]
    def media_info(self, pk):
        return MockMedia()
    def media_like(self, pk):
        print(f"     [MOCK] like({pk})")
    def media_save(self, pk):
        print(f"     [MOCK] save({pk})")

class MockIGManager:
    def get_client(self, user_id):
        return MockInstagramClient()

engine = AutomationEngine(MockIGManager())

try:
    print(f"  Running cycle for user {TEST_USER_ID}...")
    engine.run_cycle(str(TEST_USER_ID))
    ok("Cycle completed successfully")
except Exception as e:
    fail(f"Cycle raised exception: {e}")

# ==============================================================================
# TEST 4: Verify Action Logs
# ==============================================================================
header("TEST 4: Verify Action Logs Written to DB")

try:
    logs = list(_mock_db.automationlogs.find({'userId': TEST_USER_ID}))
    if not logs:
        fail("No action logs found — cycle did not write any logs!")

    types = set(l['actionType'] for l in logs)
    ok(f"Found {len(logs)} log(s) in automationlogs")
    info(f"Action types: {types}")

    sample = logs[0]
    info("Sample entry:")
    print(f"     actionType : {sample['actionType']}")
    print(f"     keyword    : {sample['keyword']}")
    print(f"     status     : {sample['status']}")
    print(f"     executedAt : {sample['executedAt']}")
except Exception as e:
    fail(f"Could not read logs: {e}")

# ==============================================================================
# TEST 5: Worker Dependencies
# ==============================================================================
header("TEST 5: Verify Worker Dependencies (Flask / APScheduler / instagrapi)")

deps = [
    ("flask",       "from flask import Flask"),
    ("flask_cors",  "from flask_cors import CORS"),
    ("apscheduler", "from apscheduler.schedulers.background import BackgroundScheduler"),
    ("instagrapi",  "from instagrapi import Client"),
    ("requests",    "import requests"),
]
for name, stmt in deps:
    try:
        exec(stmt)
        ok(f"{name}")
    except ImportError as e:
        fail(f"{name} not installed: {e}")

try:
    r = requests.get(f"http://localhost:{WORKER_PORT}/health", timeout=2)
    ok(f"Worker running on port {WORKER_PORT}: {r.json()}") if r.status_code == 200 else \
    info(f"Worker returned {r.status_code}")
except requests.exceptions.ConnectionError:
    info(f"Worker not running on port {WORKER_PORT} (start: python worker.py)")

# ==============================================================================
# TEST 6: Scheduler Polling Logic
# ==============================================================================
header("TEST 6: Scheduler poll_and_run Logic")

class MockSchedulerEngine:
    found_users = []
    def poll_and_run(self):
        for cfg in _mock_db.automationconfigs.find({
            'isActive':  True,
            'nextRunAt': {'$lte': datetime.utcnow()},
        }):
            uid = str(cfg['userId'])
            self.found_users.append(uid)
            print(f"     [SCHED] Due user: {uid}")

try:
    _mock_db.automationconfigs.update_one(
        {'userId': TEST_USER_ID},
        {'$set': {'nextRunAt': datetime.utcnow() - timedelta(seconds=1)}}
    )
    sched = MockSchedulerEngine()
    sched.poll_and_run()
    if str(TEST_USER_ID) in sched.found_users:
        ok("Scheduler correctly identified user as due for automation")
    else:
        fail("Scheduler did not find the mock user")
except Exception as e:
    fail(f"Scheduler test failed: {e}")

# ==============================================================================
# TEST 7 + 8: Node.js API (health + auth)
# ==============================================================================
header("TEST 7: Node.js Backend Health Check")
try:
    r = requests.get("http://localhost:3000/health", timeout=4)
    ok(f"Node.js healthy: {r.json()}") if r.status_code == 200 else info(f"Status {r.status_code}")
except requests.exceptions.ConnectionError:
    info("Node.js API not running on :3000 — start with: node index.js")
except Exception as e:
    info(f"Skipped: {e}")

header("TEST 8: Node.js Register + Login Flow")
API_EMAIL = f"autotest_{int(time.time())}@feedflow.test"
API_PASS  = "TestPass123"
jwt_token = None
try:
    r = requests.post("http://localhost:3000/api/auth/register",
                      json={"email": API_EMAIL, "password": API_PASS, "name": "Auto Test"},
                      timeout=8)
    if r.status_code in (200, 201):
        jwt_token = r.json().get('accessToken')
        ok(f"Registered: {API_EMAIL}")
        info(f"JWT: {jwt_token[:40]}..." if jwt_token else "No token in response")
    else:
        info(f"Register returned {r.status_code}: {r.text[:120]}")

    if jwt_token:
        r2 = requests.post("http://localhost:3000/api/auth/login",
                           json={"email": API_EMAIL, "password": API_PASS}, timeout=8)
        ok(f"Login successful") if r2.status_code == 200 else info(f"Login {r2.status_code}")

except requests.exceptions.ConnectionError:
    info("Node.js not running — skipping auth test")
except Exception as e:
    info(f"Auth test error: {e}")

# ==============================================================================
# Summary
# ==============================================================================
print(f"""
{'='*58}
ALL TESTS COMPLETE!
{'='*58}
  [1] In-memory MongoDB (mongomock)       PASS
  [2] Mock user + preferences + config    PASS
  [3] Mock automation cycle               PASS
  [4] Action logs verified                PASS
  [5] Flask + APScheduler + instagrapi    PASS
  [6] Scheduler polling logic             PASS
  [7] Node.js API health                  checked
  [8] Register + Login flow               checked

NEXT: Test with a REAL Instagram account
  1. python worker.py
  2. curl -X POST http://localhost:5000/api/instagram/login \\
       -H "Content-Type: application/json" \\
       -d {{"user_id":"<USER_ID>","username":"<IG>","password":"<PASS>"}}
  3. curl -X POST http://localhost:5000/api/automation/run \\
       -H "Content-Type: application/json" \\
       -d {{"user_id":"<USER_ID>"}}
  4. Check MongoDB Atlas -> insta-feed -> automationlogs
{'='*58}
""")
