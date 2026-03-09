# ===============================
# Mini WhatsApp Level 4 - Flask + Firebase (Secret Files)
# ===============================

from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, firestore, storage
from werkzeug.security import generate_password_hash, check_password_hash
import time, sys, os

app = Flask(__name__)
db = None
bucket = None
online_users = set()

# ===============================
# FIREBASE INIT
# ===============================
try:
    # Gunakan path Secret Files
    cred_path = "/etc/secrets/firebase_key.json"  # <-- Secret Files
    if not firebase_admin._apps:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred, {
            'storageBucket': 'data-base-d7fda.appspot.com'  # <-- bucket project kamu
        })
    db = firestore.client()
    bucket = storage.bucket()
    print(f"Firebase connected using {cred_path}", file=sys.stderr)
except Exception as e:
    print("Firebase ERROR:", e, file=sys.stderr)

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

def load_messages(user,friend):
    if not db: return {"messages":[]}
    try:
        msgs = db.collection("messages").order_by("time").limit(100).stream()
        messages=[]
        for m in msgs:
            d=m.to_dict()
            if (d.get("from")==user and d.get("to")==friend) or (d.get("from")==friend and d.get("to")==user):
                messages.append(d)
        return {"messages":messages}
    except Exception as e:
        print("load_messages error:", e, file=sys.stderr)
        return {"messages":[]}

def save_message(msg):
    if not db: return
    try:
        msg["time"]=int(time.time())
        db.collection("messages").add(msg)
    except Exception as e:
        print("save_message error:", e, file=sys.stderr)

# ===============================
# HOME
# ===============================
@app.route("/")
def home():
    return """
<!DOCTYPE html>
<html>
<head>
<title>Mini WhatsApp Level 4</title>
<style>
body{font-family:Arial,sans-serif;background:#f0f2f5;margin:0;padding:20px;}
h1{text-align:center;color:#075E54;}
form{background:#fff;padding:20px;border-radius:8px;width:300px;margin:20px auto;}
input{width:90%;padding:8px;margin:5px 0;border-radius:4px;border:1px solid #ccc;}
button{width:100%;padding:10px;background:#25D366;border:none;color:#fff;font-weight:bold;border-radius:5px;cursor:pointer;}
button:hover{background:#128C7E;}
a{color:#075E54;}
</style>
</head>
<body>
<h1>Mini WhatsApp Level 4</h1>
<h2>Register</h2>
<form action="/register" method="post">
<input name="username" placeholder="Username" required><br>
<input name="password" type="password" placeholder="Password" required><br>
<button>Register</button>
</form>
<h2>Login</h2>
<form action="/login" method="post">
<input name="username" placeholder="Username" required><br>
<input name="password" type="password" placeholder="Password" required><br>
<button>Login</button>
</form>
</body>
</html>
"""

# ===============================
# REGISTER
# ===============================
@app.route("/register",methods=["POST"])
def register():
    username = request.form.get("username")
    password = request.form.get("password")
    if not username or not password:
        return "Username/password kosong"
    users = load_users()
    if any(u.get("username")==username for u in users["users"]):
        return "Username sudah ada"
    hashed = generate_password_hash(password)
    save_user({"username":username,"password":hashed})
    return "Register berhasil"

# ===============================
# LOGIN
# ===============================
@app.route("/login",methods=["POST"])
def login():
    username = request.form.get("username")
    password = request.form.get("password")
    if not username or not password:
        return "Username/password kosong"
    users = load_users()
    for u in users["users"]:
        if u.get("username")==username and check_password_hash(u.get("password"), password):
            online_users.add(username)
            friends=[{"username":x["username"],"online":x["username"] in online_users} for x in users["users"] if x["username"]!=username]
            html=f"""
<!DOCTYPE html>
<html>
<head>
<title>Dashboard {username}</title>
<style>
body{{margin:0;font-family:Arial,sans-serif;}}
.sidebar{{width:250px;background:#075E54;color:#fff;height:100vh;float:left;padding:10px;}}
.content{{margin-left:260px;padding:20px;}}
.friend{{padding:8px;margin:5px 0;border-radius:5px;background:#128C7E;cursor:pointer;}}
.friend:hover{{background:#25D366;}}
.online{{color:#0f0;font-weight:bold;}}
.offline{{color:#888;font-weight:bold;}}
</style>
</head>
<body>
<div class="sidebar"><h3>Teman</h3>
"""
            for f in friends:
                status_class="online" if f["online"] else "offline"
                html+=f"<div class='friend'><a href='/chat/{username}/{f['username']}' style='color:white;text-decoration:none;'>{f['username']} <span class='{status_class}'>●</span></a></div>"
            html+="""</div>
<div class="content"><h2>Pilih teman untuk chat</h2></div>
</body>
</html>"""
            return html
    return "Login gagal"

# ===============================
# CHAT
# ===============================
@app.route("/chat/<user>/<friend>")
def chat(user,friend):
    return r"""
<!DOCTYPE html>
<html>
<head>
<title>Chat {user} - {friend}</title>
<style>
body{font-family:Arial,sans-serif;background:#ece5dd;margin:0;padding:20px;}
#chat{height:400px;overflow:auto;border:1px solid #ccc;padding:10px;background:#fff;border-radius:8px;}
.message-left{text-align:left;margin:5px;}
.message-right{text-align:right;margin:5px;}
.bubble-left{background:#fff;padding:8px;border-radius:10px;display:inline-block;max-width:70%;}
.bubble-right{background:#dcf8c6;padding:8px;border-radius:10px;display:inline-block;max-width:70%;}
#msg{width:50%;padding:8px;border-radius:5px;border:1px solid #ccc;}
#dropzone{width:30%;height:40px;border:2px dashed #128C7E;border-radius:5px;line-height:40px;text-align:center;color:#128C7E;margin-left:10px;display:inline-block;cursor:pointer;}
button{padding:8px 12px;background:#25D366;border:none;color:#fff;border-radius:5px;cursor:pointer;}
button:hover{background:#128C7E;}
</style>
</head>
<body>
<h2>Chat {user} - {friend}</h2>
<div id="chat"></div><br>
<input id="msg" placeholder="Ketik pesan...">
<div id="dropzone">Drop file/gambar di sini</div>
<button onclick="send()">Kirim</button>

<script>
let file_to_send=null;
let dropzone=document.getElementById('dropzone');
dropzone.addEventListener('dragover', e=>{ e.preventDefault(); dropzone.style.background="#25D366"; });
dropzone.addEventListener('dragleave', e=>{ e.preventDefault(); dropzone.style.background="transparent"; });
dropzone.addEventListener('drop', e=>{ e.preventDefault(); dropzone.style.background="transparent"; file_to_send=e.dataTransfer.files[0]; dropzone.textContent=file_to_send.name; });

function load() {
    fetch('/messages?user={user}&friend={friend}')
    .then(r=>r.json())
    .then(d=>{
        let html="";
        d.messages.forEach(m=>{
            if(m.from=="{user}") {
                if(m.file){ html+=`<div class='message-right'><span class='bubble-right'><a href='${m.file}' target='_blank'>${m.file}</a><br>${m.message}</span></div>`; }
                else{ html+=`<div class='message-right'><span class='bubble-right'>${m.message}</span></div>`; }
            } else {
                if(m.file){ html+=`<div class='message-left'><span class='bubble-left'><a href='${m.file}' target='_blank'>${m.file}</a><br>${m.message}</span></div>`; }
                else{ html+=`<div class='message-left'><span class='bubble-left'>${m.message}</span></div>`; }
            }
        });
        document.getElementById("chat").innerHTML=html;
        document.getElementById("chat").scrollTop=document.getElementById("chat").scrollHeight;
        if(Notification.permission==="granted"){
            d.messages.forEach(m=>{ if(m.from!="{user}") new Notification("Pesan baru dari "+m.from,{body:m.message}); });
        }
    });
}

function send() {
    let msg=document.getElementById("msg").value;
    let formData=new FormData();
    formData.append("from","{user}");
    formData.append("to","{friend}");
    formData.append("message",msg);
    if(file_to_send){ formData.append("file",file_to_send); file_to_send=null; dropzone.textContent="Drop file/gambar di sini"; }
    fetch('/send_file',{method:'POST',body:formData});
    document.getElementById("msg").value="";
}

if(Notification.permission!=="granted") Notification.requestPermission();
setInterval(load,1000);
load();
</script>
</body>
</html>
"""

# ===============================
# SEND FILE
# ===============================
@app.route("/send_file",methods=["POST"])
def send_file():
    try:
        from_user=request.form.get("from")
        to_user=request.form.get("to")
        msg_text=request.form.get("message")
        f=request.files.get("file")
        file_url=None
        if f and allowed_file(f.filename):
            unique_name = f"{int(time.time())}_{f.filename}"
            blob = bucket.blob(unique_name)
            blob.upload_from_file(f.stream, content_type=f.content_type)
            blob.make_public()
            file_url = blob.public_url
        msg = {"from":from_user,"to":to_user,"message":msg_text}
        if file_url: msg["file"]=file_url
        save_message(msg)
        return jsonify({"status":"ok","file_url":file_url})
    except Exception as e:
        return jsonify({"status":"error","msg":str(e)})

# ===============================
# MESSAGES
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
    port=int(os.environ.get("PORT",5000))
    app.run(host="0.0.0.0", port=port)