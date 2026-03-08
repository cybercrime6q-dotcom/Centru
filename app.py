from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, firestore
from werkzeug.security import generate_password_hash, check_password_hash
import os
import time
import sys

app = Flask(__name__)

# ===============================
# FIREBASE INIT
# ===============================

db = None

try:

    possible_paths = [
        "/etc/secrets/firebase_key.json",
        "/run/secrets/firebase_key.json",
        "firebase_key.json"
    ]

    cred_path = None

    for p in possible_paths:
        if os.path.exists(p):
            cred_path = p
            break

    if not cred_path:
        raise Exception("firebase_key.json tidak ditemukan")

    if not firebase_admin._apps:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)

    db = firestore.client()

    print("Firebase connected", file=sys.stderr)

except Exception as e:

    print("Firebase ERROR:", e, file=sys.stderr)

# ===============================
# USER FUNCTIONS
# ===============================

def load_users():

    if not db:
        return {"users": []}

    users = db.collection("users").stream()

    return {
        "users": [u.to_dict() for u in users]
    }


def save_user(data):

    if not db:
        return

    db.collection("users").document(data["username"]).set(data)

# ===============================
# MESSAGE FUNCTIONS
# ===============================

def load_messages(user, friend):

    if not db:
        return {"messages": []}

    msgs = db.collection("messages")\
        .order_by("time")\
        .limit(100)\
        .stream()

    messages = []

    for m in msgs:

        d = m.to_dict()

        if (
            (d["from"] == user and d["to"] == friend)
            or
            (d["from"] == friend and d["to"] == user)
        ):
            messages.append(d)

    return {"messages": messages}


def save_message(msg):

    if not db:
        return

    msg["time"] = int(time.time())

    db.collection("messages").add(msg)

# ===============================
# HOME
# ===============================

@app.route("/")
def home():

    return """
<h1>Mini WhatsApp</h1>

<h2>Register</h2>
<form action="/register" method="post">
<input name="username" placeholder="username"><br>
<input name="password" type="password"><br>
<button>Register</button>
</form>

<h2>Login</h2>
<form action="/login" method="post">
<input name="username"><br>
<input name="password" type="password"><br>
<button>Login</button>
</form>
"""

# ===============================
# REGISTER
# ===============================

@app.route("/register", methods=["POST"])
def register():

    username = request.form.get("username")
    password = request.form.get("password")

    users = load_users()

    for u in users["users"]:

        if u["username"] == username:
            return "Username sudah ada"

    hashed = generate_password_hash(password)

    save_user({
        "username": username,
        "password": hashed
    })

    return "Register berhasil <br><a href='/'>Login</a>"

# ===============================
# LOGIN
# ===============================

@app.route("/login", methods=["POST"])
def login():

    username = request.form.get("username")
    password = request.form.get("password")

    users = load_users()

    for u in users["users"]:

        if u["username"] == username and \
           check_password_hash(u["password"], password):

            friends = [
                x["username"]
                for x in users["users"]
                if x["username"] != username
            ]

            html = f"<h2>Halo {username}</h2>"
            html += "<h3>Teman:</h3>"

            for f in friends:
                html += f"<p><a href='/chat/{username}/{f}'>{f}</a></p>"

            return html

    return "Login gagal"

# ===============================
# CHAT PAGE
# ===============================

@app.route("/chat/<user>/<friend>")
def chat(user, friend):

    return f"""

<h2>Chat {user} - {friend}</h2>

<div id="chat" style="
height:400px;
overflow:auto;
border:1px solid #ccc;
padding:10px
"></div>

<br>

<input id="msg" style="width:80%">
<button onclick="send()">Kirim</button>

<script>

function load(){{

fetch('/messages?user={user}&friend={friend}')
.then(r=>r.json())
.then(d=>{{

let html=""

d.messages.forEach(m=>{{

if(m.from=="{user}"){{

html+=`
<div style="text-align:right">
<span style="background:#dcf8c6;
padding:8px;
border-radius:8px">
${{m.message}}
</span>
</div>
`

}}else{{

html+=`
<div style="text-align:left">
<span style="background:#eee;
padding:8px;
border-radius:8px">
${{m.message}}
</span>
</div>
`

}}

}})

document.getElementById("chat").innerHTML=html

}})

}}

function send(){{

let msg=document.getElementById("msg").value

fetch('/send',{{

method:'POST',

headers:{{

'Content-Type':'application/json'

}},

body:JSON.stringify({{

from:"{user}",
to:"{friend}",
message:msg

}})

}})

document.getElementById("msg").value=""

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

    save_message(data)

    return jsonify({"status":"ok"})

# ===============================
# GET MESSAGES
# ===============================

@app.route("/messages")
def messages():

    user = request.args.get("user")
    friend = request.args.get("friend")

    return jsonify(load_messages(user, friend))

# ===============================
# RUN
# ===============================

if __name__ == "__main__":

    port = int(os.environ.get("PORT",5000))

    app.run(host="0.0.0.0", port=port)