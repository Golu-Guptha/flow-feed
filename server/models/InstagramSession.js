const mongoose = require('mongoose');

const instagramSessionSchema = new mongoose.Schema({
  userId: {
    type: mongoose.Schema.Types.ObjectId,
    ref: 'User',
    required: true,
    unique: true,
  },
  instagramUsername: {
    type: String,
    trim: true,
  },
  sessionData: {
    type: String, // Encrypted session JSON from instagrapi
    default: null,
  },
  status: {
    type: String,
    enum: ['disconnected', 'connecting', 'connected', 'awaiting_2fa', 'awaiting_challenge', 'pending', 'expired', 'failed'],
    default: 'disconnected',
  },
  lastLogin: {
    type: Date,
    default: null,
  },
  lastActivity: {
    type: Date,
    default: null,
  },
}, {
  timestamps: true,
});

// Note: userId is already indexed by unique:true above — only index status here
instagramSessionSchema.index({ status: 1 });


module.exports = mongoose.model('InstagramSession', instagramSessionSchema);
