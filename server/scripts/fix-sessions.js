require('dotenv').config();
const mongoose = require('mongoose');

async function main() {
  await mongoose.connect(process.env.MONGODB_URI);
  console.log('Connected to MongoDB');

  // Clear all pending/connecting sessions so app shows Disconnected
  const result = await mongoose.connection.db.collection('instagramsessions').updateMany(
    { status: { $in: ['pending', 'connecting', 'failed'] } },
    { $set: { status: 'disconnected', sessionData: null } }
  );
  console.log('Reset', result.modifiedCount, 'stale session(s) to disconnected');

  await mongoose.disconnect();
  console.log('Done. Reload the app - it will now show Disconnected.');
}

main().catch(e => { console.error(e); process.exit(1); });
