from flask import Flask, request, jsonify
import os
import json
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)

# ===============================
# INISIALISASI FIREBASE DARI ENV VAR
# ===============================
# Ambil JSON dari Environment Variable
cred_json = os.environ.get("SERVICE_ACCOUNT_JSON")
if not cred_json:
    raise Exception("Environment variable SERVICE_ACCOUNT_JSON tidak ditemukan!")

cred_dict = json.loads(cred_json)

if not firebase_admin._apps:
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)

db_firebase = firestore.client()

# ===============================
# USERS FUNCTIONS
# ===============================
def load_users():
    try:
        users_ref = db_firebase.collection("users")
        users = [doc.to_dict() for doc in users_ref.stream()]
        return {"users": users}
    except Exception as e:
        print("Error load_users:", e)
        return {"users": []}

def save_user(user_data):
    try:
        db_firebase.collection("users").document(user_data["username"]).set(user_data)
    except Exception as e:
        print("Error save_user:", e)
        raise e

# ===============================
# MESSAGES FUNCTIONS
# ===============================
def load_messages():
    try:
        msgs_ref = db_firebase.collection("messages")
        messages = [doc.to_dict() for doc in msgs_ref.stream()]
        return {"messages": messages}
    except Exception as e:
        print("Error load_messages:", e)
        return {"messages": []}

def save_message(msg_data):
    try:
        db_firebase.collection("messages").add(msg_data)
    except Exception as e:
        print("Error save_message:", e)

# ===============================
# ROUTES
# ===============================
@app.route("/")
def home():
    return """
<h1>Mini WhatsApp</h1>

<h2>Register</h2>
<form action="/register" method="post">
  <input name="username" placeholder="username" required><br>
  <input name="password" type="password" placeholder="password" required><br>
  <button type="submit">Register</button>
</form>

<h2>Login</h2>
<form action="/login" method="post">
  <input name="username" placeholder="username" required><br>
  <input name="password" type="password" placeholder="password" required><br>
  <button type="submit">Login</button>
</form>
"""

@app.route("/register", methods=["POST"])
def register():
    try:
        username = request.form.get("username")
        password = request.form.get("password")

        if not username or not password:
            return "Username atau password kosong <br><a href='/'>kembali</a>"

        data = load_users()
        for u in data.get("users", []):
            if u.get("username") == username:
                return "Username sudah ada <br><a href='/'>kembali</a>"

        save_user({"username": username, "password": password})
        return "Register berhasil <br><a href='/'>Login</a>"
    except Exception as e:
        print("Error register:", e)
        return "Internal Server Error"

@app.route("/login", methods=["POST"])
def login():
    try:
        username = request.form.get("username")
        password = request.form.get("password")

        data = load_users()
        for u in data.get("users", []):
            if u.get("username") == username and u.get("password") == password:
                friends = [
                    x.get("username")
                    for x in data.get("users", [])
                    if x.get("username") != username
                ]

                html = f"<h2>Halo {username}</h2><h3>Teman:</h3>"
                for f in friends:
                    html += f"<p><a href='/chat/{username}/{f}'>{f}</a></p>"

                return html

        return "Login gagal <br><a href='/'>kembali</a>"
    except Exception as e:
        print("Error login:", e)
        return "Internal Server Error"

@app.route("/chat/<user>/<friend>")
def chat(user, friend):
    return f"""
<h2>Chat {user} - {friend}</h2>

<input id='msg'>
<button onclick='send()'>Kirim</button>

<div id='chat'></div>

<script>
function load(){{
    fetch('/messages?user={user}&friend={friend}')
    .then(r=>r.json())
    .then(d=>{{   
        let html=''
        d.messages.forEach(m=>{{   
            html+=`<p><b>${{m.from || ''}}</b>: ${{m.message || ''}}</p>`
        }})
        document.getElementById("chat").innerHTML=html
    }})
}}

function send(){{
    let msg=document.getElementById("msg").value
    fetch('/send',{{
        method:'POST',
        headers:{{'Content-Type':'application/json'}},
        body:JSON.stringify({{ 
            "from":"{user}",
            "to":"{friend}",
            "message":msg
        }})
    }}).then(load)
}}

setInterval(load,1000)
load()
</script>
"""

@app.route("/send", methods=["POST"])
def send():
    try:
        data = request.json
        save_message(data)
        return jsonify({"status": "ok"})
    except Exception as e:
        print("Error send:", e)
        return jsonify({"status": "error"}), 500

@app.route("/messages")
def messages():
    try:
        user = request.args.get("user")
        friend = request.args.get("friend")

        data = load_messages()
        msgs = [
            m for m in data.get("messages", [])
            if (
                m.get("from") == user and m.get("to") == friend
            ) or (
                m.get("from") == friend and m.get("to") == user
            )
        ]

        return jsonify({"messages": msgs})
    except Exception as e:
        print("Error messages:", e)
        return jsonify({"messages": []}), 500

@app.route("/lihat_users")
def lihat_users():
    return jsonify(load_users().get("users", []))

@app.route("/lihat_messages")
def lihat_messages():
    return jsonify(load_messages().get("messages", []))

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)