import sqlite3

# Connect to your SQLite database (or create it if it doesn't exist)
conn = sqlite3.connect('plant_watering.db')

# Create a cursor object
cursor = conn.cursor()

# Create the moisture_thresholds table
cursor.execute('''
CREATE TABLE IF NOT EXISTS moisture_thresholds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    threshold REAL NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);
''')

# Commit the changes and close the connection
conn.commit()
conn.close()

print("Table 'moisture_thresholds' created successfully.")
