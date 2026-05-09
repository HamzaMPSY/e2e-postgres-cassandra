db = db.getSiblingDB("engagement");

if (!db.getCollectionNames().includes("debezium_signal")) {
  db.createCollection("debezium_signal");
}
db.debezium_signal.createIndex({ id: 1 }, { unique: true });
