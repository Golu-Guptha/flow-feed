"""
Automation Engine
Performs Instagram actions (search, view, like, save) with human-like behavior.
Uses MongoDB for data persistence.
"""
import time
import random
from datetime import datetime, timedelta
from pymongo import MongoClient
from pymongo.errors import AutoReconnect, ConnectionFailure, ServerSelectionTimeoutError
from bson import ObjectId
from config import (
    MONGODB_URI, MONGODB_DB_NAME, MONGO_KWARGS,
    MIN_ACTION_DELAY, MAX_ACTION_DELAY,
    DAILY_LIMITS, WARMUP_SCHEDULE, MAX_ACTIONS_PER_DAY,
)
from anti_detect import HumanBehavior

# MongoDB connection
def _make_mongo():
    return MongoClient(MONGODB_URI, **MONGO_KWARGS)

mongo_client = _make_mongo()
db = mongo_client[MONGODB_DB_NAME]


class AutomationEngine:
    """Core automation engine that runs engagement cycles."""

    def __init__(self, ig_manager):
        self.ig_manager = ig_manager
        self.human = HumanBehavior()

    def poll_and_run(self):
        """Check for active users who need automation runs. Reconnects MongoDB on network drops."""
        global mongo_client, db
        for attempt in range(3):
            try:
                now = datetime.utcnow()
                active_configs = list(db.automationconfigs.find({
                    'isActive': True,
                    'nextRunAt': {'$lte': now},
                }))

                for config in active_configs:
                    user_id = str(config['userId'])
                    current_hour = now.hour
                    start_hour = config.get('activeHoursStart', 8)
                    end_hour   = config.get('activeHoursEnd', 22)

                    if not (start_hour <= current_hour < end_hour):
                        continue

                    if random.random() < 0.1:
                        print(f"⏸️ [{user_id}] Random rest skip")
                        self._schedule_next_run(user_id, config.get('frequency', 'moderate'))
                        continue

                    print(f"🚀 [{user_id}] Starting automation cycle")
                    try:
                        self.run_cycle(user_id)
                    except Exception as e:
                        print(f"❌ [{user_id}] Cycle failed: {e}")
                        self._log_action(user_id, 'error', '', '', 'failed', {'error': str(e)})

                    self._schedule_next_run(user_id, config.get('frequency', 'moderate'))
                return  # success — exit retry loop

            except (AutoReconnect, ConnectionFailure, ServerSelectionTimeoutError) as e:
                print(f"⚠️ MongoDB connection dropped (attempt {attempt+1}/3): {e}")
                try:
                    mongo_client.close()
                except Exception:
                    pass
                mongo_client = _make_mongo()
                db = mongo_client[MONGODB_DB_NAME]
                time.sleep(2 ** attempt)  # back-off: 1s, 2s, 4s
            except Exception as e:
                print(f"❌ Polling error: {e}")
                return

    def run_cycle(self, user_id):
        """Run one complete automation cycle for a user."""
        # Get Instagram client
        cl = self.ig_manager.get_client(user_id)
        if not cl:
            print(f"⚠️ [{user_id}] No Instagram session available")
            return

        # Get user preferences from MongoDB
        prefs = list(db.preferences.find({
            'userId': ObjectId(user_id),
            'preferenceType': 'more',
        }))

        if not prefs:
            print(f"⚠️ [{user_id}] No preferences set")
            return

        # Collect all keywords (primary + expanded)
        all_keywords = []
        for pref in prefs:
            all_keywords.extend(pref.get('keywords', []))
            all_keywords.extend(pref.get('expandedKeywords', []))

        if not all_keywords:
            print(f"⚠️ [{user_id}] No keywords to search")
            return

        # Get today's action counts to respect daily limits
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_logs = list(db.automationlogs.find({
            'userId': ObjectId(user_id),
            'executedAt': {'$gte': today_start},
        }))

        daily_counts = {}
        for log in today_logs:
            action = log.get('actionType', '')
            daily_counts[action] = daily_counts.get(action, 0) + 1

        total_today = sum(daily_counts.values())
        if total_today >= MAX_ACTIONS_PER_DAY:
            print(f"⚠️ [{user_id}] Daily action limit reached ({total_today})")
            return

        # Determine max actions for this session (based on warmup)
        config = db.automationconfigs.find_one({'userId': ObjectId(user_id)})
        days_active = 1
        if config and config.get('startedAt'):
            delta = datetime.utcnow() - config['startedAt']
            days_active = max(1, delta.days + 1)

        max_actions = WARMUP_SCHEDULE.get(min(days_active, 7), 20)

        # Pick random keywords for this session
        session_keywords = random.sample(all_keywords, min(3, len(all_keywords)))
        actions_done = 0

        print(f"🎯 [{user_id}] Session keywords: {session_keywords}, max actions: {max_actions}")

        for keyword in session_keywords:
            if actions_done >= max_actions:
                break

            # --- SEARCH ---
            if daily_counts.get('search', 0) < DAILY_LIMITS['search']:
                try:
                    print(f"🔍 [{user_id}] Searching: {keyword}")
                    hashtags = cl.search_hashtags(keyword, amount=5)
                    self._log_action(user_id, 'search', keyword, '', 'success', {'results': len(hashtags)})
                    actions_done += 1
                    daily_counts['search'] = daily_counts.get('search', 0) + 1
                    self.human.random_delay()
                except Exception as e:
                    self._log_action(user_id, 'search', keyword, '', 'failed', {'error': str(e)})
                    print(f"❌ [{user_id}] Search failed for '{keyword}': {e}")

            if actions_done >= max_actions:
                break

            # --- VIEW POSTS ---
            try:
                hashtag_name = keyword.replace(' ', '').lower()
                medias = cl.hashtag_medias_top(hashtag_name, amount=5)

                if medias:
                    posts_to_view = random.sample(medias, min(random.randint(2, 3), len(medias)))

                    for media in posts_to_view:
                        if actions_done >= max_actions:
                            break
                        if daily_counts.get('view', 0) >= DAILY_LIMITS['view']:
                            break

                        try:
                            media_info = cl.media_info(media.pk)
                            print(f"👁️ [{user_id}] Viewed post by @{media_info.user.username}")
                            # Only store URL if code is real (empty = DemoClient, avoids broken links)
                            post_url = f"https://instagram.com/p/{media_info.code}/" if media_info.code else ''
                            self._log_action(user_id, 'view', keyword,
                                             post_url,
                                             'success',
                                             {'author': media_info.user.username})
                            actions_done += 1
                            daily_counts['view'] = daily_counts.get('view', 0) + 1
                            self.human.random_delay()

                            # --- LIKE (~40% chance) ---
                            if random.random() < 0.4 and daily_counts.get('like', 0) < DAILY_LIMITS['like']:
                                try:
                                    cl.media_like(media.pk)
                                    print(f"❤️ [{user_id}] Liked post by @{media_info.user.username}")
                                    self._log_action(user_id, 'like', keyword,
                                                     post_url,
                                                     'success',
                                                     {'author': media_info.user.username})
                                    actions_done += 1
                                    daily_counts['like'] = daily_counts.get('like', 0) + 1
                                    self.human.random_delay()
                                except Exception as e:
                                    self._log_action(user_id, 'like', keyword, '', 'failed', {'error': str(e)})

                            # --- SAVE (~20% chance) ---
                            if random.random() < 0.2 and daily_counts.get('save', 0) < DAILY_LIMITS['save']:
                                try:
                                    cl.media_save(media.pk)
                                    print(f"📑 [{user_id}] Saved post by @{media_info.user.username}")
                                    self._log_action(user_id, 'save', keyword,
                                                     post_url,
                                                     'success',
                                                     {'author': media_info.user.username})
                                    actions_done += 1
                                    daily_counts['save'] = daily_counts.get('save', 0) + 1
                                    self.human.random_delay()
                                except Exception as e:
                                    self._log_action(user_id, 'save', keyword, '', 'failed', {'error': str(e)})

                        except Exception as e:
                            print(f"❌ [{user_id}] View failed: {e}")

            except Exception as e:
                print(f"❌ [{user_id}] Hashtag media fetch failed for '{keyword}': {e}")

            # Pause between keywords
            self.human.long_pause()

        # Update session count
        db.automationconfigs.update_one(
            {'userId': ObjectId(user_id)},
            {'$inc': {'totalSessions': 1}}
        )

        # Update instagram session last activity
        db.instagramsessions.update_one(
            {'userId': ObjectId(user_id)},
            {'$set': {'lastActivity': datetime.utcnow()}}
        )

        print(f"✅ [{user_id}] Cycle complete. Actions performed: {actions_done}")

    def _log_action(self, user_id, action_type, keyword, target_url, status, details=None):
        """Log an automation action to MongoDB."""
        try:
            db.automationlogs.insert_one({
                'userId': ObjectId(user_id),
                'actionType': action_type,
                'keyword': keyword,
                'targetUrl': target_url,
                'status': status,
                'details': details or {},
                'executedAt': datetime.utcnow(),
            })
        except Exception as e:
            print(f"⚠️ Failed to log action: {e}")

    def _schedule_next_run(self, user_id, frequency):
        """Schedule the next automation run based on frequency setting."""
        frequency_minutes = {
            'conservative': random.randint(240, 480),
            'moderate': random.randint(120, 300),
            'aggressive': random.randint(60, 180),
        }

        delay = frequency_minutes.get(frequency, random.randint(120, 300))
        next_run = datetime.utcnow() + timedelta(minutes=delay)

        db.automationconfigs.update_one(
            {'userId': ObjectId(user_id)},
            {'$set': {'nextRunAt': next_run}}
        )

        print(f"⏰ [{user_id}] Next run scheduled at {next_run.strftime('%H:%M')} (+{delay}min)")
