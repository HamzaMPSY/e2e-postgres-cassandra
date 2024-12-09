# e2e-postgres-Cassandra

# Change data capture on Postgres using Debezium

## set up the Postgres database

Run the Following commands in your postgres database console to enable replication on the tables that you wanna capture the changes

```sql
ALTER SYSTEM SET wal_level = 'logical'

CREATE TABLE if not exists his_drugs(
    product_id uuid PRIMARY KEY,
    description VARCHAR (255) NOT NULL,
    dci_code VARCHAR (255) NOT NULL,
    dci_description VARCHAR (255) NOT NULL);


CREATE TABLE if not exists his_devices(
   product_id uuid PRIMARY KEY,
   description VARCHAR (255) NOT NULL
);


CREATE TABLE if not exists his_medicals(
   product_id uuid PRIMARY KEY,
   description VARCHAR (255) NOT NULL
);


CREATE TABLE if not exists his_blabla(
   product_id uuid PRIMARY KEY,
   description VARCHAR (255) NOT NULL
);

ALTER TABLE public.his_devices REPLICA IDENTITY FULL;
ALTER TABLE public.his_drugs REPLICA IDENTITY FULL;
ALTER TABLE public.his_medicals REPLICA IDENTITY FULL;
ALTER TABLE public.his_blabla REPLICA IDENTITY FULL;

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
CREATE KEYSPACE db_amo
WITH REPLICATION = {
   'class' : 'SimpleStrategy',
   'replication_factor' : 1
  };
use db_users;
```

2- create the regions table

```sql
CREATE TABLE his_acts (
   product_id text,
   description text,
   dci_code text,
   dci_description text,
   ts_ms TIMESTAMP,
   op text,
   PRIMARY KEY (product_id, ts_ms)
);

```
