import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config import get_db_connection

conn = get_db_connection()
cursor = conn.cursor()
for table in ['students','events','attendance']:
    try:
        cursor.execute(f"SHOW COLUMNS FROM {table}")
        rows = cursor.fetchall()
        print('\nTable:', table)
        for r in rows:
            print(' ', r)
    except Exception as e:
        print('\nTable:', table, 'ERROR:', e)
conn.close()
