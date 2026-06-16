const express = require('express');
const jwt = require('jsonwebtoken');
const { InstagramSession } = require('../models');
const { authMiddleware } = require('../middleware/auth');

const JWT_SECRET = process.env.JWT_SECRET || 'default-secret-change-me';
const router = express.Router();

const WORKER_URL = process.env.WORKER_URL || 'http://localhost:5000';

// POST /api/instagram/connect — Connect Instagram account
router.post('/connect', authMiddleware, async (req, res) => {
  try {
    const { username, password, sessionid } = req.body;

    if (!username || (!password && !sessionid)) {
      return res.status(400).json({ error: 'Instagram username and either password or session ID are required' });
    }

    // Update status to connecting
    await InstagramSession.findOneAndUpdate(
      { userId: req.user.userId },
      {
        instagramUsername: username,
        status: 'connecting',
        lastLogin: new Date(),
      },
      { upsert: true, new: true }
    );

    // Send login request to Python worker
    try {
      const workerResponse = await fetch(`${WORKER_URL}/api/instagram/login`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: req.user.userId, username, password, sessionid }),
        signal: AbortSignal.timeout(150_000),  // 150 s — proxy rotation can take time
      });

      const result = await workerResponse.json();

      if (result.success) {
        await InstagramSession.findOneAndUpdate(
          { userId: req.user.userId },
          {
            instagramUsername: username,
            sessionData: result.session_data || null,
            status: 'connected',
            lastLogin: new Date(),
            lastActivity: new Date(),
          },
          { upsert: true }
        );

        return res.json({
          success: true,
          status: 'connected',
          username,
          message: 'Instagram account connected successfully',
        });
      } else if (result.ip_banned) {
        await InstagramSession.findOneAndUpdate(
          { userId: req.user.userId },
          { status: 'disconnected' },
          { upsert: true }
        );
        return res.status(403).json({
          success:   false,
          ip_banned: true,
          error: result.error,
        });
      } else if (result.requires_2fa) {
        await InstagramSession.findOneAndUpdate(
          { userId: req.user.userId },
          { status: 'awaiting_2fa' }
        );

        return res.json({
          success: false,
          requires_2fa: true,
          two_factor_identifier: result.two_factor_identifier,
          message: 'Two-factor authentication required',
        });
      } else if (result.requires_challenge) {
        await InstagramSession.findOneAndUpdate(
          { userId: req.user.userId },
          { status: 'awaiting_challenge' }
        );

        return res.json({
          success: false,
          requires_challenge: true,
          challenge_type: result.challenge_type,
          message: 'Instagram challenge verification required',
        });
      } else {
        await InstagramSession.findOneAndUpdate(
          { userId: req.user.userId },
          { status: 'failed' }
        );

        return res.status(400).json({
          success: false,
          error: result.error || 'Failed to connect Instagram account',
        });
      }
    } catch (workerErr) {
      console.error('Worker not available:', workerErr.message);

      // Store as pending connection
      await InstagramSession.findOneAndUpdate(
        { userId: req.user.userId },
        {
          instagramUsername: username,
          sessionData: JSON.stringify({ username, pending: true }),
          status: 'pending',
        },
        { upsert: true }
      );

      return res.json({
        success: true,
        status: 'pending',
        username,
        message: 'Credentials saved. Connection will be established when worker is available.',
      });
    }
  } catch (err) {
    console.error('Instagram connect error:', err);
    res.status(500).json({ error: 'Internal server error' });
  }
});

// POST /api/instagram/verify-2fa
router.post('/verify-2fa', authMiddleware, async (req, res) => {
  try {
    const { code, two_factor_identifier } = req.body;

    if (!code) {
      return res.status(400).json({ error: '2FA code is required' });
    }

    try {
      const workerResponse = await fetch(`${WORKER_URL}/api/instagram/verify-2fa`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          user_id: req.user.userId,
          code,
          two_factor_identifier,
        }),
      });

      const result = await workerResponse.json();

      if (result.success) {
        await InstagramSession.findOneAndUpdate(
          { userId: req.user.userId },
          {
            status: 'connected',
            sessionData: result.session_data || null,
            lastLogin: new Date(),
          }
        );

        return res.json({ success: true, status: 'connected' });
      } else {
        return res.status(400).json({ success: false, error: result.error || 'Invalid 2FA code' });
      }
    } catch (workerErr) {
      return res.status(503).json({ error: 'Automation worker not available' });
    }
  } catch (err) {
    res.status(500).json({ error: 'Internal server error' });
  }
});

// POST /api/instagram/verify-challenge
router.post('/verify-challenge', authMiddleware, async (req, res) => {
  try {
    const { code } = req.body;
    if (!code) return res.status(400).json({ error: 'Verification code is required' });

    const session = await InstagramSession.findOne({ userId: req.user.userId });
    if (!session) return res.status(400).json({ error: 'No session found. Please try connecting again.' });

    try {
      const wr = await fetch(`${WORKER_URL}/api/instagram/verify-challenge`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ user_id: req.user.userId, code }),
        signal:  AbortSignal.timeout(100_000),   // wait up to 100 s for challenge + login
      });
      const result = await wr.json();

      if (result.success) {
        await InstagramSession.findOneAndUpdate(
          { userId: req.user.userId },
          { status: 'connected', sessionData: result.session_data || null, lastLogin: new Date() }
        );
        return res.json({ success: true, status: 'connected' });
      }
      return res.status(400).json({ success: false, error: result.error || 'Invalid verification code' });
    } catch (workerErr) {
      return res.status(503).json({ error: 'Automation worker not available. Make sure python worker.py is running.' });
    }
  } catch (err) {
    console.error('verify-challenge error:', err);
    res.status(500).json({ error: 'Internal server error' });
  }
});

// GET /api/instagram/status
router.get('/status', authMiddleware, async (req, res) => {
  try {
    const session = await InstagramSession.findOne({ userId: req.user.userId });

    if (!session) {
      return res.json({
        connected: false,
        status: 'disconnected',
        username: null,
      });
    }

    res.json({
      connected: session.status === 'connected',
      status: session.status,
      username: session.instagramUsername,
      lastLogin: session.lastLogin,
      lastActivity: session.lastActivity,
    });
  } catch (err) {
    res.status(500).json({ error: 'Internal server error' });
  }
});

// POST /api/instagram/disconnect
router.post('/disconnect', authMiddleware, async (req, res) => {
  try {
    await InstagramSession.findOneAndUpdate(
      { userId: req.user.userId },
      { status: 'disconnected', sessionData: null }
    );

    res.json({ success: true, status: 'disconnected' });
  } catch (err) {
    res.status(500).json({ error: 'Internal server error' });
  }
});

// POST /api/instagram/browser-connect — open a real browser for the user to log in
router.post('/browser-connect', authMiddleware, async (req, res) => {
  try {
    await InstagramSession.findOneAndUpdate(
      { userId: req.user.userId },
      { instagramUsername: '', status: 'connecting', lastLogin: new Date() },
      { upsert: true, new: true }
    );

    try {
      await fetch(`${WORKER_URL}/api/instagram/browser-login`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ user_id: req.user.userId, username: '' }),
        signal:  AbortSignal.timeout(10_000),
      });
    } catch (e) {
      await InstagramSession.findOneAndUpdate(
        { userId: req.user.userId },
        { status: 'disconnected' },
        { upsert: true }
      );
      return res.status(503).json({ error: 'Automation worker not available. Make sure python worker.py is running.' });
    }

    res.json({ success: true, status: 'browser_opened',
               message: 'A browser window has been opened. Please log in to Instagram.' });
  } catch (err) {
    console.error('browser-connect error:', err);
    res.status(500).json({ error: 'Internal server error' });
  }
});

// GET /api/instagram/browser-connect-status — poll whether the browser login succeeded
router.get('/browser-connect-status', authMiddleware, async (req, res) => {
  try {
    const wr = await fetch(
      `${WORKER_URL}/api/instagram/browser-login-status?user_id=${req.user.userId}`,
      { signal: AbortSignal.timeout(8_000) }
    );
    const workerResult = await wr.json();

    if (workerResult.status === 'connected' && workerResult.success) {
      const detectedUsername = workerResult.detected_username || workerResult.username || '';
      await InstagramSession.findOneAndUpdate(
        { userId: req.user.userId },
        {
          instagramUsername: detectedUsername,
          sessionData: workerResult.session_data || null,
          status: 'connected',
          lastLogin: new Date(),
          lastActivity: new Date(),
        },
        { upsert: true }
      );
      return res.json({ success: true, status: 'connected', username: detectedUsername });
    }

    if (workerResult.status === 'failed') {
      await InstagramSession.findOneAndUpdate(
        { userId: req.user.userId },
        { status: 'disconnected' },
        { upsert: true }
      );
      return res.json({ success: false, status: 'failed', error: workerResult.error });
    }

    // Still waiting
    return res.json({ success: false, status: 'connecting', message: workerResult.message || 'Waiting for browser login...' });
  } catch (e) {
    // Worker unreachable — fall back to DB status
    const session = await InstagramSession.findOne({ userId: req.user.userId });
    return res.json({
      success: session?.status === 'connected',
      status:  session?.status || 'connecting',
    });
  }
});

module.exports = router;
