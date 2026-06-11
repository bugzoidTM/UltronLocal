import sqlite3
conn = sqlite3.connect('data/ultron.db')
print(conn.execute("SELECT status FROM learned_skills WHERE name='chat-intent-greeting'").fetchall())
