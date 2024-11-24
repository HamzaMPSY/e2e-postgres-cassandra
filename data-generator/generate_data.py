import random
import time
import uuid

import psycopg2
from faker import Faker
from loguru import logger
from sqlalchemy import create_engine


class DBConnection:
    """TODO: add docstring to this class"""

    def __init__(self, host, port, dbname, user, password):
        self.engine = create_engine(
            f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{dbname}")

        self.con = psycopg2.connect(
            dbname=dbname, user=user, password=password, host=host, port=port)

    def execute(self, query: str, params: dict):
        """Methode that take query and dict of parameters and parse the query then execute

        Args:
            query (str): query query with parameters
            params (dict): dict of paramters to parse

        Returns:
            List: List of all records or None if it's a DDL query
        """
        parsed_query = self.parse(query=query, params=params)
        # logger.info("Executing Query: " + parsed_query, level=2)
        # open the cursor
        cur = self.con.cursor()
        try:
            cur.execute(parsed_query)
            if cur.description is not None:
                # It's a SELECT query (or any other query that returns rows)
                data = cur.fetchall()
            else:
                # It's a DDL or DML query that does not return rows
                data = None
            self.con.commit()
        except (psycopg2.ProgrammingError, psycopg2.DatabaseError) as e:
            logger.exception("Error executing query")
            self.con.rollback()
            data = None
        finally:
            cur.close()

        return data

    def parse(self, query: str, params: dict) -> str:
        """Method that will take a sql query and replace all parameters 
        with the corresponding value from the dictionary

        Args:
            query (str): sql query
            params (dict): dict of parameters

        Returns:
            str: parsed query
        """
        for key, value in params.items():
            if value['type'] in ('schema', 'table', 'column'):
                query = query.replace(':' + key, value['value'])
            elif value['type'] == 'value':
                if value['value'] is None:
                    query = query.replace(':' + key, "NULL")
                elif isinstance(value['value'], int):
                    query = query.replace(':' + key, str(value['value']))
                else:
                    query = query.replace(':' + key, f"'{value['value']}'")
            else:
                raise ValueError(f"Unknown parameter type: {value['type']}")
        return query


if __name__ == "__main__":
    host = 'postgres'
    port = 5432
    username = 'postgres'
    db_name = 'postgres'
    password = 'nidal'

    connection = DBConnection(
        user=username,
        password=password,
        dbname=db_name,
        host=host,
        port=port
    )

    fake = Faker()

    # create table if not exists already
    table_creation_queries = [
        """CREATE table if not exists users (
                user_id uuid PRIMARY KEY,
                username VARCHAR ( 50 ) UNIQUE NOT NULL,
                genre varchar(1) ,
                region_id uuid
            )""",
        """CREATE TABLE if not exists regions(
                region_id uuid PRIMARY KEY,
                region_name VARCHAR (255) UNIQUE NOT NULL
        )"""
    ]

    queries = {
        'users': {
            'insert': '''insert into users values(:uuid, :username, :genre , :region_id)''',
            'update': '''update users set username  = :username where user_id = :uuid''',
            'delete': '''delete from users where user_id = :uuid''',
        },
        'regions': {
            'insert': '''insert into regions values(:uuid, :region_name)'''
        }
    }

    for query in table_creation_queries:
        connection.execute(query=query,  params={})

    while True:
        for table in queries.keys():
            if table == 'regions':
                query = queries[table]['insert']
                params = {
                    "uuid": {
                        "type": 'value',
                        "value": str(uuid.uuid4())
                    },
                    "region_name": {
                        "type": 'value',
                        "value": fake.city()
                    }
                }
                connection.execute(query=query, params=params)
            if table == 'users':
                query = queries[table]['insert']
                params = {
                    "uuid": {
                        "type": 'value',
                        "value": str(uuid.uuid4())
                    },
                    "username": {
                        "type": 'value',
                        "value": fake.name()
                    },
                    "genre": {
                        "type": 'value',
                        "value": random.choice(['M', 'F'])
                    },
                    "region_id": {
                        "type": 'value',
                        "value": str(connection.execute(query="SELECT region_id FROM regions ORDER BY RANDOM() LIMIT 1", params={})[0][0])
                    }
                }
                connection.execute(query=query, params=params)

                query = queries[table]['update']
                params = {
                    "uuid": {
                        "type": 'value',
                        "value": str(connection.execute(query="SELECT user_id FROM users ORDER BY RANDOM() LIMIT 1", params={})[0][0])
                    },
                    "username": {
                        "type": 'value',
                        "value": fake.name()
                    },

                }
                connection.execute(query=query, params=params)
        time.sleep(600)
