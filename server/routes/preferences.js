const express = require('express');
const { Preference } = require('../models');
const { authMiddleware } = require('../middleware/auth');

const router = express.Router();

// Keyword expansion map — when user selects a category, these sub-keywords are auto-added
const KEYWORD_EXPANSIONS = {
  'Technology': ['Tech News', 'Software', 'Gadgets', 'Innovation', 'Tech Reviews', 'Programming'],
  'Artificial Intelligence': ['Machine Learning', 'Deep Learning', 'GPT', 'Neural Networks', 'LLM', 'Computer Vision', 'NLP', 'AI Tools'],
  'Programming': ['Coding', 'Web Development', 'JavaScript', 'Python', 'React', 'Software Engineering', 'DevOps'],
  'Cybersecurity': ['Bug Bounty', 'Ethical Hacking', 'Pentesting', 'Network Security', 'CTF', 'InfoSec', 'Malware Analysis'],
  'Gaming': ['Video Games', 'Esports', 'Game Dev', 'PC Gaming', 'Console Gaming', 'Twitch', 'Gaming Setup'],
  'Fitness': ['Workout', 'Gym', 'Bodybuilding', 'Cardio', 'Weight Training', 'CrossFit', 'Yoga'],
  'Health': ['Nutrition', 'Wellness', 'Mental Health', 'Diet', 'Healthy Living', 'Meditation', 'Self Care'],
  'Business': ['Entrepreneurship', 'Startup', 'Marketing', 'Management', 'Strategy', 'Leadership'],
  'Finance': ['Investing', 'Stock Market', 'Crypto', 'Personal Finance', 'Trading', 'Financial Literacy', 'Wealth'],
  'Startups': ['Venture Capital', 'Product Launch', 'SaaS', 'Bootstrapping', 'Pitch Deck', 'Founder Life'],
  'Travel': ['Backpacking', 'Adventure', 'Solo Travel', 'Travel Photography', 'Digital Nomad', 'Wanderlust'],
  'Photography': ['Street Photography', 'Portrait', 'Landscape', 'Photo Editing', 'Camera Gear', 'Visual Art'],
  'Education': ['Online Learning', 'Study Tips', 'EdTech', 'MOOCs', 'Knowledge', 'Learning'],
  'Science': ['Physics', 'Biology', 'Chemistry', 'Space', 'Research', 'Scientific Discovery'],
  'Music': ['Music Production', 'Guitar', 'Piano', 'Singing', 'Hip Hop', 'Electronic Music'],
  'Art': ['Digital Art', 'Illustration', 'Painting', 'Graphic Design', 'Creative Art', 'Art Tutorials'],
  'Food': ['Cooking', 'Recipes', 'Baking', 'Food Photography', 'Healthy Eating', 'Restaurant'],
  'Fashion': ['Street Style', 'Outfit Ideas', 'Sneakers', 'Fashion Trends', 'Luxury Fashion'],
  'News': ['World News', 'Current Events', 'Politics', 'Global Affairs', 'Breaking News'],
  'Design': ['UI Design', 'UX Design', 'Web Design', 'Interior Design', 'Product Design', 'Figma'],
  'Entrepreneurship': ['Side Hustle', 'Business Ideas', 'Solopreneur', 'Growth Hacking', 'Ecommerce'],
  'Nature': ['Wildlife', 'Environment', 'Conservation', 'Outdoor', 'Hiking', 'National Parks'],
  'Lifestyle': ['Productivity', 'Minimalism', 'Home Decor', 'Daily Routine', 'Self Improvement'],
  'Sports': ['Football', 'Basketball', 'Cricket', 'Tennis', 'Running', 'Athletics'],
};

function expandKeywords(category) {
  return KEYWORD_EXPANSIONS[category] || [];
}

// GET /api/preferences — Get user's preferences
router.get('/', authMiddleware, async (req, res) => {
  try {
    const preferences = await Preference.find({ userId: req.user.userId })
      .sort({ createdAt: 1 });

    res.json({ preferences });
  } catch (err) {
    console.error('Preferences fetch error:', err);
    res.status(500).json({ error: 'Internal server error' });
  }
});

// PUT /api/preferences — Update preferences (replaces all)
router.put('/', authMiddleware, async (req, res) => {
  try {
    const { preferences } = req.body;

    if (!preferences || !Array.isArray(preferences)) {
      return res.status(400).json({ error: 'preferences must be an array' });
    }

    // Delete existing preferences
    await Preference.deleteMany({ userId: req.user.userId });

    // Insert new preferences with expanded keywords
    const prefsToInsert = preferences.map((pref) => ({
      userId: req.user.userId,
      category: pref.category,
      keywords: [pref.category, ...(pref.customKeywords || [])],
      expandedKeywords: expandKeywords(pref.category),
      preferenceType: pref.type || 'more',
    }));

    const created = await Preference.insertMany(prefsToInsert);

    res.json({ preferences: created });
  } catch (err) {
    console.error('Preferences update error:', err);
    res.status(500).json({ error: 'Internal server error' });
  }
});

// GET /api/preferences/categories — Get available categories
router.get('/categories', (req, res) => {
  const categories = Object.keys(KEYWORD_EXPANSIONS).map((name) => ({
    name,
    subKeywords: KEYWORD_EXPANSIONS[name],
  }));
  res.json({ categories });
});

module.exports = router;
