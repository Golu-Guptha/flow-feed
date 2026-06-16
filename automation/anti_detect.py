"""
Anti-Detection Module
Human-like behavior simulation to avoid Instagram bot detection.
In TEST_MODE all delays are reduced to < 1 second.
"""
import time
import random
from config import MIN_ACTION_DELAY, MAX_ACTION_DELAY, TEST_MODE


class HumanBehavior:
    """Simulates human-like interaction patterns."""

    def random_delay(self):
        """Random delay between individual actions (1-3s in TEST_MODE, 30-180s in production)."""
        delay = random.uniform(MIN_ACTION_DELAY, MAX_ACTION_DELAY)
        if not TEST_MODE:
            print(f"  Waiting {delay:.0f}s...")
        time.sleep(delay)

    def long_pause(self):
        """Longer pause between keyword groups (0.1s in TEST_MODE, 2-5min in production)."""
        if TEST_MODE:
            time.sleep(0.1)
            return
        delay = random.uniform(120, 300)
        print(f"  Long pause {delay:.0f}s...")
        time.sleep(delay)

    def session_warmup_delay(self):
        """Initial delay simulating app opening (skipped in TEST_MODE)."""
        if TEST_MODE:
            return
        delay = random.uniform(5, 15)
        time.sleep(delay)

    def should_skip_action(self, probability=0.15):
        """Randomly decide whether to skip an action for unpredictability."""
        return random.random() < probability

    def get_random_scroll_time(self):
        """Simulate time spent scrolling/reading a post."""
        return random.uniform(0.1, 0.3) if TEST_MODE else random.uniform(3, 12)

    def get_session_actions_count(self, max_actions):
        """Return a slightly randomized action count for this session."""
        variance = max(1, int(max_actions * 0.2))
        return random.randint(max(1, max_actions - variance), max_actions + variance)
