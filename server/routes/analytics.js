const express = require('express');
const mongoose = require('mongoose');
const { AutomationLog, AutomationConfig } = require('../models');
const { authMiddleware } = require('../middleware/auth');

const router = express.Router();

// GET /api/analytics/summary
router.get('/summary', authMiddleware, async (req, res) => {
  try {
    const { period } = req.query; // 'today', 'week', 'all'

    let dateFilter = {};
    const now = new Date();

    if (period === 'today') {
      const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      dateFilter = { executedAt: { $gte: todayStart } };
    } else if (period === 'week') {
      const weekAgo = new Date(now);
      weekAgo.setDate(weekAgo.getDate() - 7);
      dateFilter = { executedAt: { $gte: weekAgo } };
    }

    // Cast string userId to ObjectId — aggregate() does NOT auto-cast unlike .find()
    const userObjId = new mongoose.Types.ObjectId(req.user.userId);

    // Aggregate action counts
    const pipeline = [
      { $match: { userId: userObjId, ...dateFilter } },
      {
        $group: {
          _id: '$actionType',
          count: { $sum: 1 },
          successCount: {
            $sum: { $cond: [{ $eq: ['$status', 'success'] }, 1, 0] },
          },
        },
      },
    ];

    const results = await AutomationLog.aggregate(pipeline);

    const stats = {
      totalActions: 0,
      searches: 0,
      views: 0,
      likes: 0,
      saves: 0,
      follows: 0,
      successRate: 100,
    };

    let totalSuccess = 0;

    results.forEach((r) => {
      stats.totalActions += r.count;
      totalSuccess += r.successCount;
      switch (r._id) {
        case 'search': stats.searches = r.count; break;
        case 'view': stats.views = r.count; break;
        case 'like': stats.likes = r.count; break;
        case 'save': stats.saves = r.count; break;
        case 'follow': stats.follows = r.count; break;
      }
    });

    if (stats.totalActions > 0) {
      stats.successRate = Math.round((totalSuccess / stats.totalActions) * 100);
    }

    // Get today's count specifically
    const todayStart2 = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const todayCount = await AutomationLog.countDocuments({
      userId: req.user.userId,   // .find()/.countDocuments() auto-casts
      executedAt: { $gte: todayStart2 },
    });

    res.json({
      ...stats,
      todayActions: todayCount,
      period: period || 'all',
    });
  } catch (err) {
    console.error('Analytics summary error:', err);
    res.status(500).json({ error: 'Internal server error' });
  }
});

// GET /api/analytics/history
router.get('/history', authMiddleware, async (req, res) => {
  try {
    const { limit = 50, offset = 0 } = req.query;

    const history = await AutomationLog.find({ userId: req.user.userId })
      .sort({ executedAt: -1 })
      .skip(parseInt(offset))
      .limit(parseInt(limit));

    res.json({ history });
  } catch (err) {
    res.status(500).json({ error: 'Internal server error' });
  }
});

// GET /api/analytics/feed-score
router.get('/feed-score', authMiddleware, async (req, res) => {
  try {
    const config = await AutomationConfig.findOne({ userId: req.user.userId });

    // Get successful action counts and unique types
    const userObjId2 = new mongoose.Types.ObjectId(req.user.userId);
    const pipeline = [
      { $match: { userId: userObjId2, status: 'success' } },
      {
        $group: {
          _id: null,
          totalActions: { $sum: 1 },
          uniqueTypes: { $addToSet: '$actionType' },
        },
      },
    ];

    const [result] = await AutomationLog.aggregate(pipeline);

    let daysActive = 0;
    if (config && config.startedAt) {
      daysActive = Math.ceil((Date.now() - config.startedAt.getTime()) / (1000 * 60 * 60 * 24));
    }

    const totalActions = result ? result.totalActions : 0;
    const uniqueActions = result ? result.uniqueTypes.length : 0;
    const totalSessions = config ? (config.totalSessions || 0) : 0;

    // Feed Improvement Score formula
    const dayScore = Math.min(35, daysActive * 5);
    const actionScore = Math.min(30, totalActions * 0.5);
    const diversityScore = Math.min(20, uniqueActions * 5);
    const consistencyScore = totalSessions > daysActive * 2
      ? 15
      : Math.min(15, (totalSessions / Math.max(1, daysActive * 2)) * 15);

    const feedScore = Math.min(100, Math.round(dayScore + actionScore + diversityScore + consistencyScore));

    res.json({
      feedScore,
      breakdown: {
        daysActive: { value: daysActive, score: dayScore, max: 35 },
        totalActions: { value: totalActions, score: actionScore, max: 30 },
        actionDiversity: { value: uniqueActions, score: diversityScore, max: 20 },
        consistency: { value: totalSessions, score: Math.round(consistencyScore), max: 15 },
      },
    });
  } catch (err) {
    console.error('Feed score error:', err);
    res.status(500).json({ error: 'Internal server error' });
  }
});

// GET /api/analytics/daily
router.get('/daily', authMiddleware, async (req, res) => {
  try {
    // Aggregate logs by day for the last 30 days
    const thirtyDaysAgo = new Date();
    thirtyDaysAgo.setDate(thirtyDaysAgo.getDate() - 30);

    const userObjId3 = new mongoose.Types.ObjectId(req.user.userId);
    const pipeline = [
      {
        $match: {
          userId: userObjId3,
          executedAt: { $gte: thirtyDaysAgo },
        },
      },
      {
        $group: {
          _id: {
            $dateToString: { format: '%Y-%m-%d', date: '$executedAt' },
          },
          totalSearches: {
            $sum: { $cond: [{ $eq: ['$actionType', 'search'] }, 1, 0] },
          },
          totalViews: {
            $sum: { $cond: [{ $eq: ['$actionType', 'view'] }, 1, 0] },
          },
          totalLikes: {
            $sum: { $cond: [{ $eq: ['$actionType', 'like'] }, 1, 0] },
          },
          totalSaves: {
            $sum: { $cond: [{ $eq: ['$actionType', 'save'] }, 1, 0] },
          },
          totalActions: { $sum: 1 },
        },
      },
      { $sort: { _id: -1 } },
    ];

    const daily = await AutomationLog.aggregate(pipeline);

    // Rename _id to date for cleaner output
    const formatted = daily.map((d) => ({
      date: d._id,
      totalSearches: d.totalSearches,
      totalViews: d.totalViews,
      totalLikes: d.totalLikes,
      totalSaves: d.totalSaves,
      totalActions: d.totalActions,
    }));

    res.json({ daily: formatted });
  } catch (err) {
    res.status(500).json({ error: 'Internal server error' });
  }
});

module.exports = router;
