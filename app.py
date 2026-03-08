from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, firestore
import sys

app = Flask(__name__)

# ===============================
# FIREBASE ADMIN DENGAN SECRET FILE
# ===============================
try:
    cred_path = "/run/secrets/firebase_key.json"  # path secret file di Render
    if not firebase_admin._apps:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("✅ Firebase Admin connected", file=sys.stderr)
except Exception as e:
    print("❌ Firebase Admin ERROR:", e, file=sys.stderr)
    raise e

# ===============================
# USERS FUNCTIONS
# ===============================
def load_users():
    try:
        users_ref = db.collection("users").limit(50)
        return {"users": [doc.to_dict() for doc in users_ref.stream()]}
    except Exception as e:
        print("Error load_users:", e, file=sys.stderr)
        return {"users": []}

def save_user(user_data):
    try:
        db.collection("users").document(user_data["username"]).set(user_data)
    except Exception as e:
        print("Error save_user:", e, file=sys.stderr)
        raise e

# ===============================
# MESSAGES FUNCTIONS
# ===============================
def load_messages(user=None, friend=None):
    try:
        msgs_ref = db.collection("messages").limit(50)
        messages = [doc.to_dict() for doc in msgs_ref.stream()]
        if user and friend:
            messages = [
                m for m in messages
                if (m.get("from") == user and m.get("to") == friend) or
                   (m.get("from") == friend and m.get("to") == user)
            ]
        return {"messages": messages}
    except Exception as e:
        print("Error load_messages:", e, file=sys.stderr)
        return {"messages": []}

def save_message(msg_data):
    try:
        db.collection("messages").add(msg_data)
    except Exception as e:
        print("Error save_message:", e, file=sys.stderr)

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
        print("Error register:", e, file=sys.stderr)
        return "Internal Server Error"

@app.route("/login", methods=["POST"])
def login():
    try:
        username = request.form.get("username")
        password = request.form.get("password")
        data = load_users()
        for u in data.get("users", []):
            if u.get("username") == username and u.get("password") == password:
                friends = [x.get("username") for x in data.get("users", []) if x.get("username") != username]

                html = f"<h2>Halo {username}</h2><h3>Teman:</h3>"
                for f in friends:
                    html += f"<p><a href='/chat/{username}/{f}'>{f}</a></p>"

                html += """
<input id='msg'>
<button onclick='send()'>Kirim</button>
<div id='chat'></div>

<script>
function load(){
    fetch('/messages?user=""" + username + """&friend='+ '{{friend}}')
    .then(r=>r.json())
    .then(d=>{
        let html=''
        d.messages.forEach(m=>{
            html+=`<p><b>${m.from || ''}</b>: ${m.message || ''}</p>`
        })
        document.getElementById("chat").innerHTML=html
    })
}

function send(){
    let msg=document.getElementById("msg").value
    fetch('/send',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({
            "from":" """ + username + """ ",
            "to":"{{friend}}",
            "message":msg
        })
    }).then(load)
}

setInterval(load,3000)
load()
</script>
"""
                return html
        return "Login gagal <br><a href='/'>kembali</a>"
    except Exception as e:
        print("Error login:", e, file=sys.stderr)
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
    .then(d=>{
        let html=''
        d.messages.forEach(m=>{
            html+=`<p><b>${{m.from || ''}}</b>: ${{m.message || ''}}</p>`
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

setInterval(load,3000)
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
        print("Error send:", e, file=sys.stderr)
        return jsonify({"status": "error"}), 500

@app.route("/messages")
def messages():
    try:
        user = request.args.get("user")
        friend = request.args.get("friend")
        data = load_messages(user, friend)
        return jsonify(data)
    except Exception as e:
        print("Error messages:", e, file=sys.stderr)
        return jsonify({"messages": []}), 500

@app.route("/test_firebase")
def test_firebase():
    try:
        users = [doc.to_dict() for doc in db.collection("users").limit(1).stream()]
        return jsonify({"status": "ok", "sample_user": users})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)