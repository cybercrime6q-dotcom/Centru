from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, firestore, storage
from werkzeug.security import generate_password_hash, check_password_hash
import os, time, sys

app = Flask(__name__)
db = None
bucket = None
online_users = set()

# ===============================
# FIREBASE INIT (Firestore + Storage)
# ===============================
try:
    secret_paths = [
        "/etc/secrets/firebase_key.json",
        "/run/secrets/firebase_key.json",
        "firebase_key.json"
    ]
    cred_path = None
    for p in secret_paths:
        if os.path.exists(p):
            cred_path = p
            break
    if not cred_path:
        raise Exception("firebase_key.json tidak ditemukan")
    if not firebase_admin._apps:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred, {
            'storageBucket': '<NAMA_BUCKET_ANDA>.appspot.com'  # ganti sesuai bucket Firebase
        })
    db = firestore.client()
    bucket = storage.bucket()
    print(f"Firebase connected using {cred_path}", file=sys.stderr)
except Exception as e:
    print("Firebase ERROR:", e, file=sys.stderr)

# ===============================
# HELPERS
# ===============================
ALLOWED_EXTENSIONS = {'png','jpg','jpeg','gif','txt','pdf'}
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.',1)[1].lower() in ALLOWED_EXTENSIONS

def load_users():
    if not db: return {"users":[]}
    try:
        return {"users":[u.to_dict() for u in db.collection("users").stream()]}
    except Exception as e:
        print("load_users error:", e, file=sys.stderr)
        return {"users":[]}

def save_user(user_data):
    if not db: return
    try:
        db.collection("users").document(user_data["username"]).set(user_data)
    except Exception as e:
        print("save_user error:", e, file=sys.stderr)

def load_messages(user, friend):
    if not db: return {"messages":[]}
    try:
        msgs = db.collection("messages").order_by("time").limit(100).stream()
        messages=[]
        for m in msgs:
            d = m.to_dict()
            if (d.get("from")==user and d.get("to")==friend) or (d.get("from")==friend and d.get("to")==user):
                messages.append(d)
        return {"messages": messages}
    except Exception as e:
        print("load_messages error:", e, file=sys.stderr)
        return {"messages":[]}

def save_message(msg):
    if not db: return
    try:
        msg["time"] = int(time.time())
        db.collection("messages").add(msg)
    except Exception as e:
        print("save_message error:", e, file=sys.stderr)

# ===============================
# REGISTER
# ===============================
@app.route("/register", methods=["POST"])
def register():
    username = request.form.get("username")
    password = request.form.get("password")
    if not username or not password:
        return "Username/password kosong <br><a href='/'>kembali</a>"
    users = load_users()
    for u in users["users"]:
        if u.get("username") == username:
            return "Username sudah ada <br><a href='/'>kembali</a>"
    hashed = generate_password_hash(password)
    save_user({"username":username,"password":hashed})
    return "Register berhasil <br><a href='/'>Login</a>"

# ===============================
# LOGIN
# ===============================
@app.route("/login", methods=["POST"])
def login():
    username = request.form.get("username")
    password = request.form.get("password")
    if not username or not password:
        return "Username/password kosong <br><a href='/'>kembali</a>"
    users = load_users()
    for u in users["users"]:
        if u.get("username") == username and check_password_hash(u.get("password"), password):
            online_users.add(username)
            friends = [{"username":x["username"],"online":x["username"] in online_users} for x in users["users"] if x["username"]!=username]
            html = f"<h2>Halo {username}</h2><ul>"
            for f in friends:
                status = "online" if f["online"] else "offline"
                html += f"<li><a href='/chat/{username}/{f['username']}'>{f['username']} ({status})</a></li>"
            html += "</ul>"
            return html
    return "Login gagal <br><a href='/'>kembali</a>"

# ===============================
# CHAT
# ===============================
@app.route("/chat/<user>/<friend>")
def chat(user,friend):
    return f"""
<h2>Chat {user} - {friend}</h2>
<input id="msg" placeholder="Ketik pesan...">
<div id="chat"></div>
<input type="file" id="file_input">
<button onclick="send()">Kirim</button>
<script>
let file_to_send=null;
document.getElementById("file_input").addEventListener("change",e=>{{ file_to_send=e.target.files[0]; }});

function load(){{
    fetch('/messages?user={user}&friend={friend}').then(r=>r.json()).then(d=>{{
        let html="";
        d.messages.forEach(m=>{{
            if(m.from=="{user}") html+=m.file?`<div>[Me] <a href='${{m.file}}' target='_blank'>${{m.file}}</a>: ${{m.message}}</div>`:`<div>[Me]: ${{m.message}}</div>`;
            else html+=m.file?`<div>[${{m.from}}] <a href='${{m.file}}' target='_blank'>${{m.file}}</a>: ${{m.message}}</div>`:`<div>[${{m.from}}]: ${{m.message}}</div>`;
        }});
        document.getElementById("chat").innerHTML=html;
        document.getElementById("chat").scrollTop=document.getElementById("chat").scrollHeight;
    }});
}}

function send(){{
    let msg=document.getElementById("msg").value;
    let formData=new FormData();
    formData.append("from","{user}");
    formData.append("to","{friend}");
    formData.append("message",msg);
    if(file_to_send) formData.append("file", file_to_send);
    fetch('/send_file', {{method:'POST', body:formData}});
    document.getElementById("msg").value="";
    file_to_send=null;
    document.getElementById("file_input").value="";
}}

setInterval(load,1000);
load();
</script>
"""

# ===============================
# SEND FILE MESSAGE → pakai Firebase Storage
# ===============================
@app.route("/send_file", methods=["POST"])
def send_file():
    from_user = request.form.get("from")
    to_user = request.form.get("to")
    msg_text = request.form.get("message")
    f = request.files.get("file")
    file_url = None

    if f and allowed_file(f.filename):
        filename = secure_filename(f.filename)
        blob = bucket.blob(f"{int(time.time())}_{filename}")
        blob.upload_from_file(f)  # upload langsung
        blob.make_public()
        file_url = blob.public_url

    msg = {"from":from_user,"to":to_user,"message":msg_text}
    if file_url: msg["file"] = file_url
    save_message(msg)
    return jsonify({"status":"ok"})

# ===============================
# MESSAGES JSON
# ===============================
@app.route("/messages")
def messages():
    user = request.args.get("user")
    friend = request.args.get("friend")
    return jsonify(load_messages(user,friend))

# ===============================
# RUN SERVER
# ===============================
if __name__=="__main__":
    port = int(os.environ.get("PORT",5000))
    app.run(host="0.0.0.0", port=port)