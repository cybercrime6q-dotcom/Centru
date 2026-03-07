import sqlite3

# buka database chat.db
conn = sqlite3.connect("chat.db")
db = conn.cursor()

# --- Lihat semua users ---
print("===== USERS =====")
db.execute("SELECT username, password FROM users")
users = db.fetchall()
for u in users:
    print(f"Username: {u[0]}, Password: {u[1]}")

# --- Lihat semua messages ---
print("\n===== MESSAGES =====")
db.execute("SELECT sender, receiver, message FROM messages ORDER BY rowid")
messages = db.fetchall()
for m in messages:
    print(f"{m[0]} -> {m[1]}: {m[2]}")

# tutup koneksi
conn.close()