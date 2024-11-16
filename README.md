# e2e-postgres-Cassandra

# Change data capture on Postgres using Debezium

## set up the Postgres database

Run the Following commands in your postgres database console to enable replication on the tables that you wanna capture the changes

```sql
ALTER TABLE SCHEMA_NAME.TABLE_NAME REPLICA IDENTITY FULL;q
```

## set up debezium connector to listen to the postgres database

````console
$ curl -i -X POST -H "Accept:application/json" -H "Content-type:application/json" 127.0.0.1:8083/connectors/ --data "@debezium/debezium-connector.json"
```s
````
