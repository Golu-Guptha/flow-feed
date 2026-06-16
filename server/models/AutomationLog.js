const mongoose = require('mongoose');

const automationLogSchema = new mongoose.Schema({
  userId: {
    type: mongoose.Schema.Types.ObjectId,
    ref: 'User',
    required: true,
  },
  actionType: {
    type: String,
    enum: ['search', 'view', 'like', 'save', 'follow', 'error'],
    required: true,
  },
  keyword: {
    type: String,
    default: '',
  },
  targetUrl: {
    type: String,
    default: '',
  },
  status: {
    type: String,
    enum: ['success', 'failed', 'skipped'],
    default: 'success',
  },
  details: {
    type: mongoose.Schema.Types.Mixed,
    default: {},
  },
  executedAt: {
    type: Date,
    default: Date.now,
  },
}, {
  timestamps: true,
});

automationLogSchema.index({ userId: 1, executedAt: -1 });
automationLogSchema.index({ userId: 1, actionType: 1 });

module.exports = mongoose.model('AutomationLog', automationLogSchema);
