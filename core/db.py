import psycopg2

DB_CONFIG = {
    "dbname": "lele",
    "user": "danny",
    "password": "Com",
    "host": "localhost",
    "port": "5432"
}

def get_connection():
    return psycopg2.connect(**DB_CONFIG)
