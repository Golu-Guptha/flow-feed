const mongoose = require('mongoose');

const preferenceSchema = new mongoose.Schema({
  userId: {
    type: mongoose.Schema.Types.ObjectId,
    ref: 'User',
    required: true,
  },
  category: {
    type: String,
    required: true,
    trim: true,
  },
  keywords: {
    type: [String],
    default: [],
  },
  expandedKeywords: {
    type: [String],
    default: [],
  },
  preferenceType: {
    type: String,
    enum: ['more', 'less'],
    default: 'more',
  },
}, {
  timestamps: true,
});

preferenceSchema.index({ userId: 1 });

module.exports = mongoose.model('Preference', preferenceSchema);
