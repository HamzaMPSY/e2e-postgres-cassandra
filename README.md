# e2e-postgres-Cassandra

# Change data capture on Postgres using Debezium

## set up the Postgres database

Run the Following commands in your postgres database console to enable replication on the tables that you wanna capture the changes

```sql
ALTER TABLE SCHEMA_NAME.TABLE_NAME REPLICA IDENTITY FULL;
ALTER SYSTEM SET wal_level = 'logical';
```

Make sure you restart the whole project, kill processes using CRTL-C and re-run 'sudo docker compose up'

## set up debezium connector to listen to the postgres database

```console
$ curl -i -X POST -H "Accept:application/json" -H "Content-type:application/json" 127.0.0.1:8083/connectors/ --data "@debezium/debezium-connector.json"
```

## set up the Cassandra database

Run the following command to enter cassandra container and to be able to run sql commands

```console
$ sudo docker exec -it cassandra bash -c "cqlsh"
```

to set up the cassandra database to ingest data
1- create the keyspace that would hold the tables

```sql
CREATE KEYSPACE db_users
WITH REPLICATION = {
   'class' : 'SimpleStrategy',
   'replication_factor' : 1
  };
use db_users;
```

2- create the regions table

```sql
CREATE TABLE regions (
   region_id text,
   region_name text,
   ts_ms TIMESTAMP,
   op text,
   PRIMARY KEY (region_id, ts_ms)
);
```

3- create the users table

```sql
CREATE TABLE users (
   user_id text,
   username text,
   genre text,
   region text,
   ts_ms TIMESTAMP,
   op text,
   PRIMARY KEY (user_id, ts_ms)
);
```
