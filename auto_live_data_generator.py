import psycopg2
from datetime import datetime, timedelta, timezone
import random
import time

import os
from dotenv import load_dotenv

# Load configurations from .env
load_dotenv(".env")

def get_db_connection():
    host = os.getenv("AI_DB_HOST")
    port = os.getenv("AI_DB_PORT", "5432")
    dbname = os.getenv("AI_DB_NAME")
    user = os.getenv("AI_DB_USER")
    password = os.getenv("AI_DB_PASSWORD")

    if not all([host, dbname, user, password]):
        raise RuntimeError("Missing required database connection environment variables (AI_DB_HOST, AI_DB_NAME, AI_DB_USER, AI_DB_PASSWORD).")

    return psycopg2.connect(
        host=host,
        port=int(port),
        dbname=dbname,
        user=user,
        password=password
    )

def auto_generate_telemetry():
    print("====================================================")
    print("🌟 INFI-IOT AUTO LIVE TELEMETRY GENERATOR STARTED 🌟")
    print("   Watching database for newly created variables... ")
    print("====================================================")
    
    while True:
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            
            # 1. Fetch all variables from devices_variabledir
            cur.execute("SELECT id, variable_name FROM devices_variabledir")
            variables = cur.fetchall()
            
            for var_id, var_name in variables:
                # 2. Determine realistic value ranges based on name
                name_lower = var_name.lower()
                if "temp" in name_lower:
                    val_min, val_max = 22.0, 28.5
                elif "press" in name_lower:
                    val_min, val_max = 950.0, 1020.0
                elif "moist" in name_lower or "hum" in name_lower:
                    val_min, val_max = 40.0, 75.0
                elif "light" in name_lower or "switch" in name_lower or "lock" in name_lower or "state" in name_lower:
                    val_min, val_max = 0.0, 1.0
                else:
                    val_min, val_max = 10.0, 90.0

                # 3. Check if this variable has ANY readings in devices_data
                cur.execute("SELECT COUNT(*) FROM devices_data WHERE variable_id_id = %s", (var_id,))
                count = cur.fetchone()[0]
                
                # 4. If count is 0, backfill 15 historical points
                if count == 0:
                    print(f"\n✨ [NEW VARIABLE DETECTED] ID: {var_id} | Name: '{var_name}'")
                    print(f"   Backfilling 15 historical data points automatically...")
                    base_time = datetime.now(timezone(timedelta(hours=5, minutes=30)))
                    for i in range(15):
                        timestamp = base_time - timedelta(minutes=i * 10)
                        if val_min == 0.0 and val_max == 1.0:
                            value = float(random.choice([0, 1]))
                        else:
                            value = round(random.uniform(val_min, val_max), 2)
                        
                        cur.execute(
                            "INSERT INTO devices_data (value, timestamp, variable_id_id) VALUES (%s, %s, %s)",
                            (value, timestamp, var_id)
                        )
                    conn.commit()
                    print(f"✅ Successfully backfilled history for '{var_name}'!")
                
                # 5. In all cases, insert a fresh current live reading
                timestamp = datetime.now(timezone(timedelta(hours=5, minutes=30)))
                if val_min == 0.0 and val_max == 1.0:
                    value = float(random.choice([0, 1]))
                else:
                    value = round(random.uniform(val_min, val_max), 2)
                
                cur.execute(
                    "INSERT INTO devices_data (value, timestamp, variable_id_id) VALUES (%s, %s, %s)",
                    (value, timestamp, var_id)
                )
                conn.commit()
            
            cur.close()
            conn.close()
            
        except Exception as e:
            print("Error in generator loop:", e)
            
        # Check database and insert data every 3 seconds
        time.sleep(3)

if __name__ == "__main__":
    auto_generate_telemetry()
