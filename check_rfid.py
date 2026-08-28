import sys
from config import get_db_connection

if len(sys.argv) < 2:
    print("Usage: python check_rfid.py <rfid_value>")
    sys.exit(1)

rfid = sys.argv[1]
print(f"Looking up RFID (raw): {repr(rfid)}")

conn = get_db_connection()
cur = conn.cursor(dictionary=True)
cur.execute("SELECT * FROM students WHERE student_id = %s", (rfid,))
row = cur.fetchone()
conn.close()

if row:
    print("FOUND:")
    for k, v in row.items():
        print(f"  {k}: {repr(v)}")
else:
    print("NOT FOUND")
