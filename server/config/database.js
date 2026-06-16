const mongoose = require('mongoose');

const MONGODB_URI = process.env.MONGODB_URI || 'mongodb://localhost:27017/insta-feed';

const MONGO_OPTS = {
  serverSelectionTimeoutMS: 20000,
  connectTimeoutMS:         20000,
  socketTimeoutMS:          60000,
  heartbeatFrequencyMS:     10000,   // ping every 10s — keeps Atlas connection alive
  minPoolSize:              1,
  maxIdleTimeMS:            45000,
  retryWrites:              true,
  retryReads:               true,
};

async function connectDB() {
  try {
    await mongoose.connect(MONGODB_URI, MONGO_OPTS);
    console.log('✅ Connected to MongoDB Atlas');
  } catch (err) {
    console.error('❌ MongoDB connection error:', err.message);
    process.exit(1);
  }
}

mongoose.connection.on('disconnected', () => {
  console.warn('⚠️  MongoDB disconnected — will reconnect automatically');
});

mongoose.connection.on('reconnected', () => {
  console.log('✅ MongoDB reconnected');
});

mongoose.connection.on('error', (err) => {
  console.error('❌ MongoDB error:', err.message);
});

module.exports = { connectDB };
