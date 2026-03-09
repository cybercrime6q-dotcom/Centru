# ===============================
# Mini WhatsApp Level 4 - Flask + Firebase (Secret Files + Email)
# ===============================

from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, firestore, storage, auth
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
    cred_path = "/etc/secrets/firebase_key.json"
    if not firebase_admin._apps:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred, {
            'storageBucket': 'data-base-d7fda.appspot.com'
        })
    db = firestore.client()
    bucket = storage.bucket()
    print(f"Firebase connected using {cred_path}", file=sys.stderr)
except Exception as e:
    print("Firebase ERROR:", e, file=sys.stderr)

ALLOWED_EXTENSIONS = {'png','jpg','jpeg','gif','txt','pdf'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.',1)[1].lower() in ALLOWED_EXTENSIONS

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
<input name="email" type="email" placeholder="Email" required><br>
<input name="password" type="password" placeholder="Password" required><br>
<button>Register</button>
</form>
<h2>Login</h2>
<form action="/login" method="post">
<input name="email" type="email" placeholder="Email" required><br>
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
    email = request.form.get("email")
    password = request.form.get("password")

    if not username or not email or not password:
        return "Username/email/password kosong"

    # validasi password panjang minimal
    if len(password) < 6:
        return "Password harus minimal 6 karakter"

    try:
        # cek username sudah ada di Firestore
        existing = db.collection("users").where("username","==",username).get()
        if existing:
            return "Username sudah ada"

        # cek email sudah terdaftar di Firebase Auth
        try:
            auth.get_user_by_email(email)
            return "Email sudah terdaftar"
        except auth.UserNotFoundError:
            pass

        # buat user di Firebase Auth
        firebase_user = auth.create_user(
            email=email,
            password=password
        )

        # hash password
        hashed = generate_password_hash(password)

        # simpan user di Firestore pakai uid sebagai id
        db.collection("users").document(firebase_user.uid).set({
            "uid": firebase_user.uid,
            "username": username,
            "email": email,
            "password": hashed
        })

        return "Register berhasil 🎉"

    except Exception as e:
        print("Firebase register error:", e, file=sys.stderr)
        return f"Register gagal: {str(e)}"

# ===============================
# LOGIN
# ===============================
@app.route("/login",methods=["POST"])
def login():
    email = request.form.get("email")
    password = request.form.get("password")
    if not email or not password:
        return "Email/password kosong"

    try:
        # ambil user berdasar email
        users = db.collection("users").where("email","==",email).get()
        if not users:
            return "Login gagal"

        user = users[0].to_dict()
        if check_password_hash(user.get("password",""), password):
            username = user.get("username")
            online_users.add(username)
            return "Login berhasil"
        else:
            return "Login gagal"
    except Exception as e:
        print("Login error:", e, file=sys.stderr)
        return "Login gagal"

# ===============================
# CHAT UI dan SEND_FILE tetap sama
# ===============================
@app.route("/chat/<user>/<friend>")
def chat(user,friend):
    return r"""..."""  # kamu bisa isi bagian chat sama seperti semula

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