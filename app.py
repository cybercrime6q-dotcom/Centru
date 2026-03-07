from flask import Flask, request, jsonify
from flask_cors import CORS
import os
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)
CORS(app)  # agar bisa diakses dari browser frontend

# ===============================
# Inisialisasi Firebase
# ===============================
cred = credentials.Certificate("firebase-key.json")
firebase_admin.initialize_app(cred)
firestore_db = firestore.client()  # Gunakan nama berbeda supaya tidak bentrok

# ===============================
# ROUTE HOME
# ===============================
@app.route("/")
def home():
    return """
<h1>Mini WhatsApp (Firebase)</h1>

<h2>Register</h2>
<form action="/register" method="post">
<input name="username" placeholder="username"><br>
<input name="password" type="password" placeholder="password"><br>
<button>Register</button>
</form>

<h2>Login</h2>
<form action="/login" method="post">
<input name="username" placeholder="username"><br>
<input name="password" type="password" placeholder="password"><br>
<button>Login</button>
</form>
"""

# ===============================
# REGISTER
# ===============================
@app.route("/register", methods=["POST"])
def register():
    username = request.form["username"]
    password = request.form["password"]

    user_ref = firestore_db.collection("users").document(username)
    if user_ref.get().exists:
        return "Username sudah ada <br><a href='/'>kembali</a>"

    user_ref.set({
        "username": username,
        "password": password
    })

    return "Register berhasil <br><a href='/'>Login</a>"

# ===============================
# LOGIN
# ===============================
@app.route("/login", methods=["POST"])
def login():
    username = request.form["username"]
    password = request.form["password"]

    user_ref = firestore_db.collection("users").document(username)
    user_doc = user_ref.get()
    if user_doc.exists and user_doc.to_dict()["password"] == password:
        # ambil daftar teman (user lain)
        users = firestore_db.collection("users").stream()
        friends = [u.to_dict()["username"] for u in users if u.to_dict()["username"] != username]

        html = f"<h2>Halo {username}</h2><h3>Teman:</h3>"
        for f in friends:
            html += f"<p><a href='/chat/{username}/{f}'>{f}</a></p>"
        return html

    return "Login gagal <br><a href='/'>kembali</a>"

# ===============================
# CHAT PAGE
# ===============================
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
html+=`<p><b>${{m.from}}</b>: ${{m.message}}</p>`
}})
document.getElementById("chat").innerHTML=html
}})
}}

function send(){{
let msg = document.getElementById("msg").value
fetch('/send', {{
method:'POST',
headers:{{'Content-Type':'application/json'}},
body: JSON.stringify({{
"from":"{user}",
"to":"{friend}",
"message": msg
}})
}}).then(load)
}}

setInterval(load,1000)
load()
</script>
"""

# ===============================
# SEND MESSAGE
# ===============================
@app.route("/send", methods=["POST"])
def send():
    data = request.json
    firestore_db.collection("messages").add({
        "from": data["from"],
        "to": data["to"],
        "message": data["message"]
    })
    return jsonify({"status":"ok"})

# ===============================
# GET MESSAGES
# ===============================
@app.route("/messages")
def messages():
    user = request.args.get("user")
    friend = request.args.get("friend")

    messages_ref = firestore_db.collection("messages").stream()
    msgs = [
        {"from": m.to_dict()["from"], "to": m.to_dict()["to"], "message": m.to_dict()["message"]}
        for m in messages_ref
        if (m.to_dict()["from"] == user and m.to_dict()["to"] == friend)
        or (m.to_dict()["from"] == friend and m.to_dict()["to"] == user)
    ]

    return jsonify({"messages": msgs})

# ===============================
# RUN APP
# ===============================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)