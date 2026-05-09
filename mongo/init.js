db = db.getSiblingDB("engagement");

db.createCollection("support_tickets");
db.support_tickets.createIndex({ ticket_id: 1 }, { unique: true });
db.support_tickets.createIndex({ customer_id: 1, opened_at: -1 });

db.createCollection("customer_events");
db.customer_events.createIndex({ event_id: 1 }, { unique: true });
db.customer_events.createIndex({ customer_id: 1, event_ts: -1 });

db.createCollection("debezium_signal");
db.debezium_signal.createIndex({ id: 1 }, { unique: true });
