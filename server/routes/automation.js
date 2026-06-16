const express = require('express');
const { AutomationConfig, InstagramSession, Preference } = require('../models');
const { authMiddleware } = require('../middleware/auth');

const WORKER_URL = process.env.WORKER_URL || 'https://feedflow-worker-3j6j.onrender.com';
const router = express.Router();

// POST /api/automation/start
router.post('/start', authMiddleware, async (req, res) => {
  try {
    // Check if Instagram is connected
    const session = await InstagramSession.findOne({ userId: req.user.userId });
    if (!session || (session.status !== 'connected' && session.status !== 'pending')) {
      return res.status(400).json({ error: 'Please connect your Instagram account first' });
    }

    // Check if user has preferences
    const prefsCount = await Preference.countDocuments({ userId: req.user.userId });
    if (prefsCount === 0) {
      return res.status(400).json({ error: 'Please set your content preferences first' });
    }

    // Update automation config
    const config = await AutomationConfig.findOneAndUpdate(
      { userId: req.user.userId },
      {
        isActive: true,
        startedAt: new Date(),
        nextRunAt: new Date(), // Run immediately
      },
      { upsert: true, new: true }
    );

    res.json({
      success: true,
      status: 'active',
      message: 'Automation started successfully',
      config,
    });
  } catch (err) {
    console.error('Start automation error:', err);
    res.status(500).json({ error: 'Internal server error' });
  }
});

// POST /api/automation/stop
router.post('/stop', authMiddleware, async (req, res) => {
  try {
    await AutomationConfig.findOneAndUpdate(
      { userId: req.user.userId },
      { isActive: false, nextRunAt: null }
    );

    res.json({
      success: true,
      status: 'paused',
      message: 'Automation stopped',
    });
  } catch (err) {
    res.status(500).json({ error: 'Internal server error' });
  }
});

// GET /api/automation/status
router.get('/status', authMiddleware, async (req, res) => {
  try {
    const config = await AutomationConfig.findOne({ userId: req.user.userId });

    if (!config) {
      return res.json({
        isActive: false,
        status: 'inactive',
        frequency: 'moderate',
        totalSessions: 0,
        daysActive: 0,
      });
    }

    // Calculate days active
    let daysActive = 0;
    if (config.startedAt) {
      daysActive = Math.ceil((Date.now() - config.startedAt.getTime()) / (1000 * 60 * 60 * 24));
    }

    res.json({
      isActive: config.isActive,
      status: config.isActive ? 'active' : 'paused',
      frequency: config.frequency,
      activeHoursStart: config.activeHoursStart,
      activeHoursEnd: config.activeHoursEnd,
      actionsPerSession: config.actionsPerSession,
      startedAt: config.startedAt,
      nextRunAt: config.nextRunAt,
      totalSessions: config.totalSessions || 0,
      daysActive,
    });
  } catch (err) {
    res.status(500).json({ error: 'Internal server error' });
  }
});

// PUT /api/automation/config
router.put('/config', authMiddleware, async (req, res) => {
  try {
    const { frequency, activeHoursStart, activeHoursEnd, actionsPerSession } = req.body;

    const updates = {};
    if (frequency) updates.frequency = frequency;
    if (activeHoursStart !== undefined) updates.activeHoursStart = activeHoursStart;
    if (activeHoursEnd !== undefined) updates.activeHoursEnd = activeHoursEnd;
    if (actionsPerSession !== undefined) updates.actionsPerSession = actionsPerSession;

    const config = await AutomationConfig.findOneAndUpdate(
      { userId: req.user.userId },
      updates,
      { upsert: true, new: true }
    );

    res.json({ success: true, config });
  } catch (err) {
    res.status(500).json({ error: 'Internal server error' });
  }
});


// POST /api/automation/run-now — trigger an immediate cycle without waiting for scheduler
router.post('/run-now', authMiddleware, async (req, res) => {
  try {
    const session = await InstagramSession.findOne({ userId: req.user.userId });

    if (!session) {
      return res.status(400).json({ error: 'Please connect your Instagram account first in the Connect tab.' });
    }

    if (session.status === 'pending') {
      return res.status(400).json({
        error: 'Instagram connection is pending — the worker was not running when you connected. Please go to the Connect tab and re-enter your credentials while the automation worker (python worker.py) is running.',
        code: 'SESSION_PENDING',
      });
    }

    if (session.status !== 'connected') {
      return res.status(400).json({ error: `Instagram session is ${session.status}. Please reconnect your account in the Connect tab.` });
    }

    // Activate and schedule for immediate run
    await AutomationConfig.findOneAndUpdate(
      { userId: req.user.userId },
      { isActive: true, startedAt: new Date(), nextRunAt: new Date() },
      { upsert: true, new: true }
    );

    // Ask the worker to run right now
    try {
      const wr = await fetch(`${WORKER_URL}/api/automation/run`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ user_id: req.user.userId }),
        signal:  AbortSignal.timeout(8000),
      });
      const result = await wr.json();
      return res.json({ success: true, message: 'Automation cycle started immediately', worker: result });
    } catch {
      return res.json({ success: true, message: 'Automation queued — worker will run within 60 seconds', workerAvailable: false });
    }
  } catch (err) {
    console.error('Run-now error:', err);
    res.status(500).json({ error: 'Internal server error' });
  }
});


// POST /api/automation/unlike  — undo a like the AI did
router.post('/unlike', authMiddleware, async (req, res) => {
  try {
    const { targetUrl } = req.body;
    const response = await fetch(`${WORKER_URL}/api/instagram/unlike`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: req.user.userId, target_url: targetUrl }),
      signal: AbortSignal.timeout(10000),
    });
    const result = await response.json();
    return result.success
      ? res.json({ success: true })
      : res.status(400).json({ error: result.error || 'Unlike failed' });
  } catch (err) {
    res.status(503).json({ error: 'Automation worker not available' });
  }
});

// POST /api/automation/unfollow  — undo a follow the AI did
router.post('/unfollow', authMiddleware, async (req, res) => {
  try {
    const { username } = req.body;
    const response = await fetch(`${WORKER_URL}/api/instagram/unfollow`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ user_id: req.user.userId, username }),
      signal: AbortSignal.timeout(10000),
    });
    const result = await response.json();
    return result.success
      ? res.json({ success: true })
      : res.status(400).json({ error: result.error || 'Unfollow failed' });
  } catch (err) {
    res.status(503).json({ error: 'Automation worker not available' });
  }
});

module.exports = router;
