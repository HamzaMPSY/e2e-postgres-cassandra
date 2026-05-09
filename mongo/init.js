db = db.getSiblingDB("engagement");

const supportTicketValidator = {
  $jsonSchema: {
    bsonType: "object",
    required: ["ticket_id", "customer_id", "priority", "status", "opened_at"],
    properties: {
      ticket_id: { bsonType: "string", minLength: 1 },
      customer_id: { bsonType: "string", minLength: 1 },
      priority: { enum: ["low", "medium", "high", "critical"] },
      status: { enum: ["open", "waiting_customer", "resolved"] },
      opened_at: { bsonType: "date" },
      sla_due_at: { bsonType: ["date", "null"] },
      closed_at: { bsonType: ["date", "null"] }
    }
  }
};

if (!db.getCollectionNames().includes("support_tickets")) {
  db.createCollection("support_tickets", {
    validator: supportTicketValidator,
    validationLevel: "strict",
    validationAction: "error"
  });
} else {
  db.runCommand({
    collMod: "support_tickets",
    validator: supportTicketValidator,
    validationLevel: "strict",
    validationAction: "error"
  });
}
db.support_tickets.createIndex({ ticket_id: 1 }, { unique: true });
db.support_tickets.createIndex({ customer_id: 1, opened_at: -1 });

db.createCollection("customer_events");
db.customer_events.createIndex({ event_id: 1 }, { unique: true });
db.customer_events.createIndex({ customer_id: 1, event_ts: -1 });

db.createCollection("debezium_signal");
db.debezium_signal.createIndex({ id: 1 }, { unique: true });
