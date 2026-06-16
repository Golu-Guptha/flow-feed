/**
 * reset-pending-sessions.js
 * Run once to clear stale 'pending'/'connecting' Instagram sessions so they
 * can be reconnected cleanly.
 *
 * Usage:  node scripts/reset-pending-sessions.js
 */
require('dotenv').config({ path: require('path').join(__dirname, '../.env') });
const mongoose = require('mongoose');

const SESSION_SCHEMA = new mongoose.Schema({}, { strict: false });
const InstagramSession = mongoose.model('InstagramSession', SESSION_SCHEMA, 'instagramsessions');

async function main() {
  await mongoose.connect(process.env.MONGODB_URI);
  console.log('✅ Connected to MongoDB');

  const result = await InstagramSession.updateMany(
    { status: { $in: ['pending', 'connecting', 'failed'] } },
    { $set: { status: 'disconnected', sessionData: null } }
  );

  console.log(`🔄 Reset ${result.modifiedCount} session(s) to 'disconnected'`);
  await mongoose.disconnect();
  console.log('Done. You can now reconnect your Instagram account in the app.');
}

main().catch(e => { console.error(e); process.exit(1); });
