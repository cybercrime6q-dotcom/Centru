from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, firestore
import sys
import os

app = Flask(__name__)

# ===============================
# FIREBASE ADMIN
# ===============================
try:
    cred_path = "/run/secrets/firebase_key.json"

    if not firebase_admin._apps:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)

    db = firestore.client()
    print("Firebase connected", file=sys.stderr)

except Exception as e:
    print("Firebase ERROR:", e, file=sys.stderr)
    raise e


# ===============================
# USER FUNCTIONS
# ===============================
def load_users():
    try:
        users_ref = db.collection("users").limit(50)
        return {"users": [doc.to_dict() for doc in users_ref.stream()]}
    except Exception as e:
        print("load_users error:", e, file=sys.stderr)
        return {"users": []}


def save_user(user_data):
    try:
        db.collection("users").document(user_data["username"]).set(user_data)
    except Exception as e:
        print("save_user error:", e, file=sys.stderr)


# ===============================
# MESSAGE FUNCTIONS
# ===============================
def load_messages(user=None, friend=None):
    try:
        msgs_ref = db.collection("messages").limit(50)
        messages = [doc.to_dict() for doc in msgs_ref.stream()]

        if user and friend:
            messages = [
                m for m in messages
                if (m.get("from") == user and m.get("to") == friend)
                or (m.get("from") == friend and m.get("to") == user)
            ]

        return {"messages": messages}

    except Exception as e:
        print("load_messages error:", e, file=sys.stderr)
        return {"messages": []}


def save_message(msg):
    try:
        db.collection("messages").add(msg)
    except Exception as e:
        print("save_message error:", e, file=sys.stderr)


# ===============================
# HOME
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


# ===============================
# REGISTER
# ===============================
@app.route("/register", methods=["POST"])
def register():

    username = request.form.get("username")
    password = request.form.get("password")

    if not username or not password:
        return "Username / password kosong <br><a href='/'>kembali</a>"

    data = load_users()

    for u in data["users"]:
        if u.get("username") == username:
            return "Username sudah ada <br><a href='/'>kembali</a>"

    save_user({"username": username, "password": password})

    return "Register berhasil <br><a href='/'>Login</a>"


# ===============================
# LOGIN
# ===============================
@app.route("/login", methods=["POST"])
def login():

    username = request.form.get("username")
    password = request.form.get("password")

    data = load_users()

    for u in data["users"]:
        if u.get("username") == username and u.get("password") == password:

            friends = [
                x.get("username")
                for x in data["users"]
                if x.get("username") != username
            ]

            html = f"<h2>Halo {username}</h2>"
            html += "<h3>Teman:</h3>"

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

<input id="msg">
<button onclick="send()">Kirim</button>

<div id="chat"></div>

<script>

function load(){{

fetch('/messages?user={user}&friend={friend}')
.then(r=>r.json())
.then(d=>{{
    let html=""

    d.messages.forEach(m=>{{
        html += `<p><b>${{m["from"] || ""}}</b>: ${{m["message"] || ""}}</p>`
    }})

    document.getElementById("chat").innerHTML = html
}})

}}

function send(){{

let msg = document.getElementById("msg").value

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

setInterval(load,3000)

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

    return jsonify({"status": "ok"})


# ===============================
# GET MESSAGES
# ===============================
@app.route("/messages")
def messages():

    user = request.args.get("user")
    friend = request.args.get("friend")

    data = load_messages(user, friend)

    return jsonify(data)


# ===============================
# FIREBASE TEST
# ===============================
@app.route("/test_firebase")
def test_firebase():

    try:

        users = [
            doc.to_dict()
            for doc in db.collection("users").limit(1).stream()
        ]

        return jsonify({
            "status": "ok",
            "sample_user": users
        })

    except Exception as e:

        return jsonify({
            "status": "error",
            "msg": str(e)
        })


# ===============================
# RUN SERVER
# ===============================
if __name__ == "__main__":

    port = int(os.environ.get("PORT", 5000))

    app.run(host="0.0.0.0", port=port)