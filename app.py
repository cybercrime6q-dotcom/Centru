from flask import Flask, request, jsonify
import os
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)

# ===============================
# INISIALISASI FIREBASE
# ===============================
# Pastikan file firebase_key.json ada di folder project atau gunakan Secret Render
cred = credentials.Certificate('firebase_key.json')
firebase_admin.initialize_app(cred)
db_firebase = firestore.client()

# ===============================
# USERS FUNCTIONS
# ===============================
def load_users():
    users_ref = db_firebase.collection('users')
    users = [doc.to_dict() for doc in users_ref.stream()]
    return {"users": users}

def save_user(user_data):
    db_firebase.collection('users').document(user_data['username']).set(user_data)

# ===============================
# MESSAGES FUNCTIONS
# ===============================
def load_messages():
    msgs_ref = db_firebase.collection('messages')
    messages = [doc.to_dict() for doc in msgs_ref.stream()]
    return {"messages": messages}

def save_message(msg_data):
    db_firebase.collection('messages').add(msg_data)

# ===============================
# FLASK ROUTES
# ===============================

@app.route("/")
def home():
    return """
<h1>Mini WhatsApp</h1>

<h2>Register</h2>
<form action="/register" method="post">
<input name="username" placeholder="username"><br>
<input name="password" type="password" placeholder="password"><br>
<button>Register</button>
</form>

<h2>Login</h2>
<form action="/login" method="post">
<input name="username"><br>
<input name="password" type="password"><br>
<button>Login</button>
</form>
"""

# REGISTER
@app.route("/register", methods=["POST"])
def register():
    username = request.form["username"]
    password = request.form["password"]

    data = load_users()
    for u in data["users"]:
        if u["username"] == username:
            return "Username sudah ada <br><a href='/'>kembali</a>"

    save_user({"username": username, "password": password})
    return "Register berhasil <br><a href='/'>Login</a>"

# LOGIN
@app.route("/login", methods=["POST"])
def login():
    username = request.form["username"]
    password = request.form["password"]

    data = load_users()
    for u in data["users"]:
        if u["username"] == username and u["password"] == password:
            friends = [x["username"] for x in data["users"] if x["username"] != username]

            html = f"<h2>Halo {username}</h2><h3>Teman:</h3>"
            for f in friends:
                html += f"<p><a href='/chat/{username}/{f}'>{f}</a></p>"

            return html
    return "Login gagal <br><a href='/'>kembali</a>"

# CHAT PAGE
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
.then(d=>{
let html=''
d.messages.forEach(m=>{
html+=`<p><b>${{m.from}}</b>: ${{m.message}}</p>`
})
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

# SEND MESSAGE
@app.route("/send", methods=["POST"])
def send():
    data = request.json
    save_message(data)
    return jsonify({"status":"ok"})

# GET MESSAGES
@app.route("/messages")
def messages():
    user = request.args.get("user")
    friend = request.args.get("friend")

    data = load_messages()
    msgs = [m for m in data["messages"] if (m["from"] == user and m["to"] == friend) or (m["from"] == friend and m["to"] == user)]
    return jsonify({"messages": msgs})

# API VIEW USERS
@app.route("/lihat_users")
def lihat_users():
    data = load_users()
    return jsonify(data["users"])

# API VIEW ALL MESSAGES
@app.route("/lihat_messages")
def lihat_messages():
    data = load_messages()
    return jsonify(data["messages"])

# ===============================
# RUN FLASK
# ===============================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)