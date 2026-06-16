const mongoose = require('mongoose');

const automationConfigSchema = new mongoose.Schema({
  userId: {
    type: mongoose.Schema.Types.ObjectId,
    ref: 'User',
    required: true,
    unique: true,
  },
  isActive: {
    type: Boolean,
    default: false,
  },
  frequency: {
    type: String,
    enum: ['conservative', 'moderate', 'aggressive'],
    default: 'moderate',
  },
  activeHoursStart: {
    type: Number,
    default: 8,
    min: 0,
    max: 23,
  },
  activeHoursEnd: {
    type: Number,
    default: 22,
    min: 0,
    max: 23,
  },
  actionsPerSession: {
    type: Number,
    default: 10,
    min: 5,
    max: 30,
  },
  startedAt: {
    type: Date,
    default: null,
  },
  nextRunAt: {
    type: Date,
    default: null,
  },
  totalSessions: {
    type: Number,
    default: 0,
  },
}, {
  timestamps: true,
});

automationConfigSchema.index({ isActive: 1, nextRunAt: 1 });

module.exports = mongoose.model('AutomationConfig', automationConfigSchema);
