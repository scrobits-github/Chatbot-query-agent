import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

conn = psycopg2.connect(
    host=os.environ["AI_DB_HOST"],
    port=os.environ["AI_DB_PORT"],
    dbname=os.environ["AI_DB_NAME"],
    user=os.environ["AI_DB_USER"],
    password=os.environ["AI_DB_PASSWORD"],
)
cur = conn.cursor()
cur.execute("SELECT current_user, current_database();")
print("OK:", cur.fetchone())
cur.execute("SELECT COUNT(*) FROM public.dashboard_widgets;")
print("widgets count:", cur.fetchone()[0])
cur.close()
conn.close()