"""
FeedFlow Automation Worker
Main entry point -- Flask API bridge + APScheduler for automation cycles.
Uses MongoDB for data persistence.
"""
import sys
import re
import threading

# Force UTF-8 output so emoji in print() don't crash on Windows cp1252 consoles
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except AttributeError:
    pass  # Python < 3.7 fallback

from flask import Flask, request, jsonify
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
from config import WORKER_PORT
from instagram_client import InstagramClientManager
from actions import AutomationEngine

app = Flask(__name__)
CORS(app)

# Initialize components
ig_manager = InstagramClientManager()
engine = AutomationEngine(ig_manager)

# Scheduler for recurring automation
scheduler = BackgroundScheduler()
scheduler.start()


# ---- API Bridge (called by Node.js backend) ----

@app.route('/', methods=['GET', 'HEAD'])
def health_check():
    return jsonify({'status': 'ok'}), 200

@app.route('/api/instagram/login', methods=['POST'])
def instagram_login():
    """Login to Instagram in a background thread so we never block Flask."""
    data = request.json
    user_id   = data.get('user_id')
    username  = data.get('username')
    password  = data.get('password')
    sessionid = data.get('sessionid')

    print("--- LOGIN REQUEST ---")
    print("user_id:", user_id)
    print("username:", username)
    print("sessionid provided:", bool(sessionid))

    if not all([user_id, username]):
        return jsonify({'success': False, 'error': 'Missing required fields'}), 400
    
    if not password and not sessionid:
        return jsonify({'success': False, 'error': 'Must provide either password or sessionid'}), 400

    result_holder = {}

    def do_login():
        result = ig_manager.login(user_id, username, password, sessionid=sessionid)
        result_holder['result'] = result
        result_holder['done']   = True

    thread = threading.Thread(target=do_login)
    thread.daemon = True
    thread.start()
    thread.join(timeout=120)          # wait up to 120 s for proxy rotation

    if result_holder.get('done'):
        return jsonify(result_holder['result'])

    # Still running after 30 s — must be waiting for a challenge code
    if user_id in ig_manager._challenge_events:
        return jsonify({
            'success':           False,
            'requires_challenge': True,
            'challenge_type':    'email',
        })

    # Generic slow-response fallback
    return jsonify({
        'success': False,
        'error': 'Instagram is taking too long to respond. Please try again in a moment.',
    }), 408


@app.route('/api/instagram/browser-login', methods=['POST'])
def instagram_browser_login():
    """Launch a visible Chromium browser for the user to log into Instagram."""
    data = request.json or {}
    user_id  = data.get('user_id')
    username = data.get('username', '')

    if not user_id:
        return jsonify({'success': False, 'error': 'user_id required'}), 400

    # Clear any stale result
    ig_manager._login_results.pop(user_id, None)

    def do_browser_login():
        ig_manager.browser_login(user_id, username)

    thread = threading.Thread(target=do_browser_login)
    thread.daemon = True
    thread.start()

    return jsonify({'success': True, 'status': 'browser_opened',
                    'message': 'Browser opened. Please log in to Instagram.'})


@app.route('/api/instagram/browser-login-status', methods=['GET'])
def instagram_browser_login_status():
    """Poll the result of the browser login (called repeatedly by the app)."""
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'status': 'unknown'}), 400

    result = ig_manager._login_results.get(user_id, {})

    if result.get('success'):
        return jsonify({'status': 'connected', **result})
    if result.get('status') == 'browser_open':
        return jsonify({'status': 'waiting', 'message': 'Waiting for Instagram login in browser...'})
    if result.get('error') and not result.get('status') == 'browser_open':
        return jsonify({'status': 'failed', 'error': result['error']})

    return jsonify({'status': 'waiting', 'message': 'Opening browser...'})


@app.route('/api/instagram/verify-2fa', methods=['POST'])
def instagram_verify_2fa():
    """Verify 2FA code."""
    data = request.json
    user_id = data.get('user_id')
    code = data.get('code')
    two_factor_identifier = data.get('two_factor_identifier')

    result = ig_manager.verify_2fa(user_id, code, two_factor_identifier)
    return jsonify(result)


@app.route('/api/instagram/verify-challenge', methods=['POST'])
def instagram_verify_challenge():
    """Submit an Instagram challenge/security code to unblock the waiting login thread."""
    data    = request.json or {}
    user_id = data.get('user_id')
    code    = data.get('code', '').strip()

    if not user_id or not code:
        return jsonify({'success': False, 'error': 'user_id and code are required'}), 400

    # submit_challenge_code() blocks until the background login thread finishes
    result = ig_manager.submit_challenge_code(user_id, code)
    return jsonify(result)


@app.route('/api/automation/run', methods=['POST'])
def run_automation():
    """Manually trigger an automation cycle for a user."""
    data = request.json
    user_id = data.get('user_id')

    if not user_id:
        return jsonify({'error': 'user_id required'}), 400

    # Run in background thread
    thread = threading.Thread(target=engine.run_cycle, args=(user_id,))
    thread.daemon = True
    thread.start()

    return jsonify({'success': True, 'message': 'Automation cycle started'})


@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'service': 'feedflow-worker'})


@app.route('/api/instagram/unlike', methods=['POST'])
def instagram_unlike():
    """Unlike a post that the automation previously liked."""
    data = request.json or {}
    user_id   = data.get('user_id')
    target_url = data.get('target_url', '')

    if not user_id:
        return jsonify({'success': False, 'error': 'user_id required'}), 400

    try:
        cl = ig_manager.get_client(user_id)
        if not cl:
            return jsonify({'success': False, 'error': 'No Instagram session found'}), 400

        # Extract media shortcode from URL like https://instagram.com/p/{code}/
        match = re.search(r'/p/([^/?#]+)', target_url)
        if not match:
            return jsonify({'success': False, 'error': 'Could not parse post URL'}), 400

        media_code = match.group(1)
        media_pk   = cl.media_pk_from_code(media_code)
        cl.media_unlike(media_pk)
        return jsonify({'success': True, 'message': 'Post unliked'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/instagram/unsave', methods=['POST'])
def instagram_unsave():
    """Unsave a post that the automation previously saved."""
    data = request.json or {}
    user_id    = data.get('user_id')
    target_url = data.get('target_url', '')

    if not user_id:
        return jsonify({'success': False, 'error': 'user_id required'}), 400

    try:
        cl = ig_manager.get_client(user_id)
        if not cl:
            return jsonify({'success': False, 'error': 'No Instagram session found'}), 400

        match = re.search(r'/p/([^/?#]+)', target_url)
        if not match:
            return jsonify({'success': False, 'error': 'Could not parse post URL'}), 400

        media_code = match.group(1)
        media_pk   = cl.media_pk_from_code(media_code)
        cl.media_unsave(media_pk)
        return jsonify({'success': True, 'message': 'Post unsaved'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/instagram/unfollow', methods=['POST'])
def instagram_unfollow():
    """Unfollow a user that the automation previously followed."""
    data = request.json or {}
    user_id  = data.get('user_id')
    username = data.get('username', '')

    if not user_id or not username:
        return jsonify({'success': False, 'error': 'user_id and username required'}), 400

    try:
        cl = ig_manager.get_client(user_id)
        if not cl:
            return jsonify({'success': False, 'error': 'No Instagram session found'}), 400

        user_info = cl.user_info_by_username(username)
        cl.user_unfollow(user_info.pk)
        return jsonify({'success': True, 'message': f'Unfollowed @{username}'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


def start_polling():
    """Background job that checks for active users and runs automation."""
    engine.poll_and_run()


# Schedule polling every 60 seconds
scheduler.add_job(start_polling, 'interval', seconds=60, id='poll_active_users', replace_existing=True)


if __name__ == '__main__':
    print(f"[FeedFlow] Worker running on port {WORKER_PORT}")
    app.run(host='0.0.0.0', port=WORKER_PORT, debug=False)
