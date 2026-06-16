const express = require('express');
const cors = require('cors');
const helmet = require('helmet');
const rateLimit = require('express-rate-limit');
require('dotenv').config();

const { connectDB } = require('./config/database');
const authRoutes = require('./routes/auth');
const preferencesRoutes = require('./routes/preferences');
const instagramRoutes = require('./routes/instagram');
const automationRoutes = require('./routes/automation');
const analyticsRoutes = require('./routes/analytics');

const app = express();
const PORT = process.env.PORT || 3000;

// Middleware
app.use(helmet());
app.use(cors());
app.use(express.json());

// Rate limiting
const limiter = rateLimit({
  windowMs: 15 * 60 * 1000,
  max: 100,
  standardHeaders: true,
  legacyHeaders: false,
});
app.use(limiter);

// Health check
app.get('/health', (req, res) => {
  res.json({ status: 'ok', timestamp: new Date().toISOString() });
});

// Routes
app.use('/api/auth', authRoutes);
app.use('/api/preferences', preferencesRoutes);
app.use('/api/instagram', instagramRoutes);
app.use('/api/automation', automationRoutes);
app.use('/api/analytics', analyticsRoutes);

// Error handling middleware
app.use((err, req, res, next) => {
  console.error('Error:', err.message);
  res.status(err.status || 500).json({
    error: err.message || 'Internal server error',
  });
});

// Connect to MongoDB then start server
connectDB().then(() => {
  app.listen(PORT, () => {
    console.log(`🚀 FeedFlow API running on port ${PORT}`);
  });
});

module.exports = app;
