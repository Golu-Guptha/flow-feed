const express = require('express');
const bcrypt = require('bcryptjs');
const jwt = require('jsonwebtoken');
const { User, AutomationConfig } = require('../models');
const { authMiddleware } = require('../middleware/auth');

const router = express.Router();

const JWT_SECRET = process.env.JWT_SECRET || 'default-secret-change-me';
const JWT_REFRESH_SECRET = process.env.JWT_REFRESH_SECRET || 'default-refresh-secret';

function generateTokens(userId, email) {
  const accessToken = jwt.sign({ userId, email }, JWT_SECRET, { expiresIn: '24h' });
  const refreshToken = jwt.sign({ userId, email }, JWT_REFRESH_SECRET, { expiresIn: '7d' });
  return { accessToken, refreshToken };
}

// POST /api/auth/register
router.post('/register', async (req, res) => {
  try {
    const { email, password, name } = req.body;

    if (!email || !password) {
      return res.status(400).json({ error: 'Email and password are required' });
    }

    if (password.length < 6) {
      return res.status(400).json({ error: 'Password must be at least 6 characters' });
    }

    // Check if user already exists
    const existing = await User.findOne({ email: email.toLowerCase() });
    if (existing) {
      return res.status(409).json({ error: 'User already exists' });
    }

    // Hash password
    const passwordHash = await bcrypt.hash(password, 12);

    // Create user
    const user = await User.create({
      email: email.toLowerCase(),
      passwordHash,
      name: name || '',
    });

    // Create default automation config
    await AutomationConfig.create({ userId: user._id });

    // Generate tokens
    const tokens = generateTokens(user._id, user.email);

    res.status(201).json({
      user: {
        id: user._id,
        email: user.email,
        name: user.name,
      },
      ...tokens,
    });
  } catch (err) {
    console.error('Registration error:', err);
    res.status(500).json({ error: 'Internal server error' });
  }
});

// POST /api/auth/login
router.post('/login', async (req, res) => {
  try {
    const { email, password } = req.body;

    if (!email || !password) {
      return res.status(400).json({ error: 'Email and password are required' });
    }

    // Find user (include passwordHash for comparison)
    const user = await User.findOne({ email: email.toLowerCase() }).select('+passwordHash');
    if (!user) {
      return res.status(401).json({ error: 'Invalid email or password' });
    }

    // Verify password
    const validPassword = await bcrypt.compare(password, user.passwordHash);
    if (!validPassword) {
      return res.status(401).json({ error: 'Invalid email or password' });
    }

    // Generate tokens
    const tokens = generateTokens(user._id, user.email);

    res.json({
      user: {
        id: user._id,
        email: user.email,
        name: user.name,
      },
      ...tokens,
    });
  } catch (err) {
    console.error('Login error:', err);
    res.status(500).json({ error: 'Internal server error' });
  }
});

// POST /api/auth/refresh
router.post('/refresh', async (req, res) => {
  try {
    const { refreshToken } = req.body;

    if (!refreshToken) {
      return res.status(400).json({ error: 'Refresh token required' });
    }

    const decoded = jwt.verify(refreshToken, JWT_REFRESH_SECRET);
    const tokens = generateTokens(decoded.userId, decoded.email);

    res.json(tokens);
  } catch (err) {
    res.status(401).json({ error: 'Invalid refresh token' });
  }
});

// GET /api/auth/me
router.get('/me', authMiddleware, async (req, res) => {
  try {
    const user = await User.findById(req.user.userId);
    if (!user) {
      return res.status(404).json({ error: 'User not found' });
    }

    res.json({ user });
  } catch (err) {
    res.status(500).json({ error: 'Internal server error' });
  }
});

// PUT /api/auth/profile — Update display name
router.put('/profile', authMiddleware, async (req, res) => {
  try {
    const { name } = req.body;
    const user = await User.findByIdAndUpdate(
      req.user.userId,
      { name: (name || '').trim() },
      { new: true }
    );
    if (!user) return res.status(404).json({ error: 'User not found' });
    res.json({ user });
  } catch (err) {
    console.error('Profile update error:', err);
    res.status(500).json({ error: 'Internal server error' });
  }
});

module.exports = router;
