from flask import Flask, request, jsonify, redirect, make_response
import firebase_admin
from firebase_admin import credentials, firestore, storage, auth
from werkzeug.security import generate_password_hash, check_password_hash
import time, sys, os, uuid

app = Flask(__name__)
db = None
bucket = None
import os
import cloudinary

cloudinary.config(
  cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
  api_key=os.getenv("CLOUDINARY_API_KEY"),
  api_secret=os.getenv("CLOUDINARY_API_SECRET")
)

# ============================
# API KEYS CONFIGURATION
# ============================
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
SUPABASE_PROJECT_ID = "dsgpad1rv"

AGORA_APP_ID = os.environ.get("AGORA_APP_ID", "YOUR_AGOR_APP_ID")
AGORA_APP_CERTIFICATE = os.environ.get("AGORA_APP_CERTIFICATE", "")

try:
    cred_path = "/etc/secrets/firebase_key.json"
    if not firebase_admin._apps:
        cred = credentials.Certificate(cred_path)
        firebase_admin.initialize_app(cred, {'storageBucket': 'data-base-d7fda.firebasestorage.app'})
    db = firestore.client()
    bucket = storage.bucket()
    print(f"Firebase connected: {cred_path}", file=sys.stderr)
except Exception as e:
    print("Firebase ERROR:", e, file=sys.stderr)

ALLOWED_EXTENSIONS = {'png','jpg','jpeg','gif','webp','bmp','txt','pdf','doc','docx',
                       'xls','xlsx','zip','rar','mp4','webm','ogg','m4a','wav','mp3',
                       'mov','avi','mkv','heic','heif'}

def allowed_file(fn):
    return '.' in fn and fn.rsplit('.',1)[1].lower() in ALLOWED_EXTENSIONS

def get_current_user(req):
    uid = req.cookies.get("uid")
    if not uid or not db: return None
    try:
        doc = db.collection("users").document(uid).get()
        return doc.to_dict() if doc.exists else None
    except: return None

def upload_to_storage(file_obj, folder="uploads"):
    ext = file_obj.filename.rsplit('.',1)[1].lower() if '.' in file_obj.filename else 'bin'
    name = f"{folder}/{int(time.time())}_{uuid.uuid4().hex[:8]}.{ext}"
    blob = bucket.blob(name)
    file_obj.stream.seek(0)
    blob.upload_from_file(file_obj.stream, content_type=file_obj.content_type or 'application/octet-stream')
    blob.make_public()
    return blob.public_url, file_obj.content_type or 'application/octet-stream'

def save_message(from_uid, to_uid, text, file_url=None, file_type=None, reply_to=None):
    if not db: return None
    try:
        chat_id = "_".join(sorted([from_uid, to_uid]))
        msg = {
            "from": from_uid, "to": to_uid,
            "message": text or "",
            "time": int(time.time()),
            "status": "sent",
            "file": file_url,
            "file_type": file_type,
            "reply_to": reply_to,
            "deleted": False
        }
        ref = db.collection("chats").document(chat_id).collection("messages").add(msg)
        db.collection("chats").document(chat_id).set({
            "participants": [from_uid, to_uid],
            "last_message": text or ("\U0001f4ce Media" if file_url else ""),
            "last_time": int(time.time()),
            "last_from": from_uid
        }, merge=True)
        db.collection("notifications").add({
            "to": to_uid, "from": from_uid,
            "message": text or "\U0001f4ce Media",
            "time": int(time.time()), "read": False
        })
        return ref[1].id
    except Exception as e:
        print("save_message error:", e, file=sys.stderr)
        return None

def load_messages(user_uid, friend_uid):
    if not db: return []
    try:
        chat_id = "_".join(sorted([user_uid, friend_uid]))
        msgs = db.collection("chats").document(chat_id).collection("messages").order_by("time").limit(200).stream()
        result = []
        for m in msgs:
            d = m.to_dict(); d["id"] = m.id
            if not d.get("deleted"):
                result.append(d)
        return result
    except Exception as e:
        print("load_messages error:", e, file=sys.stderr)
        return []

def mark_messages_read(user_uid, friend_uid):
    if not db: return
    try:
        chat_id = "_".join(sorted([user_uid, friend_uid]))
        msgs = db.collection("chats").document(chat_id).collection("messages")\
            .where("to","==",user_uid).where("status","!=","read").stream()
        for m in msgs: m.reference.update({"status": "read"})
        notifs = db.collection("notifications")\
            .where("to","==",user_uid).where("from","==",friend_uid).stream()
        for n in notifs: n.reference.update({"read": True})
    except Exception as e:
        print("mark_read error:", e, file=sys.stderr)


AUTH_PAGE = r"""<!DOCTYPE html>
<html>
<head>
<title>WaClone</title>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800;900&display=swap" rel="stylesheet">
<style>
:root{--g:#00a884;--dk:#111b21;--pn:#202c33;--bd:#2a3942;--tx:#e9edef;--st:#8696a0;--rd:#f15c6d;}
*{margin:0;padding:0;box-sizing:border-box;}
body{font-family:'Nunito',sans-serif;background:var(--dk);color:var(--tx);display:flex;align-items:center;justify-content:center;min-height:100vh;background-image:radial-gradient(circle at 20% 80%,rgba(0,168,132,.08) 0,transparent 50%),radial-gradient(circle at 80% 20%,rgba(0,168,132,.06) 0,transparent 50%);}
input{outline:none;border:none;font-family:'Nunito',sans-serif;}
button{cursor:pointer;font-family:'Nunito',sans-serif;}
.wrap{width:100%;max-width:420px;padding:20px;}
.logo{text-align:center;margin-bottom:32px;}
.logo svg{width:76px;height:76px;filter:drop-shadow(0 8px 24px rgba(0,168,132,.5));}
.logo h1{font-size:30px;font-weight:900;color:var(--g);margin-top:10px;letter-spacing:-1px;}
.logo p{color:var(--st);font-size:14px;margin-top:4px;}
.card{background:var(--pn);border-radius:20px;padding:28px;border:1px solid var(--bd);box-shadow:0 20px 60px rgba(0,0,0,.4);}
.tabs{display:flex;gap:4px;background:var(--dk);border-radius:12px;padding:4px;margin-bottom:24px;}
.tab{flex:1;padding:10px;text-align:center;border-radius:9px;font-weight:800;font-size:14px;color:var(--st);cursor:pointer;transition:.2s;}
.tab.active{background:var(--g);color:#fff;box-shadow:0 4px 12px rgba(0,168,132,.4);}
.fg{margin-bottom:14px;position:relative;}
.fg label{display:block;font-size:11px;font-weight:800;color:var(--st);margin-bottom:6px;text-transform:uppercase;letter-spacing:.8px;}
.fg input{width:100%;padding:13px 16px;border-radius:12px;font-size:15px;background:var(--dk);border:1.5px solid var(--bd);color:var(--tx);transition:.2s;}
.fg input:focus{border-color:var(--g);background:#1a2328;}
.eye{position:absolute;right:14px;bottom:13px;cursor:pointer;color:var(--st);font-size:18px;line-height:1;}
.btn{width:100%;padding:14px;background:var(--g);color:#fff;border:none;border-radius:12px;font-size:16px;font-weight:800;transition:.2s;margin-top:6px;}
.btn:hover{background:#009070;transform:translateY(-1px);box-shadow:0 8px 20px rgba(0,168,132,.35);}
.btn:disabled{opacity:.6;transform:none;}
.divider{display:flex;align-items:center;gap:12px;margin:16px 0;}
.divider span{color:var(--st);font-size:12px;font-weight:700;white-space:nowrap;}
.divider::before,.divider::after{content:'';flex:1;height:1px;background:var(--bd);}
.gbtn{width:100%;padding:13px;background:var(--dk);color:var(--tx);border:1.5px solid var(--bd);border-radius:12px;font-size:15px;font-weight:800;transition:.2s;display:flex;align-items:center;justify-content:center;gap:10px;}
.gbtn:hover{border-color:var(--g);background:#1a2328;}
.gbtn svg{width:22px;height:22px;flex-shrink:0;}
.pf{display:none;}.pf.active{display:block;}
.err{color:var(--rd);font-size:13px;margin-top:8px;text-align:center;min-height:18px;}
.toast{position:fixed;bottom:30px;left:50%;transform:translateX(-50%);background:var(--pn);color:var(--tx);padding:12px 24px;border-radius:12px;border-left:4px solid var(--g);z-index:9999;box-shadow:0 8px 32px rgba(0,0,0,.5);opacity:0;transition:opacity .3s;pointer-events:none;font-weight:700;}
.toast.show{opacity:1;}
.spin{display:inline-block;width:18px;height:18px;border:2px solid rgba(255,255,255,.3);border-top-color:#fff;border-radius:50%;animation:spin .7s linear infinite;}
@keyframes spin{to{transform:rotate(360deg);}}
.note{font-size:12px;color:var(--st);text-align:center;margin-top:14px;line-height:1.6;}
</style>
</head>
<body>
<div class="wrap">
  <div class="logo">
    <svg viewBox="0 0 80 80" fill="none">
      <circle cx="40" cy="40" r="40" fill="#00a884"/>
      <path d="M40 16C27 16 16 27 16 40c0 4.3 1.2 8.4 3.3 11.8L16 64l12.7-3.4A24 24 0 1040 16z" fill="white"/>
      <path d="M31 33c0-.6.5-1 1-1h16c.6 0 1 .4 1 1v.6c0 .5-.4 1-1 1H32c-.5 0-1-.5-1-1V33zm0 8c0-.6.5-1 1-1h10c.5 0 1 .4 1 1v.5c0 .6-.5 1-1 1H32c-.5 0-1-.4-1-1V41z" fill="#00a884"/>
    </svg>
    <h1>WaClone</h1>
    <p>Simple. Fast. Private.</p>
  </div>
  <div class="card">
    <div class="tabs">
      <div class="tab active" onclick="sw('login')">Masuk</div>
      <div class="tab" onclick="sw('register')">Daftar</div>
    </div>
    <div id="login-p" class="pf active">
      <div class="fg"><label>Email</label><input id="le" type="email" placeholder="nama@email.com" onkeydown="if(event.key==='Enter')doLogin()"></div>
      <div class="fg">
        <label>Password</label>
        <input id="lp" type="password" placeholder="&#x2022;&#x2022;&#x2022;&#x2022;&#x2022;&#x2022;&#x2022;&#x2022;" onkeydown="if(event.key==='Enter')doLogin()">
        <span class="eye" onclick="togglePw('lp',this)">&#x1F441;&#xFE0F;</span>
      </div>
      <div class="err" id="le2"></div>
      <button class="btn" id="lbtn" onclick="doLogin()">Masuk &#x2192;</button>
      <div class="divider"><span>atau</span></div>
      <button class="gbtn" onclick="loginGoogle()">
        <svg viewBox="0 0 48 48"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.18 1.48-4.97 2.36-8.16 2.36-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg>
        Lanjutkan dengan Google
      </button>
    </div>
    <div id="register-p" class="pf">
      <div class="fg"><label>Username</label><input id="ru" placeholder="username kamu" onkeydown="if(event.key==='Enter')doReg()"></div>
      <div class="fg"><label>Email</label><input id="re" type="email" placeholder="nama@email.com" onkeydown="if(event.key==='Enter')doReg()"></div>
      <div class="fg">
        <label>Password</label>
        <input id="rp" type="password" placeholder="min. 6 karakter" onkeydown="if(event.key==='Enter')doReg()">
        <span class="eye" onclick="togglePw('rp',this)">&#x1F441;&#xFE0F;</span>
      </div>
      <div class="err" id="re2"></div>
      <button class="btn" id="rbtn" onclick="doReg()">Daftar &#x2192;</button>
      <div class="divider"><span>atau</span></div>
      <button class="gbtn" onclick="loginGoogle()">
        <svg viewBox="0 0 48 48"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.18 1.48-4.97 2.36-8.16 2.36-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg>
        Daftar dengan Google
      </button>
      <p class="note">Dengan mendaftar kamu menyetujui syarat &amp; ketentuan penggunaan WaClone.</p>
    </div>
  </div>
</div>
<div class="toast" id="toast"></div>
<script src="https://www.gstatic.com/firebasejs/10.12.0/firebase-app-compat.js"></script>
<script src="https://www.gstatic.com/firebasejs/10.12.0/firebase-auth-compat.js"></script>
<script>
let fbApp=null,fbAuth=null,fbInitialized=false;
async function ensureFirebase(){
  if(fbInitialized)return!!fbAuth;fbInitialized=true;
  try{const r=await fetch('/firebase_config');const cfg=await r.json();if(!cfg.apiKey)return false;
  if(!firebase.apps.length){fbApp=firebase.initializeApp(cfg);}else{fbApp=firebase.app();}
  fbAuth=firebase.auth();return true;}catch(e){fbInitialized=false;return false;}
}
ensureFirebase();
function sw(t){document.querySelectorAll('.tab').forEach(e=>e.classList.remove('active'));document.querySelectorAll('.pf').forEach(e=>e.classList.remove('active'));document.getElementById(t+'-p').classList.add('active');document.querySelectorAll('.tab')[t==='login'?0:1].classList.add('active');document.getElementById('le2').textContent='';document.getElementById('re2').textContent='';}
function toast(m,d=3000){const t=document.getElementById('toast');t.textContent=m;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),d);}
function togglePw(id,el){const i=document.getElementById(id);i.type=i.type==='password'?'text':'password';el.textContent=i.type==='password'?'&#x1F441;&#xFE0F;':'&#x1F648;';}
function setLoading(btn,loading){const b=document.getElementById(btn);if(loading){b.disabled=true;b.innerHTML='<span class="spin"></span>';}else{b.disabled=false;b.textContent=btn==='lbtn'?'Masuk \u2192':'Daftar \u2192';}}
async function doLogin(){
  const email=document.getElementById('le').value.trim(),pass=document.getElementById('lp').value;
  const err=document.getElementById('le2');if(!email||!pass){err.textContent='Isi semua field!';return;}
  setLoading('lbtn',true);const fd=new FormData();fd.append('email',email);fd.append('password',pass);
  const r=await fetch('/login',{method:'POST',body:fd});const d=await r.json();setLoading('lbtn',false);
  if(d.ok){toast('Login berhasil! \u{1F389}');setTimeout(()=>location.href='/home',700);}else err.textContent=d.msg||'Login gagal';
}
async function doReg(){
  const u=document.getElementById('ru').value.trim(),e=document.getElementById('re').value.trim(),p=document.getElementById('rp').value;
  const err=document.getElementById('re2');if(!u||!e||!p){err.textContent='Isi semua field!';return;}
  if(p.length<6){err.textContent='Password minimal 6 karakter';return;}
  if(!/^[a-zA-Z0-9_]+$/.test(u)){err.textContent='Username hanya huruf, angka, dan underscore';return;}
  setLoading('rbtn',true);const fd=new FormData();fd.append('username',u);fd.append('email',e);fd.append('password',p);
  const r=await fetch('/register',{method:'POST',body:fd});const d=await r.json();setLoading('rbtn',false);
  if(d.ok){toast('Registrasi berhasil! \u{1F389}');setTimeout(()=>location.href='/home',700);}else err.textContent=d.msg||'Registrasi gagal';
}
async function loginGoogle(){
  const errEl=document.getElementById('le2')||document.getElementById('re2');
  const ok=await ensureFirebase();if(!ok||!fbAuth){if(errEl)errEl.textContent='Google login tidak bisa dimuat';return;}
  try{
    const provider=new firebase.auth.GoogleAuthProvider();provider.addScope('email');provider.addScope('profile');
    const result=await fbAuth.signInWithPopup(provider);const idToken=await result.user.getIdToken();
    document.querySelectorAll('.gbtn').forEach(b=>{b.disabled=true;b.innerHTML='<span class="spin"></span> Memproses...';});
    const r=await fetch('/google_auth',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id_token:idToken})});
    const d=await r.json();
    document.querySelectorAll('.gbtn').forEach(b=>{b.disabled=false;b.textContent='Google';});
    if(d.ok){toast('Login Google berhasil! \u{1F389}');setTimeout(()=>location.href='/home',700);}
    else if(errEl)errEl.textContent=d.msg||'Google login gagal';
  }catch(e){
    document.querySelectorAll('.gbtn').forEach(b=>{b.disabled=false;});
    const msg=e.code==='auth/popup-closed-by-user'?'Login dibatalkan':e.code==='auth/popup-blocked'?'Popup diblokir browser':e.message||'Google login gagal';
    if(errEl)errEl.textContent=msg;
  }
}
</script>
</body>
</html>"""


MAIN_HTML = r"""<!DOCTYPE html>
<html>
<head>
<title>WaClone</title>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<link href="https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800;900&display=swap" rel="stylesheet">
<!-- Agora RTC SDK -->
<script src="https://download.agora.io/sdk/release/AgoraRTC_N-4.19.0.js"></script>
<style>
:root{
  --g:#00a884;--dk:#111b21;--pn:#202c33;--bo:#005c4b;--bi:#1e2c33;
  --bd:#2a3942;--tx:#e9edef;--st:#8696a0;--hv:#2a3942;--rd:#f15c6d;--bl:#53bdeb;
  --inp:#2a3942;
}
*{margin:0;padding:0;box-sizing:border-box;}
html,body{height:100%;overflow:hidden;}
body{font-family:'Nunito',sans-serif;background:var(--dk);color:var(--tx);display:flex;height:100vh;}
::-webkit-scrollbar{width:5px;}
::-webkit-scrollbar-thumb{background:var(--bd);border-radius:3px;}
input,textarea{outline:none;border:none;background:transparent;color:var(--tx);font-family:'Nunito',sans-serif;}
button{cursor:pointer;font-family:'Nunito',sans-serif;border:none;}

.sb{width:380px;min-width:320px;max-width:380px;background:var(--pn);display:flex;flex-direction:column;
  border-right:1px solid var(--bd);height:100vh;overflow:hidden;transition:transform .25s;}
.sbh{padding:10px 14px;display:flex;align-items:center;gap:8px;height:60px;border-bottom:1px solid var(--bd);flex-shrink:0;}
.my-av{width:40px;height:40px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;
  font-weight:900;font-size:17px;color:#fff;cursor:pointer;flex-shrink:0;overflow:hidden;}
.my-av img{width:40px;height:40px;object-fit:cover;border-radius:50%;}
.sbh-title{font-size:19px;font-weight:900;flex:1;color:var(--tx);}
.icon-btn{width:38px;height:38px;border-radius:50%;background:transparent;color:var(--st);display:flex;
  align-items:center;justify-content:center;transition:.2s;position:relative;flex-shrink:0;}
.icon-btn:hover{background:var(--hv);color:var(--tx);}
.badge{position:absolute;top:3px;right:3px;background:var(--rd);color:#fff;border-radius:50%;
  width:16px;height:16px;font-size:9px;font-weight:900;display:flex;align-items:center;justify-content:center;}

.sbtabs{display:flex;border-bottom:1px solid var(--bd);flex-shrink:0;}
.stab{flex:1;padding:10px 4px;text-align:center;font-size:13px;font-weight:800;color:var(--st);
  cursor:pointer;border-bottom:2.5px solid transparent;transition:.2s;position:relative;}
.stab.active{color:var(--g);border-bottom-color:var(--g);}

.search-wrap{padding:7px 12px;flex-shrink:0;}
.search-inner{position:relative;display:flex;align-items:center;}
.search-inner svg{position:absolute;left:11px;color:var(--st);pointer-events:none;}
.search-inner input{width:100%;padding:8px 14px 8px 38px;border-radius:10px;background:var(--dk);
  font-size:14px;color:var(--tx);border:1.5px solid transparent;}
.search-inner input:focus{border-color:var(--g);}

.sb-panel{flex:1;overflow-y:auto;display:none;flex-direction:column;}
.sb-panel.active{display:flex;}

.chat-item{display:flex;align-items:center;gap:11px;padding:9px 14px;cursor:pointer;
  border-bottom:1px solid rgba(255,255,255,.03);transition:.15s;}
.chat-item:hover,.chat-item.active{background:var(--hv);}
.chat-av{width:48px;height:48px;border-radius:50%;background:var(--g);display:flex;align-items:center;
  justify-content:center;font-weight:900;font-size:19px;color:#fff;flex-shrink:0;position:relative;overflow:hidden;}
.chat-av img{width:48px;height:48px;border-radius:50%;object-fit:cover;}
.online-dot{position:absolute;bottom:1px;right:1px;width:12px;height:12px;background:#44c56a;
  border-radius:50%;border:2px solid var(--pn);}
.chat-info{flex:1;min-width:0;}
.chat-name{font-weight:800;font-size:14px;color:var(--tx);}
.chat-prev{font-size:12px;color:var(--st);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px;}
.chat-meta{display:flex;flex-direction:column;align-items:flex-end;gap:3px;flex-shrink:0;}
.chat-time{font-size:11px;color:var(--st);}
.unread-badge{background:var(--g);color:#fff;border-radius:50%;min-width:19px;height:19px;
  font-size:11px;font-weight:900;display:flex;align-items:center;justify-content:center;padding:0 4px;}

.status-section-label{font-size:11px;font-weight:800;color:var(--st);text-transform:uppercase;
  letter-spacing:.5px;padding:10px 14px 5px;}
.my-status-row{display:flex;align-items:center;gap:12px;padding:10px 14px;cursor:pointer;
  border-bottom:1px solid var(--bd);transition:.15px;}
.my-status-row:hover{background:var(--hv);}
.status-ring-wrap{position:relative;flex-shrink:0;}
.status-ring{width:52px;height:52px;border-radius:50%;border:3px solid var(--g);padding:2px;}
.status-ring-inner{width:100%;height:100%;border-radius:50%;background:var(--g);display:flex;
  align-items:center;justify-content:center;font-weight:900;font-size:18px;color:#fff;overflow:hidden;}
.status-ring-inner img{width:100%;height:100%;object-fit:cover;}
.status-add-badge{position:absolute;bottom:-2px;right:-2px;width:20px;height:20px;border-radius:50%;
  background:var(--g);color:#fff;font-size:15px;line-height:20px;text-align:center;border:2px solid var(--pn);}
.status-friend-item{display:flex;align-items:center;gap:12px;padding:9px 14px;cursor:pointer;
  border-bottom:1px solid rgba(255,255,255,.03);transition:.15s;}
.status-friend-item:hover{background:var(--hv);}

.main{flex:1;display:flex;flex-direction:column;overflow:hidden;position:relative;height:100vh;}
.no-chat{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;color:var(--st);gap:10px;}
.no-chat-icon{font-size:70px;opacity:.25;}
.no-chat h2{font-size:21px;font-weight:900;color:var(--tx);}
.no-chat p{font-size:13px;}

.chat-header{height:60px;background:var(--pn);display:flex;align-items:center;gap:2px;
  padding:0 4px 0 2px;border-bottom:1px solid var(--bd);flex-shrink:0;overflow:visible;}
.back-btn{width:34px;height:34px;border-radius:50%;background:transparent;color:var(--st);
  display:none;align-items:center;justify-content:center;font-size:21px;flex-shrink:0;transition:.2s;}
.back-btn:hover{background:var(--hv);color:var(--tx);}
.header-av{width:40px;height:40px;border-radius:50%;overflow:hidden;flex-shrink:0;cursor:pointer;}
.header-av img,.header-av div{width:40px;height:40px;border-radius:50%;}
.header-info{flex:1;cursor:pointer;min-width:0;overflow:hidden;}
.header-info h3{font-weight:900;font-size:15px;color:var(--tx);}
.header-info p{font-size:11px;color:var(--g);}

/* ====== FIXED: Header buttons - selalu tampil ====== */
.header-btn{width:38px;height:38px;border-radius:50%;background:transparent;color:var(--tx);
  display:flex !important;align-items:center;justify-content:center;transition:.2s;flex-shrink:0;
  border:none;cursor:pointer;}
.header-btn:hover,.header-btn:active{background:var(--hv);}
.header-btn svg{pointer-events:none;}

.messages-area{flex:1;overflow-y:auto;padding:8px 18px 4px;display:flex;flex-direction:column;gap:2px;
  background-color:var(--dk);
  background-image:url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='%23ffffff' fill-opacity='0.015'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/svg%3E");}
.msg-row{display:flex;margin:1px 0;align-items:flex-end;gap:4px;position:relative;}
.msg-row:hover .msg-actions{opacity:1;}
.msg-row.out{justify-content:flex-end;}
.msg-row.in{justify-content:flex-start;}
.msg-actions{opacity:0;transition:opacity .15s;display:flex;gap:3px;align-items:center;}
.msg-row.out .msg-actions{order:-1;}
.act-btn{width:25px;height:25px;border-radius:50%;background:rgba(32,44,51,.92);border:1px solid var(--bd);
  color:var(--st);font-size:11px;display:flex;align-items:center;justify-content:center;transition:.15s;}
.act-btn:hover{background:var(--hv);color:var(--tx);}
.bubble{max-width:66%;padding:7px 11px 4px;border-radius:12px;font-size:14px;line-height:1.5;
  word-break:break-word;box-shadow:0 1px 2px rgba(0,0,0,.3);position:relative;}
.msg-row.out .bubble{background:var(--bo);border-bottom-right-radius:3px;}
.msg-row.in .bubble{background:var(--bi);border-bottom-left-radius:3px;}
.bubble-time{font-size:10.5px;color:rgba(255,255,255,.45);text-align:right;margin-top:3px;
  display:flex;align-items:center;justify-content:flex-end;gap:2px;white-space:nowrap;line-height:1;}
.tick{display:inline-flex;align-items:center;line-height:1;}.tick.read{color:var(--bl);}.tick svg{display:inline-block;}
.bubble img{max-width:250px;max-height:250px;border-radius:8px;display:block;margin-bottom:3px;cursor:pointer;object-fit:cover;}
.bubble audio{width:210px;margin-bottom:3px;}
.bubble video{max-width:250px;border-radius:8px;display:block;margin-bottom:3px;}
.bubble a.file-link{color:var(--bl);text-decoration:none;font-size:13px;display:flex;align-items:center;gap:6px;padding:5px 0;}
.date-divider{text-align:center;color:var(--st);font-size:11px;margin:8px 0;}
.date-divider span{background:rgba(17,27,33,.85);padding:3px 12px;border-radius:20px;border:1px solid var(--bd);}
.reply-quote{background:rgba(255,255,255,.07);border-left:3px solid var(--g);border-radius:6px;
  padding:5px 8px;margin-bottom:5px;font-size:11px;cursor:pointer;}
.rq-name{font-weight:800;color:var(--g);font-size:10px;margin-bottom:2px;}
.rq-text{color:var(--st);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:220px;}
.typing-wrap{padding:3px 18px;min-height:24px;display:flex;align-items:center;flex-shrink:0;}
.typing-dots{display:none;align-items:center;gap:6px;}
.typing-dots.show{display:flex;}
.dot-anim{display:flex;gap:3px;}
.dot-anim span{width:6px;height:6px;background:var(--st);border-radius:50%;animation:dotBounce 1.4s infinite;}
.dot-anim span:nth-child(2){animation-delay:.2s;}
.dot-anim span:nth-child(3){animation-delay:.4s;}
@keyframes dotBounce{0%,60%,100%{transform:translateY(0);}30%{transform:translateY(-5px);}}
.typing-text{font-size:11px;color:var(--st);}

.input-area{background:var(--pn);padding:6px 10px 8px;border-top:1px solid var(--bd);flex-shrink:0;display:flex;flex-direction:column;gap:5px;}
.reply-preview{display:none;background:rgba(0,168,132,.1);border-left:3px solid var(--g);border-radius:8px;padding:6px 10px;align-items:center;justify-content:space-between;gap:8px;}
.reply-preview.show{display:flex;}
.rp-name{color:var(--g);font-weight:800;font-size:11px;}
.rp-text{color:var(--st);font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.rp-close{width:22px;height:22px;border-radius:50%;background:var(--bd);color:var(--st);font-size:12px;display:flex;align-items:center;justify-content:center;}
.rp-close:hover{background:var(--hv);color:var(--tx);}
.input-row{display:flex;align-items:flex-end;gap:5px;}
.side-btn{width:38px;height:38px;border-radius:50%;background:transparent;color:var(--st);display:flex;align-items:center;justify-content:center;font-size:20px;flex-shrink:0;transition:.2s;}
.side-btn:hover{background:var(--hv);color:var(--tx);}
.msg-textarea{flex:1;background:var(--inp);border:1.5px solid transparent;border-radius:22px;padding:9px 15px;font-size:14.5px;color:var(--tx);resize:none;max-height:120px;min-height:42px;line-height:1.4;transition:.2s;display:block;}
.msg-textarea:focus{border-color:var(--g);outline:none;}
.msg-textarea::placeholder{color:var(--st);}
.send-btn{width:42px;height:42px;border-radius:50%;background:var(--g);color:#fff;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:.2s;}
.send-btn:hover{background:#009070;transform:scale(1.06);}
.rec-btn{width:42px;height:42px;border-radius:50%;background:var(--dk);border:1.5px solid var(--bd);color:var(--st);display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:.2s;}
.rec-btn.recording{background:var(--rd);border-color:var(--rd);color:#fff;animation:recPulse 1s infinite;}
@keyframes recPulse{0%,100%{transform:scale(1);}50%{transform:scale(1.1);}}
.upload-progress{height:3px;background:var(--bd);border-radius:3px;overflow:hidden;display:none;}
.upload-progress.show{display:block;}
.upload-fill{height:100%;background:var(--g);width:0%;transition:width .3s;border-radius:3px;}

.emoji-picker{position:absolute;bottom:68px;right:52px;background:var(--pn);border:1px solid var(--bd);
  border-radius:16px;padding:10px;box-shadow:0 8px 30px rgba(0,0,0,.6);z-index:200;display:none;width:280px;}
.emoji-picker.open{display:block;}
.emoji-grid{display:flex;flex-wrap:wrap;gap:2px;max-height:170px;overflow-y:auto;}
.emoji-item{font-size:21px;cursor:pointer;padding:4px;border-radius:7px;transition:.1s;line-height:1;}
.emoji-item:hover{background:var(--hv);}

.att-menu{position:absolute;bottom:68px;left:10px;background:var(--pn);border:1px solid var(--bd);
  border-radius:16px;padding:12px;box-shadow:0 8px 30px rgba(0,0,0,.6);z-index:200;display:none;flex-wrap:wrap;gap:8px;width:220px;}
.att-menu.open{display:flex;}
.att-opt{display:flex;flex-direction:column;align-items:center;gap:5px;cursor:pointer;width:calc(33% - 6px);padding:5px 0;border-radius:10px;transition:.15s;}
.att-opt:hover{background:var(--hv);}
.att-ic{width:44px;height:44px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:19px;}
.att-lbl{font-size:10px;font-weight:700;color:var(--st);}

.ctx-menu{position:fixed;background:var(--pn);border:1px solid var(--bd);border-radius:14px;
  box-shadow:0 8px 30px rgba(0,0,0,.6);z-index:600;min-width:178px;overflow:hidden;display:none;}
.ctx-item{padding:10px 16px;font-size:14px;font-weight:700;cursor:pointer;display:flex;align-items:center;gap:10px;transition:.15s;color:var(--tx);}
.ctx-item:hover{background:var(--hv);}
.ctx-item.danger{color:var(--rd);}

.overlay{position:fixed;inset:0;background:rgba(0,0,0,.72);z-index:400;display:none;align-items:center;justify-content:center;}
.overlay.open{display:flex;}
.panel{background:var(--pn);border-radius:20px;width:400px;max-height:90vh;overflow-y:auto;border:1px solid var(--bd);box-shadow:0 20px 60px rgba(0,0,0,.6);}
.panel-header{padding:16px 20px;display:flex;align-items:center;justify-content:space-between;
  border-bottom:1px solid var(--bd);position:sticky;top:0;background:var(--pn);z-index:1;}
.panel-header h2{font-size:17px;font-weight:900;}
.close-btn{background:var(--hv);border:none;color:var(--st);width:30px;height:30px;border-radius:50%;
  font-size:15px;display:flex;align-items:center;justify-content:center;cursor:pointer;}
.close-btn:hover{color:var(--tx);}
.panel-body{padding:18px 20px;}
.pav-wrap{text-align:center;margin-bottom:14px;position:relative;display:inline-block;left:50%;transform:translateX(-50%);}
.pav-big{width:96px;height:96px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-size:38px;font-weight:900;color:#fff;overflow:hidden;cursor:pointer;border:3px solid var(--bd);transition:.2s;}
.pav-big:hover{border-color:var(--g);}
.pav-big img{width:100%;height:100%;object-fit:cover;}
.pav-edit-btn{position:absolute;bottom:1px;right:0;background:var(--g);width:28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.4);font-size:12px;}
.prof-name{font-size:19px;font-weight:900;text-align:center;}
.prof-email{color:var(--st);font-size:12px;text-align:center;margin-top:3px;}
.field-group{margin-bottom:12px;}
.field-group label{display:block;font-size:10px;font-weight:800;color:var(--g);text-transform:uppercase;letter-spacing:.6px;margin-bottom:5px;}
.field-group input,.field-group textarea,.field-group select{width:100%;padding:9px 12px;border-radius:10px;background:var(--dk);border:1.5px solid var(--bd);color:var(--tx);font-size:13px;font-family:'Nunito',sans-serif;transition:.2s;}
.field-group input:focus,.field-group textarea:focus,.field-group select:focus{border-color:var(--g);outline:none;}
.field-group textarea{resize:none;height:68px;line-height:1.5;}
.field-group select{appearance:none;cursor:pointer;}
.save-btn{width:100%;padding:11px;background:var(--g);color:#fff;border:none;border-radius:12px;font-size:14px;font-weight:800;margin-top:5px;transition:.2s;cursor:pointer;}
.save-btn:hover{background:#009070;}
.logout-btn{width:100%;padding:10px;background:transparent;color:var(--rd);border:1.5px solid var(--rd);border-radius:12px;font-size:14px;font-weight:800;margin-top:7px;transition:.2s;cursor:pointer;}
.logout-btn:hover{background:var(--rd);color:#fff;}

.settings-section{margin-bottom:18px;}
.settings-section h3{font-size:11px;font-weight:800;color:var(--g);text-transform:uppercase;letter-spacing:.6px;margin-bottom:10px;padding-bottom:5px;border-bottom:1px solid var(--bd);}
.settings-row{display:flex;align-items:center;justify-content:space-between;padding:9px 0;border-bottom:1px solid rgba(255,255,255,.04);}
.settings-row:last-child{border-bottom:none;}
.settings-label{font-size:13px;font-weight:700;color:var(--tx);}
.settings-desc{font-size:11px;color:var(--st);margin-top:2px;}
.toggle-switch{position:relative;width:44px;height:24px;flex-shrink:0;}
.toggle-switch input{opacity:0;width:0;height:0;}
.toggle-slider{position:absolute;inset:0;background:var(--bd);border-radius:24px;cursor:pointer;transition:.3s;}
.toggle-slider:before{content:'';position:absolute;width:18px;height:18px;left:3px;bottom:3px;background:#fff;border-radius:50%;transition:.3s;}
.toggle-switch input:checked+.toggle-slider{background:var(--g);}
.toggle-switch input:checked+.toggle-slider:before{transform:translateX(20px);}
.settings-btn{padding:7px 14px;background:var(--dk);border:1.5px solid var(--bd);border-radius:8px;color:var(--tx);font-size:12px;font-weight:700;cursor:pointer;transition:.2s;}
.settings-btn:hover{border-color:var(--g);color:var(--g);}
.settings-btn.danger{border-color:var(--rd);color:var(--rd);}
.settings-btn.danger:hover{background:var(--rd);color:#fff;}

.notif-item{display:flex;gap:10px;align-items:center;padding:9px 0;border-bottom:1px solid var(--bd);cursor:pointer;}
.notif-item:last-child{border-bottom:none;}
.notif-av{width:42px;height:42px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-weight:900;font-size:17px;color:#fff;flex-shrink:0;overflow:hidden;}
.notif-av img{width:42px;height:42px;object-fit:cover;}
.notif-dot{width:8px;height:8px;background:var(--g);border-radius:50%;flex-shrink:0;}

.stv{background:#000;width:100%;max-width:460px;border-radius:20px;overflow:hidden;}
.stv-progress{display:flex;gap:3px;padding:10px 12px 6px;}
.stv-seg{flex:1;height:3px;background:rgba(255,255,255,.3);border-radius:3px;overflow:hidden;}
.stv-fill{height:100%;background:#fff;width:0%;transition:width linear;}
.stv-head{display:flex;align-items:center;gap:10px;padding:6px 14px;}
.stv-av{width:34px;height:34px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-weight:900;color:#fff;font-size:13px;overflow:hidden;}
.stv-av img{width:100%;height:100%;object-fit:cover;}
.stv-body{min-height:200px;display:flex;align-items:center;justify-content:center;padding:14px;}
.stv-text{font-size:22px;font-weight:800;text-align:center;color:#fff;padding:22px 14px;width:100%;}
.stv-img{max-width:100%;max-height:380px;object-fit:contain;border-radius:4px;}
.stv-nav-btns{display:flex;justify-content:space-between;padding:8px 14px 14px;}
.stv-nav-btn{padding:8px 20px;background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.2);
  border-radius:20px;color:#fff;font-size:13px;font-weight:700;cursor:pointer;transition:.2s;}
.stv-nav-btn:hover{background:rgba(255,255,255,.2);}

.create-opts{display:flex;flex-direction:column;gap:8px;}
.create-opt{display:flex;align-items:center;gap:12px;padding:11px;background:var(--dk);border-radius:10px;border:1.5px solid var(--bd);cursor:pointer;transition:.2s;}
.create-opt:hover{border-color:var(--g);}
.create-opt-ic{width:42px;height:42px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:19px;flex-shrink:0;}

.cam-wrap{background:#000;border-radius:12px;overflow:hidden;}
.cam-wrap video{width:100%;display:block;max-height:270px;object-fit:cover;}
.cam-controls{display:flex;gap:10px;justify-content:center;margin-top:10px;}
.cam-btn{width:50px;height:50px;border-radius:50%;border:none;display:flex;align-items:center;justify-content:center;font-size:20px;cursor:pointer;transition:.2s;}

.fw-list{display:flex;flex-direction:column;gap:6px;max-height:260px;overflow-y:auto;}
.fw-item{display:flex;align-items:center;gap:10px;padding:9px;background:var(--dk);border-radius:10px;cursor:pointer;border:1.5px solid var(--bd);transition:.15s;}
.fw-item:hover,.fw-item.sel{border-color:var(--g);}
.fw-av{width:36px;height:36px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-weight:900;font-size:14px;color:#fff;flex-shrink:0;overflow:hidden;}
.fw-av img{width:36px;height:36px;object-fit:cover;}
.img-fullview{max-width:92vw;max-height:88vh;border-radius:8px;object-fit:contain;}

/* ====== AGORA CALL UI ====== */
.call-ui{position:fixed;inset:0;background:#0a0a14;z-index:900;display:none;flex-direction:column;align-items:center;justify-content:space-between;padding:16px;}
.call-ui.active{display:flex;}
.call-video-grid{width:100%;max-width:1000px;flex:1;display:flex;align-items:center;justify-content:center;gap:10px;padding:8px 0;position:relative;}
#agora-remote-container{flex:1;max-height:72vh;border-radius:18px;overflow:hidden;background:#111827;border:1px solid var(--bd);min-height:200px;display:flex;align-items:center;justify-content:center;}
#agora-remote-container video{width:100%;height:100%;object-fit:cover;}
#agora-local-container{position:relative;width:170px;min-width:130px;height:230px;border-radius:16px;overflow:hidden;background:#111;border:2px solid var(--g);flex-shrink:0;}
#agora-local-container video{width:100%;height:100%;object-fit:cover;}
.audio-call-info{text-align:center;padding:30px 20px;flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;}
.call-person-av{width:120px;height:120px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-size:50px;font-weight:900;color:#fff;margin:0 auto 16px;overflow:hidden;
  border:4px solid rgba(0,168,132,.3);animation:callRing 2.5s infinite;}
@keyframes callRing{0%,100%{box-shadow:0 0 0 0 rgba(0,168,132,.4);}60%{box-shadow:0 0 0 22px rgba(0,168,132,0);}}
.call-person-av img{width:100%;height:100%;object-fit:cover;}
.call-name{font-size:28px;font-weight:900;color:#fff;}
.call-status-txt{font-size:15px;color:rgba(255,255,255,.55);margin-top:6px;}
.call-timer{font-size:20px;color:var(--g);font-weight:800;margin-top:10px;display:none;letter-spacing:2px;}
.call-controls{display:flex;gap:16px;align-items:center;justify-content:center;padding:12px 0 4px;flex-shrink:0;}
.call-cbtn{width:64px;height:64px;border-radius:50%;border:none;display:flex;align-items:center;justify-content:center;font-size:26px;cursor:pointer;transition:.2s;}
.call-cbtn:hover{transform:scale(1.08);}
.cbtn-end{background:#e53e3e;}
.cbtn-toggle{background:#1e2a3a;}
.cbtn-toggle:hover{background:#2a3a52;}
.cbtn-on{background:var(--g)!important;}
.cbtn-off-state{background:#e53e3e!important;}
.incoming-call{position:fixed;bottom:24px;right:24px;background:var(--pn);border:1px solid var(--bd);border-radius:20px;padding:18px;z-index:950;box-shadow:0 20px 60px rgba(0,0,0,.8);min-width:270px;display:none;}
.incoming-call.show{display:block;animation:slideInRight .3s ease;}
@keyframes slideInRight{from{transform:translateX(60px);opacity:0;}to{transform:none;opacity:1;}}
.inc-av{width:56px;height:56px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-size:22px;font-weight:900;color:#fff;margin:0 auto 8px;overflow:hidden;}
.inc-av img{width:100%;height:100%;object-fit:cover;}
.inc-type-badge{text-align:center;font-size:12px;color:var(--st);margin-bottom:10px;}
.inc-actions{display:flex;gap:8px;}
.inc-btn{flex:1;padding:10px;border:none;border-radius:10px;font-size:13px;font-weight:800;cursor:pointer;}
.inc-audio{background:var(--g);color:#fff;}
.inc-video{background:#1a56db;color:#fff;}
.inc-reject{background:var(--rd);color:#fff;flex:none;padding:10px 14px;}

/* ====== LIVE STREAMING UI ====== */
.live-ui{position:fixed;inset:0;background:#000;z-index:910;display:none;flex-direction:column;}
.live-ui.active{display:flex;}
.live-header{display:flex;align-items:center;justify-content:space-between;padding:12px 16px;background:linear-gradient(to bottom,rgba(0,0,0,.8),transparent);position:absolute;top:0;left:0;right:0;z-index:2;}
.live-badge{background:#e53e3e;color:#fff;padding:4px 10px;border-radius:20px;font-size:12px;font-weight:900;letter-spacing:1px;animation:livePulse 1.5s infinite;}
@keyframes livePulse{0%,100%{opacity:1;}50%{opacity:.7;}}
.live-viewer-count{background:rgba(0,0,0,.6);color:#fff;padding:4px 10px;border-radius:20px;font-size:12px;font-weight:700;}
.live-video-area{flex:1;position:relative;background:#000;}
#live-local-video,#live-remote-video{width:100%;height:100%;object-fit:cover;position:absolute;top:0;left:0;}
.live-comments{position:absolute;bottom:80px;left:0;right:0;padding:10px 14px;display:flex;flex-direction:column;gap:4px;max-height:200px;overflow:hidden;pointer-events:none;}
.live-comment{background:rgba(0,0,0,.55);color:#fff;padding:6px 12px;border-radius:20px;font-size:13px;font-weight:600;width:fit-content;max-width:80%;animation:commentFade 0.3s ease;}
@keyframes commentFade{from{opacity:0;transform:translateY(10px);}to{opacity:1;transform:none;}}
.live-comment .cname{color:var(--g);font-weight:900;margin-right:6px;}
.live-controls-bottom{position:absolute;bottom:0;left:0;right:0;padding:12px 16px;background:linear-gradient(to top,rgba(0,0,0,.8),transparent);display:flex;align-items:center;gap:10px;}
.live-comment-input{flex:1;background:rgba(255,255,255,.15);border:1px solid rgba(255,255,255,.25);border-radius:24px;padding:9px 16px;color:#fff;font-size:14px;font-family:'Nunito',sans-serif;}
.live-comment-input::placeholder{color:rgba(255,255,255,.5);}
.live-comment-input:focus{outline:none;border-color:var(--g);}
.live-send-comment{width:40px;height:40px;border-radius:50%;background:var(--g);color:#fff;border:none;display:flex;align-items:center;justify-content:center;cursor:pointer;flex-shrink:0;}
.live-end-btn{padding:9px 18px;background:#e53e3e;color:#fff;border:none;border-radius:20px;font-size:13px;font-weight:800;cursor:pointer;}
.live-viewers-panel{position:absolute;top:60px;right:12px;background:rgba(0,0,0,.75);border:1px solid rgba(255,255,255,.15);border-radius:14px;padding:10px 14px;max-width:180px;max-height:260px;overflow-y:auto;}
.live-viewer-item{display:flex;align-items:center;gap:8px;padding:4px 0;font-size:12px;color:#fff;}
/* Live streaming list in sidebar live tab */
.live-item{display:flex;align-items:center;gap:11px;padding:9px 14px;cursor:pointer;border-bottom:1px solid rgba(255,255,255,.03);transition:.15s;}
.live-item:hover{background:var(--hv);}
.live-thumb{width:70px;height:44px;border-radius:8px;background:#111;overflow:hidden;flex-shrink:0;position:relative;}
.live-thumb video,.live-thumb img{width:100%;height:100%;object-fit:cover;}
.live-thumb-badge{position:absolute;top:3px;left:3px;background:#e53e3e;color:#fff;font-size:9px;font-weight:900;padding:1px 5px;border-radius:4px;}

/* AI Drawer */
.ai-drawer{position:fixed;top:0;right:0;height:100vh;width:380px;background:#13111c;
  border-left:1px solid rgba(108,58,199,.3);z-index:500;display:flex;flex-direction:column;
  transform:translateX(100%);transition:transform .3s cubic-bezier(.4,0,.2,1);
  box-shadow:-20px 0 60px rgba(0,0,0,.5);}
.ai-drawer.open{transform:translateX(0);}
.ai-drawer-header{padding:14px 16px;background:linear-gradient(135deg,#2d1059 0%,#1a0a38 100%);
  display:flex;align-items:center;gap:10px;border-bottom:1px solid rgba(108,58,199,.3);flex-shrink:0;}
.ai-avatar-icon{width:38px;height:38px;border-radius:50%;background:linear-gradient(135deg,#7c3aed,#9b5de5);
  display:flex;align-items:center;justify-content:center;font-size:18px;flex-shrink:0;}
.ai-drawer-title{font-weight:900;font-size:16px;color:#e0d4ff;}
.ai-online-dot{width:9px;height:9px;border-radius:50%;background:#a8ff78;animation:aiPulse 1.5s infinite;margin-left:4px;}
@keyframes aiPulse{0%,100%{opacity:1;transform:scale(1);}50%{opacity:.6;transform:scale(.85);}}
.ai-close{margin-left:auto;width:30px;height:30px;border-radius:50%;background:rgba(255,255,255,.08);
  color:rgba(224,212,255,.6);font-size:16px;display:flex;align-items:center;justify-content:center;cursor:pointer;transition:.2s;}
.ai-close:hover{background:rgba(255,255,255,.15);color:#e0d4ff;}
.ai-messages{flex:1;overflow-y:auto;padding:14px 14px 6px;display:flex;flex-direction:column;gap:10px;}
.ai-msg{display:flex;gap:8px;align-items:flex-start;}
.ai-msg.user{flex-direction:row-reverse;}
.ai-msg-av{width:30px;height:30px;border-radius:50%;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:14px;}
.ai-msg.ai .ai-msg-av{background:linear-gradient(135deg,#7c3aed,#9b5de5);}
.ai-msg.user .ai-msg-av{background:var(--g);}
.ai-bubble{max-width:84%;padding:9px 12px;border-radius:14px;font-size:13.5px;line-height:1.55;word-break:break-word;}
.ai-msg.ai .ai-bubble{background:rgba(108,58,199,.15);border:1px solid rgba(108,58,199,.25);color:#d4c8f8;}
.ai-msg.user .ai-bubble{background:var(--bo);color:var(--tx);border-bottom-right-radius:3px;}
.ai-thinking-bubble{display:flex;gap:4px;padding:10px 14px;background:rgba(108,58,199,.12);border:1px solid rgba(108,58,199,.2);border-radius:14px;}
.ai-thinking-bubble span{width:7px;height:7px;background:#9b5de5;border-radius:50%;animation:dotBounce 1.4s infinite;}
.ai-thinking-bubble span:nth-child(2){animation-delay:.2s;}
.ai-thinking-bubble span:nth-child(3){animation-delay:.4s;}
.ai-chips{display:flex;flex-wrap:wrap;gap:5px;padding:4px 14px 8px;}
.ai-chip{padding:5px 11px;background:rgba(108,58,199,.12);border:1px solid rgba(108,58,199,.25);
  border-radius:20px;font-size:11.5px;color:#c4b3f0;cursor:pointer;transition:.2s;}
.ai-chip:hover{background:rgba(108,58,199,.25);color:#e0d4ff;}
.ai-input-row{padding:10px 14px 14px;border-top:1px solid rgba(108,58,199,.2);display:flex;gap:8px;align-items:flex-end;flex-shrink:0;}
.ai-textarea{flex:1;background:rgba(108,58,199,.1);border:1.5px solid rgba(108,58,199,.3);border-radius:18px;
  padding:9px 13px;font-size:13.5px;color:#e0d4ff;resize:none;min-height:40px;max-height:100px;line-height:1.4;font-family:'Nunito',sans-serif;}
.ai-textarea:focus{border-color:#9b5de5;outline:none;}
.ai-textarea::placeholder{color:rgba(224,212,255,.3);}
.ai-send-btn{width:40px;height:40px;border-radius:50%;background:linear-gradient(135deg,#7c3aed,#9b5de5);color:#fff;
  border:none;display:flex;align-items:center;justify-content:center;flex-shrink:0;cursor:pointer;transition:.2s;}
.ai-send-btn:hover{transform:scale(1.08);box-shadow:0 4px 15px rgba(108,58,199,.5);}
.copy-to-chat-btn{display:inline-flex;align-items:center;gap:5px;margin-top:6px;padding:5px 12px;
  background:rgba(0,168,132,.12);border:1px solid rgba(0,168,132,.3);border-radius:14px;
  color:var(--g);font-size:11.5px;font-weight:700;cursor:pointer;font-family:'Nunito',sans-serif;transition:.2s;}
.copy-to-chat-btn:hover{background:rgba(0,168,132,.22);}

.toast{position:fixed;bottom:26px;left:50%;transform:translateX(-50%);background:var(--pn);color:var(--tx);padding:9px 20px;border-radius:12px;border-left:4px solid var(--g);z-index:9999;box-shadow:0 8px 32px rgba(0,0,0,.5);opacity:0;transition:opacity .3s;pointer-events:none;font-weight:700;white-space:nowrap;}
.toast.show{opacity:1;}
.toast.err{border-left-color:var(--rd);}

@media(max-width:700px){
  .sb{position:fixed;left:0;top:0;z-index:100;width:100%!important;max-width:100%!important;transition:transform .25s;}
  .sb.hidden{transform:translateX(-100%);}
  .main{width:100%;}
  .back-btn{display:flex!important;}
  .messages-area{padding:6px 8px 4px;}
  .bubble{max-width:82%;}
  .ai-drawer{width:100%;}
  .live-ui{z-index:1000;}
}
</style>
</head>
<body>

<!-- SIDEBAR -->
<div class="sb" id="sidebar">
  <div class="sbh">
    <div class="my-av" onclick="openPanel('prof-ov')" id="my-av-el">__SIDEBAR_AV__</div>
    <span class="sbh-title">WaClone</span>
    <button class="icon-btn" onclick="openAI()" title="Asisten AI"
      style="background:linear-gradient(135deg,#7c3aed,#9b5de5);color:#fff;">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2a2 2 0 012 2c0 .74-.4 1.39-1 1.73V7h1a7 7 0 017 7h1a1 1 0 010 2h-1v1a2 2 0 01-2 2H5a2 2 0 01-2-2v-1H2a1 1 0 010-2h1a7 7 0 017-7h1V5.73A2 2 0 0110 4a2 2 0 012-2zm-5 9a5 5 0 000 10h10a5 5 0 000-10H7zm2 3a1 1 0 110 2 1 1 0 010-2zm6 0a1 1 0 110 2 1 1 0 010-2z"/></svg>
    </button>
    <button class="icon-btn" onclick="openNotifPanel()" title="Notifikasi">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M12 22c1.1 0 2-.9 2-2h-4c0 1.1.9 2 2 2zm6-6v-5c0-3.07-1.63-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 1.5v.68C7.64 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z"/></svg>
      <span class="badge" id="notif-badge" style="display:none">0</span>
    </button>
    <button class="icon-btn" onclick="openPanel('settings-ov')" title="Pengaturan">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M19.14,12.94c0.04-0.3,0.06-0.61,0.06-0.94c0-0.32-0.02-0.64-0.07-0.94l2.03-1.58c0.18-0.14,0.23-0.41,0.12-0.61 l-1.92-3.32c-0.12-0.22-0.37-0.29-0.59-0.22l-2.39,0.96c-0.5-0.38-1.03-0.7-1.62-0.94L14.4,2.81c-0.04-0.24-0.24-0.41-0.48-0.41 h-3.84c-0.24,0-0.43,0.17-0.47,0.41L9.25,5.35C8.66,5.59,8.12,5.92,7.63,6.29L5.24,5.33c-0.22-0.08-0.47,0-0.59,0.22L2.74,8.87 C2.62,9.08,2.66,9.34,2.86,9.48l2.03,1.58C4.84,11.36,4.8,11.69,4.8,12s0.02,0.64,0.07,0.94l-2.03,1.58 c-0.18,0.14-0.23,0.41-0.12,0.61l1.92,3.32c0.12,0.22,0.37,0.29,0.59,0.22l2.39-0.96c0.5,0.38,1.03,0.7,1.62,0.94l0.36,2.54 c0.05,0.24,0.24,0.41,0.48,0.41h3.84c0.24,0,0.44-0.17,0.47-0.41l0.36-2.54c0.59-0.24,1.13-0.56,1.62-0.94l2.39,0.96 c0.22,0.08,0.47,0,0.59-0.22l1.92-3.32c0.12-0.22,0.07-0.47-0.12-0.61L19.14,12.94z M12,15.6c-1.98,0-3.6-1.62-3.6-3.6 s1.62-3.6,3.6-3.6s3.6,1.62,3.6,3.6S13.98,15.6,12,15.6z"/></svg>
    </button>
  </div>

  <div class="sbtabs">
    <div class="stab active" onclick="switchTab('chats')" id="tab-chats">&#x1F4AC; Chat</div>
    <div class="stab" onclick="switchTab('status')" id="tab-status">&#x1F7E2; Status</div>
    <div class="stab" onclick="switchTab('live')" id="tab-live">&#x1F534; Live</div>
    <div class="stab" onclick="switchTab('contacts')" id="tab-contacts">&#x1F465; Kontak</div>
  </div>

  <div class="search-wrap" id="search-wrap-el">
    <div class="search-inner">
      <svg width="15" height="15" viewBox="0 0 24 24" fill="currentColor"><path d="M15.5 14h-.79l-.28-.27A6.471 6.471 0 0016 9.5 6.5 6.5 0 109.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/></svg>
      <input type="text" id="search-input" placeholder="Cari..." oninput="filterList(this.value)">
    </div>
  </div>

  <div class="sb-panel active" id="panel-chats">
    <div id="chat-list"><div style="padding:28px;text-align:center;color:var(--st);font-size:14px;">Memuat...</div></div>
  </div>

  <div class="sb-panel" id="panel-status">
    <div class="status-section-label">Status Saya</div>
    <div class="my-status-row" onclick="openMyStatus()">
      <div class="status-ring-wrap">
        <div class="status-ring" id="my-status-ring">
          <div class="status-ring-inner" id="my-status-ring-av">__SIDEBAR_AV__</div>
        </div>
        <div class="status-add-badge">+</div>
      </div>
      <div style="flex:1;">
        <div style="font-weight:800;font-size:14px;">Lihat / Tambah Status Saya</div>
        <div style="font-size:12px;color:var(--st);margin-top:2px;" id="my-status-hint">Ketuk untuk lihat atau buat status</div>
      </div>
    </div>
    <div class="status-section-label" id="friends-stat-label" style="display:none;">Status Teman</div>
    <div id="friends-status-list"></div>
    <div id="status-empty" style="display:none;padding:30px;text-align:center;color:var(--st);font-size:13px;">Belum ada status teman &#x1F440;</div>
  </div>

  <!-- LIVE TAB -->
  <div class="sb-panel" id="panel-live">
    <div style="padding:12px 14px;">
      <button onclick="startLiveStream()" style="width:100%;padding:12px;background:linear-gradient(135deg,#e53e3e,#c53030);color:#fff;border:none;border-radius:12px;font-size:14px;font-weight:900;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:8px;">
        &#x1F534; Mulai Live Streaming
      </button>
    </div>
    <div class="status-section-label">Live Sekarang</div>
    <div id="live-list">
      <div style="padding:24px;text-align:center;color:var(--st);font-size:13px;">Tidak ada siaran live saat ini &#x1F4FA;</div>
    </div>
  </div>

  <div class="sb-panel" id="panel-contacts">
    <div id="contacts-list"><div style="padding:28px;text-align:center;color:var(--st);font-size:14px;">Memuat...</div></div>
  </div>
</div>

<!-- MAIN PANEL -->
<div class="main" id="main-panel">
  <div class="no-chat" id="no-chat" style="display:flex;">
    <div class="no-chat-icon">&#x1F4AC;</div>
    <h2>WaClone</h2>
    <p>Pilih kontak untuk mulai chat &#x1F44B;</p>
    <div style="margin-top:16px;display:flex;gap:10px;flex-wrap:wrap;justify-content:center;">
      <button onclick="openAI()" style="padding:10px 20px;background:linear-gradient(135deg,#7c3aed,#9b5de5);color:#fff;border:none;border-radius:20px;font-size:14px;font-weight:800;cursor:pointer;font-family:'Nunito',sans-serif;">&#x1F916; Buka AI</button>
      <button onclick="switchTab('live')" style="padding:10px 20px;background:linear-gradient(135deg,#e53e3e,#c53030);color:#fff;border:none;border-radius:20px;font-size:14px;font-weight:800;cursor:pointer;font-family:'Nunito',sans-serif;">&#x1F534; Live</button>
      <button onclick="switchTab('status')" style="padding:10px 20px;background:var(--pn);color:var(--tx);border:1.5px solid var(--bd);border-radius:20px;font-size:14px;font-weight:800;cursor:pointer;font-family:'Nunito',sans-serif;">&#x1F7E2; Status</button>
    </div>
  </div>

  <div id="chat-wrap" style="display:none;flex-direction:column;height:100%;overflow:hidden;">
    <div class="chat-header" id="chat-header">
      <button id="back-btn" onclick="goBack()" style="display:none;flex-shrink:0;width:36px;height:36px;border:none;background:transparent;color:#e9edef;border-radius:50%;align-items:center;justify-content:center;cursor:pointer;">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M20 11H7.83l5.59-5.59L12 4l-8 8 8 8 1.41-1.41L7.83 13H20v-2z"/></svg>
      </button>
      <div id="header-av" onclick="showContactInfo()" style="width:40px;height:40px;border-radius:50%;overflow:hidden;flex-shrink:0;cursor:pointer;"></div>
      <div onclick="showContactInfo()" style="flex:1;min-width:0;overflow:hidden;cursor:pointer;">
        <div id="header-name" style="font-weight:900;font-size:15px;color:#e9edef;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">-</div>
        <div id="header-status" style="font-size:11px;color:#00a884;"></div>
      </div>
      <!-- VIDEO CALL BUTTON - FIXED always visible -->
      <button class="header-btn" id="btn-video-call" onclick="startAgoraCall('video')" title="Video Call">
        <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor">
          <path d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z"/>
        </svg>
      </button>
      <!-- AUDIO CALL BUTTON - FIXED always visible -->
      <button class="header-btn" id="btn-audio-call" onclick="startAgoraCall('audio')" title="Telepon">
        <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor">
          <path d="M6.62 10.79c1.44 2.83 3.76 5.14 6.59 6.59l2.2-2.2c.27-.27.67-.36 1.02-.24 1.12.37 2.33.57 3.57.57.55 0 1 .45 1 1V20c0 .55-.45 1-1 1-9.39 0-17-7.61-17-17 0-.55.45-1 1-1h3.5c.55 0 1 .45 1 1 0 1.25.2 2.45.57 3.57.11.35.03.74-.25 1.02l-2.2 2.2z"/>
        </svg>
      </button>
      <button class="header-btn" id="chat-more-btn" onclick="showChatMenu(this)" title="Lainnya">
        <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor">
          <path d="M12 8c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm0 2c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm0 6c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z"/>
        </svg>
      </button>
    </div>
    <div id="chat-more-menu" style="display:none;position:fixed;right:8px;top:62px;background:#202c33;border:1px solid #2a3942;border-radius:8px;box-shadow:0 4px 20px rgba(0,0,0,.5);z-index:999;min-width:160px;overflow:hidden;">
      <div onclick="openAI();this.parentElement.style.display='none'" style="padding:13px 18px;cursor:pointer;font-size:14px;color:#e9edef;" onmouseover="this.style.background='#2a3942'" onmouseout="this.style.background='transparent'">&#x1F916; Tanya AI</div>
      <div onclick="clearChatConfirm();this.parentElement.style.display='none'" style="padding:13px 18px;cursor:pointer;font-size:14px;color:#e9edef;" onmouseover="this.style.background='#2a3942'" onmouseout="this.style.background='transparent'">&#x1F5D1; Hapus Chat</div>
      <div onclick="searchInChat();this.parentElement.style.display='none'" style="padding:13px 18px;cursor:pointer;font-size:14px;color:#e9edef;" onmouseover="this.style.background='#2a3942'" onmouseout="this.style.background='transparent'">&#x1F50D; Cari Pesan</div>
    </div>
    <div class="messages-area" id="messages-area"></div>

    <div class="typing-wrap">
      <div class="typing-dots" id="typing-dots">
        <div class="dot-anim"><span></span><span></span><span></span></div>
        <span class="typing-text" id="typing-text"></span>
      </div>
    </div>

    <div class="att-menu" id="att-menu">
      <div class="att-opt" onclick="triggerFile('photo')"><div class="att-ic" style="background:#1a56db22;">&#x1F4F7;</div><span class="att-lbl">Foto/Video</span></div>
      <div class="att-opt" onclick="triggerFile('doc')"><div class="att-ic" style="background:#7c3aed22;">&#x1F4C4;</div><span class="att-lbl">Dokumen</span></div>
      <div class="att-opt" onclick="openCameraChat()"><div class="att-ic" style="background:#05966922;">&#x1F4F8;</div><span class="att-lbl">Kamera</span></div>
    </div>
    <input type="file" id="file-photo" style="display:none" accept="image/*,video/*" onchange="handleUpload(this)">
    <input type="file" id="file-doc" style="display:none" accept=".pdf,.txt,.doc,.docx,.xls,.xlsx,.zip,.rar" onchange="handleUpload(this)">

    <div class="emoji-picker" id="emoji-picker">
      <div class="emoji-grid" id="emoji-grid"></div>
    </div>

    <div class="upload-progress" id="upload-progress"><div class="upload-fill" id="upload-fill"></div></div>

    <div class="input-area" id="input-area">
      <div class="reply-preview" id="reply-preview">
        <div style="flex:1;min-width:0;">
          <div class="rp-name" id="rp-name"></div>
          <div class="rp-text" id="rp-text"></div>
        </div>
        <button class="rp-close" onclick="cancelReply()">&times;</button>
      </div>
      <div class="input-row">
        <button class="side-btn" onclick="toggleAttMenu()" title="Lampiran">
          <svg width="21" height="21" viewBox="0 0 24 24" fill="currentColor"><path d="M16.5 6v11.5c0 2.21-1.79 4-4 4s-4-1.79-4-4V5c0-1.38 1.12-2.5 2.5-2.5s2.5 1.12 2.5 2.5v10.5c0 .55-.45 1-1 1s-1-.45-1-1V6H10v9.5c0 1.38 1.12 2.5 2.5 2.5s2.5-1.12 2.5-2.5V5c0-2.21-1.79-4-4-4S7 2.79 7 5v12.5c0 3.04 2.46 5.5 5.5 5.5s5.5-2.46 5.5-5.5V6h-1.5z"/></svg>
        </button>
        <button class="side-btn" onclick="toggleEmojiPicker()" title="Emoji">&#x1F60A;</button>
        <textarea id="msg-input" class="msg-textarea" rows="1" placeholder="Ketik pesan..."
          onkeydown="handleMsgKey(event)" oninput="onMsgInput(this)"></textarea>
        <button class="rec-btn" id="rec-btn"
          onmousedown="startVoice()" onmouseup="stopVoice()"
          ontouchstart="startVoice(event)" ontouchend="stopVoice(event)" title="Tahan rekam suara">
          <svg width="19" height="19" viewBox="0 0 24 24" fill="currentColor"><path d="M12 14c1.66 0 2.99-1.34 2.99-3L15 5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.3-3c0 3-2.54 5.1-5.3 5.1S6.7 14 6.7 11H5c0 3.41 2.72 6.23 6 6.72V21h2v-3.28c3.28-.48 6-3.3 6-6.72h-1.7z"/></svg>
        </button>
        <button class="send-btn" onclick="sendMessage()" title="Kirim">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="white"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
        </button>
      </div>
    </div>
  </div>
</div>

<!-- CONTEXT MENU -->
<div class="ctx-menu" id="ctx-menu">
  <div class="ctx-item" onclick="doReply()">&#x21A9;&#xFE0F; Balas</div>
  <div class="ctx-item" onclick="doCopy()">&#x1F4CB; Salin</div>
  <div class="ctx-item" onclick="doForward()">&#x21AA;&#xFE0F; Teruskan</div>
  <div class="ctx-item" onclick="askAIAboutMsg()">&#x1F916; Tanya AI</div>
  <div class="ctx-item danger" onclick="doDelete()">&#x1F5D1;&#xFE0F; Hapus</div>
</div>

<!-- AI ASSISTANT DRAWER -->
<div class="ai-drawer" id="ai-drawer">
  <div class="ai-drawer-header">
    <div class="ai-avatar-icon">&#x1F916;</div>
    <div style="flex:1;">
      <div class="ai-drawer-title">WaClone AI</div>
      <div style="font-size:11px;color:rgba(224,212,255,.5);">Asisten pintarmu</div>
    </div>
    <div class="ai-online-dot"></div>
    <button class="ai-close" onclick="closeAI()">&times;</button>
  </div>
  <div class="ai-messages" id="ai-messages">
    <div class="ai-msg ai">
      <div class="ai-msg-av">&#x1F916;</div>
      <div class="ai-bubble">Halo! Saya <b>WaClone AI</b> &#x1F44B;<br><br>Saya bisa membantu:<br>&#x2022; Menulis atau menyempurnakan pesan<br>&#x2022; Menjawab pertanyaan apapun<br>&#x2022; Menerjemahkan teks<br>&#x2022; Memberi ide &amp; saran kreatif<br><br>Apa yang bisa saya bantu?</div>
    </div>
  </div>
  <div class="ai-chips" id="ai-chips">
    <div class="ai-chip" onclick="sendAIMsg('Bantu saya menulis pesan yang baik untuk teman')">&#x270D;&#xFE0F; Tulis pesan</div>
    <div class="ai-chip" onclick="sendAIMsg('Buat lelucon lucu yang bisa dikirim ke teman')">&#x1F602; Lelucon</div>
    <div class="ai-chip" onclick="sendAIMsg('Apa tips berkomunikasi yang baik?')">&#x1F4A1; Tips chat</div>
    <div class="ai-chip" onclick="sendAIMsg('Terjemahkan ke bahasa Inggris: Halo, apa kabar?')">&#x1F310; Terjemah</div>
  </div>
  <div class="ai-input-row">
    <textarea class="ai-textarea" id="ai-input" rows="1" placeholder="Tanya AI apapun..."
      onkeydown="handleAIKey(event)" oninput="autoResizeAI(this)"></textarea>
    <button class="ai-send-btn" onclick="sendAIFromInput()">
      <svg width="17" height="17" viewBox="0 0 24 24" fill="white"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
    </button>
  </div>
</div>

<!-- OVERLAYS -->
<div class="overlay" id="prof-ov">
  <div class="panel">
    <div class="panel-header"><h2>&#x1F464; Profil Saya</h2><button class="close-btn" onclick="closePanel('prof-ov')">&times;</button></div>
    <div class="panel-body">
      <div class="pav-wrap">
        <div class="pav-big" id="pav-big" onclick="document.getElementById('avatar-input').click()">__PROFILE_AV__</div>
        <div class="pav-edit-btn" onclick="document.getElementById('avatar-input').click()">&#x1F4F7;</div>
        <input type="file" id="avatar-input" style="display:none" accept="image/*,image/heic,image/heif" onchange="uploadAvatar(this)">
      </div>
      <div class="prof-name" id="pname">__USERNAME__</div>
      <div class="prof-email">__EMAIL__</div>
      <div style="margin-top:16px;">
        <div class="field-group"><label>Username</label><input id="edit-username" value="__USERNAME__" placeholder="username baru"></div>
        <div class="field-group"><label>Bio / Status</label><textarea id="edit-bio">__BIO__</textarea></div>
      </div>
      <button class="save-btn" onclick="saveProfile()">&#x1F4BE; Simpan Profil</button>
      <button class="logout-btn" onclick="doLogout()">&#x1F6AA; Logout</button>
    </div>
  </div>
</div>

<!-- SETTINGS PANEL -->
<div class="overlay" id="settings-ov">
  <div class="panel" style="width:440px;">
    <div class="panel-header"><h2>&#x2699;&#xFE0F; Pengaturan</h2><button class="close-btn" onclick="closePanel('settings-ov')">&times;</button></div>
    <div class="panel-body">
      <div class="settings-section">
        <h3>&#x1F514; Notifikasi</h3>
        <div class="settings-row">
          <div><div class="settings-label">Notifikasi Pesan</div><div class="settings-desc">Tampilkan notifikasi saat pesan baru masuk</div></div>
          <label class="toggle-switch"><input type="checkbox" id="set-notif" checked onchange="saveSetting('notif',this.checked)"><span class="toggle-slider"></span></label>
        </div>
        <div class="settings-row">
          <div><div class="settings-label">Suara Notifikasi</div></div>
          <label class="toggle-switch"><input type="checkbox" id="set-sound" checked onchange="saveSetting('sound',this.checked)"><span class="toggle-slider"></span></label>
        </div>
      </div>
      <div class="settings-section">
        <h3>&#x1F512; Privasi</h3>
        <div class="settings-row">
          <div><div class="settings-label">Tampilkan Status Online</div></div>
          <label class="toggle-switch"><input type="checkbox" id="set-show-online" checked onchange="saveSetting('show_online',this.checked)"><span class="toggle-slider"></span></label>
        </div>
        <div class="settings-row">
          <div><div class="settings-label">Tanda Baca Pesan</div></div>
          <label class="toggle-switch"><input type="checkbox" id="set-read-receipt" checked onchange="saveSetting('read_receipt',this.checked)"><span class="toggle-slider"></span></label>
        </div>
      </div>
      <div class="settings-section">
        <h3>&#x1F4AC; Chat</h3>
        <div class="settings-row">
          <div><div class="settings-label">Enter untuk Kirim</div></div>
          <label class="toggle-switch"><input type="checkbox" id="set-enter-send" checked onchange="saveSetting('enter_send',this.checked)"><span class="toggle-slider"></span></label>
        </div>
        <div class="settings-row">
          <div><div class="settings-label">Ukuran Font</div></div>
          <select id="set-font-size" onchange="applyFontSize(this.value);saveSetting('font_size',this.value)" style="width:auto;padding:6px 10px;font-size:12px;">
            <option value="13">Kecil</option>
            <option value="15" selected>Normal</option>
            <option value="17">Besar</option>
          </select>
        </div>
      </div>
      <div class="settings-section">
        <h3>&#x1F4DE; Panggilan (Agora)</h3>
        <div class="settings-row">
          <div><div class="settings-label">Kamera Default Depan</div></div>
          <label class="toggle-switch"><input type="checkbox" id="set-front-cam" checked onchange="saveSetting('front_cam',this.checked)"><span class="toggle-slider"></span></label>
        </div>
        <div class="settings-row">
          <div><div class="settings-label">Auto Speaker Video Call</div></div>
          <label class="toggle-switch"><input type="checkbox" id="set-auto-spk" checked onchange="saveSetting('auto_spk',this.checked)"><span class="toggle-slider"></span></label>
        </div>
      </div>
      <div class="settings-section">
        <h3>&#x1F5C4;&#xFE0F; Data</h3>
        <div class="settings-row">
          <div><div class="settings-label">Hapus Cache Lokal</div></div>
          <button class="settings-btn" onclick="clearLocalCache()">&#x1F5D1;&#xFE0F; Hapus</button>
        </div>
        <div class="settings-row">
          <div><div class="settings-label">Versi Aplikasi</div></div>
          <span style="font-size:12px;color:var(--g);font-weight:700;">v3.0 + Agora</span>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- Notifications -->
<div class="overlay" id="notif-ov">
  <div class="panel">
    <div class="panel-header"><h2>&#x1F514; Notifikasi</h2><button class="close-btn" onclick="closePanel('notif-ov');markNotifsRead()">&times;</button></div>
    <div class="panel-body" id="notif-list"></div>
  </div>
</div>

<!-- Status Viewer -->
<div class="overlay" id="stview-ov">
  <div class="stv" id="stv-wrap">
    <div class="stv-progress" id="stv-progress"></div>
    <div class="stv-head">
      <div class="stv-av" id="stv-av"></div>
      <div style="flex:1;">
        <div style="font-weight:800;font-size:14px;color:#fff;" id="stv-name"></div>
        <div style="font-size:11px;color:rgba(255,255,255,.5);" id="stv-time"></div>
      </div>
      <button class="close-btn" onclick="closeStatusViewer()" style="background:rgba(255,255,255,.1);color:rgba(255,255,255,.7);">&times;</button>
    </div>
    <div class="stv-body" id="stv-body"></div>
    <div class="stv-nav-btns">
      <button class="stv-nav-btn" id="stv-prev-btn" onclick="prevStatus()">&#x25C0; Prev</button>
      <button class="stv-nav-btn" id="stv-next-btn" onclick="nextStatus()">Next &#x25B6;</button>
    </div>
  </div>
</div>

<!-- Create Status -->
<div class="overlay" id="cstat-ov">
  <div class="panel">
    <div class="panel-header"><h2>&#x270F;&#xFE0F; Buat Status</h2><button class="close-btn" onclick="closePanel('cstat-ov')">&times;</button></div>
    <div class="panel-body">
      <div class="create-opts">
        <div class="create-opt" onclick="showTextStatusForm()">
          <div class="create-opt-ic" style="background:#2563eb22;">&#x270F;&#xFE0F;</div>
          <div><div style="font-weight:800;">Teks</div><div style="font-size:12px;color:var(--st);">Tulis status teks</div></div>
        </div>
        <div class="create-opt" onclick="document.getElementById('stat-photo-in').click()">
          <div class="create-opt-ic" style="background:#dc262622;">&#x1F5BC;&#xFE0F;</div>
          <div><div style="font-weight:800;">Foto</div></div>
        </div>
        <div class="create-opt" onclick="document.getElementById('stat-video-in').click()">
          <div class="create-opt-ic" style="background:#7c3aed22;">&#x1F3A5;</div>
          <div><div style="font-weight:800;">Video</div></div>
        </div>
      </div>
      <input type="file" id="stat-photo-in" accept="image/*,image/heic,image/heif" style="display:none" onchange="uploadStatus(this,'image')">
      <input type="file" id="stat-video-in" accept="video/*" style="display:none" onchange="uploadStatus(this,'video')">
      <div id="text-stat-form" style="display:none;margin-top:14px;">
        <div class="field-group">
          <label>Teks Status</label>
          <textarea id="stat-text-inp" placeholder="Tulis status kamu..." style="height:88px;" maxlength="200"></textarea>
        </div>
        <button class="save-btn" onclick="postTextStatus()">&#x1F4E4; Posting Status</button>
      </div>
    </div>
  </div>
</div>

<!-- Camera -->
<div class="overlay" id="cam-ov">
  <div class="panel" style="width:420px;">
    <div class="panel-header"><h2>&#x1F4F7; Kamera</h2><button class="close-btn" onclick="closeCamera()">&times;</button></div>
    <div class="panel-body">
      <div class="cam-wrap"><video id="cam-vid" autoplay playsinline muted></video></div>
      <canvas id="cam-canvas" style="display:none;width:100%;border-radius:10px;margin-top:8px;"></canvas>
      <div class="cam-controls">
        <button class="cam-btn" style="background:var(--g);" onclick="snapPhoto()">&#x1F4F8;</button>
        <button class="cam-btn" style="background:#2a3942;" onclick="switchCamFacing()">&#x1F504;</button>
        <button class="cam-btn" style="background:var(--rd);" onclick="closeCamera()">&times;</button>
      </div>
      <div id="cam-send-wrap" style="display:none;margin-top:10px;">
        <button class="save-btn" onclick="sendCamPhoto()">&#x1F4E4; Kirim Foto</button>
      </div>
    </div>
  </div>
</div>

<!-- Forward -->
<div class="overlay" id="fw-ov">
  <div class="panel">
    <div class="panel-header"><h2>&#x21AA;&#xFE0F; Teruskan Pesan</h2><button class="close-btn" onclick="closePanel('fw-ov')">&times;</button></div>
    <div class="panel-body">
      <div class="fw-list" id="fw-list"></div>
      <button class="save-btn" id="fw-send-btn" style="display:none;margin-top:12px;" onclick="execForward()">&#x1F4E4; Kirim</button>
    </div>
  </div>
</div>

<!-- Image fullscreen -->
<div class="overlay" id="img-ov" onclick="closePanel('img-ov')">
  <img class="img-fullview" id="img-full" src="" alt="">
</div>

<!-- ====== AGORA CALL UI ====== -->
<div class="call-ui" id="call-ui">
  <div class="call-video-grid" id="call-video-grid" style="display:none;">
    <div id="agora-remote-container">
      <div style="color:rgba(255,255,255,.4);font-size:14px;text-align:center;">
        <div style="font-size:48px;margin-bottom:8px;">&#x1F464;</div>
        Menunggu video...
      </div>
    </div>
    <div id="agora-local-container"></div>
  </div>
  <div class="audio-call-info" id="audio-call-info" style="display:flex;">
    <div class="call-person-av" id="call-av">&#x1F464;</div>
    <div class="call-name" id="call-name">&#x2014;</div>
    <div class="call-status-txt" id="call-status-txt">Memanggil...</div>
    <div class="call-timer" id="call-timer">00:00</div>
  </div>
  <div class="call-controls">
    <div style="display:flex;flex-direction:column;align-items:center;gap:2px;">
      <button class="call-cbtn cbtn-toggle cbtn-on" id="cbtn-mic" onclick="agoraToggleMic()">&#x1F3A4;</button>
      <span style="font-size:10px;color:rgba(255,255,255,.5);">Mic</span>
    </div>
    <div style="display:flex;flex-direction:column;align-items:center;gap:2px;" id="cam-ctrl-wrap">
      <button class="call-cbtn cbtn-toggle cbtn-on" id="cbtn-cam" onclick="agoraToggleCam()">&#x1F4F7;</button>
      <span style="font-size:10px;color:rgba(255,255,255,.5);">Kamera</span>
    </div>
    <div style="display:flex;flex-direction:column;align-items:center;gap:2px;">
      <button class="call-cbtn cbtn-end" onclick="agoraEndCall()">&#x1F4F5;</button>
      <span style="font-size:10px;color:rgba(255,255,255,.5);">Tutup</span>
    </div>
    <div style="display:flex;flex-direction:column;align-items:center;gap:2px;">
      <button class="call-cbtn cbtn-toggle cbtn-on" id="cbtn-spk" onclick="agoraToggleSpeaker()">&#x1F50A;</button>
      <span style="font-size:10px;color:rgba(255,255,255,.5);">Speaker</span>
    </div>
  </div>
</div>

<!-- Incoming call -->
<div class="incoming-call" id="incoming-call">
  <div class="inc-av" id="inc-av">&#x1F464;</div>
  <div style="text-align:center;font-size:17px;font-weight:900;" id="inc-name">&#x2014;</div>
  <div class="inc-type-badge" id="inc-type">&#x1F4DE; Panggilan Masuk</div>
  <div class="inc-actions">
    <button class="inc-btn inc-audio" onclick="answerAgoraCall('audio')">&#x1F4DE; Audio</button>
    <button class="inc-btn inc-video" onclick="answerAgoraCall('video')">&#x1F4F9; Video</button>
    <button class="inc-btn inc-reject" onclick="rejectAgoraCall()">&#x1F4F5;</button>
  </div>
</div>

<!-- ====== LIVE STREAMING UI ====== -->
<div class="live-ui" id="live-ui">
  <div class="live-header">
    <div style="display:flex;align-items:center;gap:10px;">
      <div class="live-badge" id="live-badge">&#x25CF; LIVE</div>
      <div class="live-viewer-count" id="live-viewer-count">&#x1F441; 0 penonton</div>
    </div>
    <div style="display:flex;align-items:center;gap:8px;">
      <span id="live-streamer-name" style="color:#fff;font-size:14px;font-weight:700;"></span>
      <button onclick="closeLiveUI()" style="background:rgba(255,255,255,.15);border:none;color:#fff;width:32px;height:32px;border-radius:50%;font-size:18px;cursor:pointer;">&times;</button>
    </div>
  </div>
  <div class="live-video-area" id="live-video-area">
    <div id="live-local-video"></div>
    <div id="live-remote-video"></div>
    <div class="live-comments" id="live-comments"></div>
    <div class="live-viewers-panel" id="live-viewers-panel" style="display:none;"></div>
  </div>
  <div class="live-controls-bottom">
    <input type="text" class="live-comment-input" id="live-comment-input"
      placeholder="Tulis komentar..." onkeydown="if(event.key==='Enter')sendLiveComment()">
    <button class="live-send-comment" onclick="sendLiveComment()">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="white"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
    </button>
    <button onclick="toggleLiveViewers()" style="padding:9px 14px;background:rgba(255,255,255,.15);border:none;color:#fff;border-radius:20px;font-size:13px;font-weight:700;cursor:pointer;">&#x1F465;</button>
    <button id="live-end-btn" onclick="endLiveStream()" class="live-end-btn" style="display:none;">&#x23F9; Akhiri</button>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
// ============================================================
// CONFIG
// ============================================================
const AGORA_APP_ID = "__AGORA_APP_ID__";
const SUPABASE_PROJECT = "__SUPABASE_PROJECT__";
const ME = { uid: "__UID__", username: "__USERNAME__" };
const EMOJIS = ['&#x1F600;','&#x1F602;','&#x1F60D;','&#x1F970;','&#x1F60E;','&#x1F914;','&#x1F62D;','&#x1F621;','&#x1F44D;','&#x1F44E;','&#x2764;&#xFE0F;','&#x1F525;','&#x2705;','&#x2B50;','&#x1F389;','&#x1F64F;',
  '&#x1F4AA;','&#x1F634;','&#x1F923;','&#x1F60A;','&#x1F618;','&#x1F917;','&#x1F97A;','&#x1F605;','&#x1F62C;','&#x1F919;','&#x1F480;','&#x1F48B;','&#x1FAC2;','&#x1F31F;','&#x1F4AF;','&#x1F38A;',
  '&#x1F929;','&#x1F631;','&#x1F92F;','&#x1FAE1;','&#x1F973;','&#x1F624;','&#x1FAF6;','&#x1F44B;','&#x1F64C;','&#x1F440;','&#x1F3B5;','&#x1F308;','&#x1F355;','&#x2615;','&#x1F680;','&#x1F4A1;',
  '&#x1F3AF;','&#x1F3C6;','&#x1F48E;','&#x1F338;','&#x1F98B;','&#x1F319;','&#x2600;&#xFE0F;','&#x1F30A;','&#x1F340;','&#x1F436;','&#x1F431;','&#x1F981;','&#x1F43B;','&#x1F98A;','&#x1F428;','&#x1F43C;'];

let allUsers=[], currentFriend=null, pollTimer=null;
let replyData=null, ctxMsgData=null;
let mediaRecorder=null, recChunks=[], isRecording=false;
let callTimerInt=null, callSecs=0, micMuted=false, camOff=false, speakerOff=false;
let incCallInfo=null;
let camStream=null, camFacing='user', camMode='chat', camPhotoBlob=null;
let stvData=null, stvIdx=0, stvTimerInt=null;
let fwText='', fwTargetUid=null;
let lastTypingPing=0;
let aiHistory=[];

// ====== AGORA CALL STATE ======
let agoraClient=null, agoraLocalAudioTrack=null, agoraLocalVideoTrack=null;
let agoraCallType='audio', agoraCurrentCallId=null;

// ====== AGORA LIVE STATE ======
let agoraLiveClient=null, agoraLiveLocalVideoTrack=null, agoraLiveLocalAudioTrack=null;
let isLiveHost=false, liveChannelName='', liveViewers=[], liveCommentPollTimer=null;
let currentLiveData=null;

let appSettings = {
  notif:true, sound:true, show_online:true, read_receipt:true,
  typing:true, font_size:'15', enter_send:true, front_cam:true, auto_spk:true
};

// ============================================================
// UTILS
// ============================================================
function toast(msg,dur=2500,isErr=false){
  const t=document.getElementById('toast');
  t.textContent=msg;t.className='toast show'+(isErr?' err':'');
  setTimeout(()=>t.classList.remove('show'),dur);
}
function escHtml(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function fmtTime(ts){
  const d=new Date(ts*1000),now=new Date();
  if(d.toDateString()===now.toDateString())return d.getHours().toString().padStart(2,'0')+':'+d.getMinutes().toString().padStart(2,'0');
  const diff=Math.floor((now-d)/86400000);
  if(diff===1)return'Kemarin';
  if(diff<7)return['Min','Sen','Sel','Rab','Kam','Jum','Sab'][d.getDay()];
  return d.getDate()+'/'+(d.getMonth()+1);
}
function makeAv(u,size=48){
  if(u&&u.avatar)return`<img src="${u.avatar}" style="width:${size}px;height:${size}px;border-radius:50%;object-fit:cover;" onerror="this.style.display='none'">`;
  const n=(u&&u.username)?u.username:'?';
  const pal=['#00a884','#7c3aed','#1a56db','#dc2626','#d97706','#059669','#0891b2','#be185d'];
  const bg=pal[(n.charCodeAt(0)||0)%pal.length];
  const fs=Math.floor(size*0.42);
  return`<div style="width:${size}px;height:${size}px;border-radius:50%;background:${bg};display:flex;align-items:center;justify-content:center;font-weight:900;font-size:${fs}px;color:#fff;flex-shrink:0;">${n[0].toUpperCase()}</div>`;
}

// ============================================================
// SETTINGS
// ============================================================
function loadSettings(){
  try{
    const saved=JSON.parse(localStorage.getItem('waclone_settings')||'{}');
    Object.assign(appSettings,saved);
    ['notif','sound','show-online','read-receipt','typing','enter-send','front-cam','auto-spk'].forEach(k=>{
      const el=document.getElementById('set-'+k);
      if(el)el.checked=!!appSettings[k.replace('-','_')];
    });
    const fs=document.getElementById('set-font-size');
    if(fs)fs.value=appSettings.font_size||'15';
    applyFontSize(appSettings.font_size||'15');
  }catch(e){}
}
function saveSetting(key,value){appSettings[key]=value;try{localStorage.setItem('waclone_settings',JSON.stringify(appSettings));}catch(e){}}
function applyFontSize(size){document.querySelectorAll('.bubble,.ai-bubble').forEach(el=>el.style.fontSize=size+'px');}
function clearLocalCache(){try{const k=localStorage.getItem('waclone_settings');localStorage.clear();if(k)localStorage.setItem('waclone_settings',k);toast('Cache dibersihkan \u2705');}catch(e){toast('Gagal hapus cache',2500,true);}}

// ============================================================
// PANELS & TABS
// ============================================================
function openPanel(id){document.getElementById(id).classList.add('open');}
function closePanel(id){document.getElementById(id).classList.remove('open');}
function openNotifPanel(){openPanel('notif-ov');loadNotifications();}
function switchTab(tab){
  ['chats','status','live','contacts'].forEach(t=>{
    const tb=document.getElementById('tab-'+t);
    const pn=document.getElementById('panel-'+t);
    if(tb)tb.classList.toggle('active',t===tab);
    if(pn)pn.classList.toggle('active',t===tab);
  });
  document.getElementById('search-wrap-el').style.display=(tab==='status'||tab==='live')?'none':'';
  if(tab==='status')loadSidebarStatuses();
  if(tab==='live')loadLiveList();
}
function closeAllMenus(){
  document.getElementById('att-menu').classList.remove('open');
  document.getElementById('emoji-picker').classList.remove('open');
  document.getElementById('ctx-menu').style.display='none';
}

// ============================================================
// USERS
// ============================================================
async function loadUsers(){
  try{const r=await fetch('/api/users');const d=await r.json();allUsers=d.users||[];renderChatList();renderContactsList();checkNotifCount();}catch(e){}
}
function renderChatList(){
  const el=document.getElementById('chat-list');
  const others=allUsers.filter(u=>u.uid!==ME.uid);
  if(!others.length){el.innerHTML='<div style="padding:28px;text-align:center;color:var(--st);font-size:14px;">Belum ada pengguna &#x1F465;</div>';return;}
  el.innerHTML=others.map(u=>chatItemHtml(u)).join('');
}
function renderContactsList(){
  const el=document.getElementById('contacts-list');
  const sorted=[...allUsers.filter(u=>u.uid!==ME.uid)].sort((a,b)=>a.username.localeCompare(b.username));
  if(!sorted.length){el.innerHTML='<div style="padding:28px;text-align:center;color:var(--st);">Tidak ada kontak</div>';return;}
  el.innerHTML=sorted.map(u=>chatItemHtml(u,true)).join('');
}
function chatItemHtml(u,isContact=false){
  const av=makeAv(u,48);
  const onlineDot=u.online?'<div class="online-dot"></div>':'';
  const preview=escHtml((isContact?(u.bio||'Tap untuk chat'):(u.last_msg||u.bio||'Tap untuk chat')).substring(0,40));
  const tm=u.last_time?fmtTime(u.last_time):'';
  const badge=u.unread_count>0?`<div class="unread-badge">${u.unread_count>99?'99+':u.unread_count}</div>`:'';
  const isActive=currentFriend&&currentFriend.uid===u.uid;
  const sUname=(u.username||'').replace(/\\/g,'\\\\').replace(/'/g,"\\'");
  const sAvatar=(u.avatar||'').replace(/\\/g,'\\\\').replace(/'/g,"\\'");
  const sBio=(u.bio||'').replace(/\\/g,'\\\\').replace(/'/g,"\\'");
  return`<div class="chat-item${isActive?' active':''}" data-uid="${u.uid}" data-name="${escHtml(u.username)}"
    onclick="openChat('${u.uid}','${sUname}','${sAvatar}','${sBio}')">
    <div class="chat-av">${av}${onlineDot}</div>
    <div class="chat-info"><div class="chat-name">${escHtml(u.username)}</div><div class="chat-prev">${preview}</div></div>
    <div class="chat-meta"><div class="chat-time">${tm}</div>${badge}</div>
  </div>`;
}
function filterList(q){
  const q2=q.toLowerCase();
  document.querySelectorAll('.chat-item').forEach(el=>{el.style.display=el.dataset.name.toLowerCase().includes(q2)?'':'none';});
}

// ============================================================
// OPEN CHAT
// ============================================================
function openChat(uid,name,avatar,bio){
  currentFriend={uid,name,avatar,bio};
  document.getElementById('no-chat').style.display='none';
  const cw=document.getElementById('chat-wrap');cw.style.display='flex';
  if(window.innerWidth<=700)document.getElementById('sidebar').classList.add('hidden');
  document.getElementById('header-av').innerHTML=makeAv(currentFriend,40);
  document.getElementById('header-name').textContent=name;
  document.getElementById('header-status').textContent='Memuat...';
  document.querySelectorAll('.chat-item').forEach(e=>e.classList.toggle('active',e.dataset.uid===uid));
  cancelReply();closeAllMenus();
  loadMessages();
  if(pollTimer)clearInterval(pollTimer);
  pollTimer=setInterval(()=>{loadMessages();checkTyping();},3000);
  fetch('/api/mark_read',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({friend_uid:uid})});
  setTimeout(()=>document.getElementById('msg-input').focus(),100);
}
function showChatMenu(btn){
  const menu=document.getElementById('chat-more-menu');
  if(menu.style.display==='block'){menu.style.display='none';return;}
  const rect=btn.getBoundingClientRect();
  menu.style.display='block';
  menu.style.top=(rect.bottom+4)+'px';
  menu.style.right=(window.innerWidth-rect.right)+'px';
  menu.style.left='auto';
  setTimeout(()=>document.addEventListener('click',()=>menu.style.display='none',{once:true}),50);
}
function showContactInfo(){if(!currentFriend)return;const u=allUsers.find(x=>x.uid===currentFriend.uid);toast((u?.username||currentFriend.name)+' \u2014 '+(u?.bio||'No bio'),3000);}
function clearChatConfirm(){if(!currentFriend)return;if(confirm('Hapus semua pesan?'))toast('Fitur hapus chat segera hadir!',2000);}
function searchInChat(){
  const q=prompt('Cari teks:');if(!q)return;
  let found=0;
  document.querySelectorAll('.bubble span').forEach(el=>{
    const txt=el.textContent||'';
    el.parentElement.style.outline=txt.toLowerCase().includes(q.toLowerCase())?'2px solid var(--g)':'none';
    if(txt.toLowerCase().includes(q.toLowerCase()))found++;
  });
  toast(found>0?found+' pesan ditemukan':'Tidak ditemukan',2000,found===0);
}
function goBack(){
  const openOverlays=[...document.querySelectorAll('.overlay.open')];
  if(openOverlays.length>0){openOverlays[openOverlays.length-1].classList.remove('open');if(openOverlays[openOverlays.length-1].id==='stview-ov')clearStvTimer();return;}
  if(document.getElementById('ai-drawer').classList.contains('open')){document.getElementById('ai-drawer').classList.remove('open');return;}
  if(currentFriend){
    document.getElementById('sidebar').classList.remove('hidden');
    document.getElementById('chat-wrap').style.display='none';
    document.getElementById('no-chat').style.display='flex';
    currentFriend=null;
    if(pollTimer){clearInterval(pollTimer);pollTimer=null;}
  }
}

// ============================================================
// MESSAGES
// ============================================================
async function loadMessages(){
  if(!currentFriend)return;
  try{
    const r=await fetch(`/api/messages?friend_uid=${currentFriend.uid}`);
    const d=await r.json();
    renderMessages(d.messages||[]);
    const f=allUsers.find(u=>u.uid===currentFriend.uid);
    if(f){
      const st=document.getElementById('header-status');
      st.textContent=f.online?'\u{1F7E2} Online':(f.last_seen?`Terakhir ${fmtTime(f.last_seen)}`:'\u26AB Offline');
    }
  }catch(e){}
}
function renderMessages(msgs){
  const area=document.getElementById('messages-area');
  const atBottom=area.scrollHeight-area.clientHeight<=area.scrollTop+120;
  if(!msgs.length){area.innerHTML='<div style="text-align:center;color:var(--st);padding:36px;font-size:13px;">Belum ada pesan. Mulai percakapan! &#x1F44B;</div>';return;}
  let html='',lastDate='';
  msgs.forEach(m=>{
    const d=new Date(m.time*1000);
    const ds=d.toLocaleDateString('id-ID',{day:'2-digit',month:'long',year:'numeric'});
    if(ds!==lastDate){html+=`<div class="date-divider"><span>${ds}</span></div>`;lastDate=ds;}
    const isOut=m.from===ME.uid;
    const ts=d.getHours().toString().padStart(2,'0')+':'+d.getMinutes().toString().padStart(2,'0');
    let tick='';
    if(isOut){
      const dbl='<svg viewBox="0 0 16 11" width="16" height="11"><path d="M15.01 3.316l-.478-.372a.365.365 0 0 0-.51.063L8.666 9.88a.32.32 0 0 1-.484.032l-.358-.325a.32.32 0 0 0-.484.032l-.378.48a.418.418 0 0 0 .036.541l1.316 1.266c.143.14.361.125.484-.033l6.272-8.048a.366.366 0 0 0-.064-.512z" fill="currentColor"/><path d="M7.434 4.814l-4.405 5.026-.655-.63L7.434 4.814z" fill="currentColor"/></svg>';
      const sgl='<svg viewBox="0 0 12 11" width="12" height="11"><path d="M11.01 3.316l-.478-.372a.365.365 0 0 0-.51.063L4.666 9.88a.32.32 0 0 1-.484.032l-2.36-2.342a.32.32 0 0 0-.484.032l-.378.48a.418.418 0 0 0 .036.541l2.956 2.921c.143.14.361.125.484-.033l6.272-8.048a.366.366 0 0 0-.064-.512z" fill="currentColor"/></svg>';
      if(m.status==='read')tick='<span class="tick read">'+dbl+'</span>';
      else if(m.status==='delivered')tick='<span class="tick">'+dbl+'</span>';
      else tick='<span class="tick">'+sgl+'</span>';
    }
    let rqHtml='';
    if(m.reply_to&&m.reply_to.text){
      const rs=m.reply_to.from===ME.uid?'Kamu':(currentFriend?currentFriend.name:'?');
      rqHtml=`<div class="reply-quote"><div class="rq-name">${escHtml(rs)}</div><div class="rq-text">${escHtml(m.reply_to.text)}</div></div>`;
    }
    let content='';
    if(m.file){
      const ft=m.file_type||'';
      if(ft.startsWith('image/')||/\.(jpg|jpeg|png|gif|webp|bmp|heic|heif)$/i.test(m.file))
        content+=`<img src="${m.file}" onclick="viewImg('${m.file}')" loading="lazy" alt="foto">`;
      else if(ft.startsWith('video/')||/\.(mp4|webm|mov|avi|mkv)$/i.test(m.file))
        content+=`<video src="${m.file}" controls style="max-width:250px;border-radius:8px;display:block;margin-bottom:3px;"></video>`;
      else if(ft.startsWith('audio/')||/\.(ogg|m4a|wav|mp3|webm)$/i.test(m.file))
        content+=`<audio src="${m.file}" controls></audio>`;
      else{const fn=m.file.split('/').pop().split('?')[0].substring(0,30);content+=`<a class="file-link" href="${m.file}" target="_blank">&#x1F4C4; ${escHtml(fn)}</a>`;}
    }
    if(m.message)content+=`<span>${escHtml(m.message)}</span>`;
    const safeTxt=(m.message||'').replace(/"/g,'&quot;').replace(/'/g,'&#39;').replace(/\\/g,'\\\\');
    const acts=`<div class="msg-actions">
      <button class="act-btn" onclick='setReply("${m.id}","${safeTxt}","${m.from}")' title="Balas">&#x21A9;</button>
      <button class="act-btn" onclick='showCtxMenu(event,"${m.id}","${safeTxt}","${m.from}")' title="Lebih">&#x22EF;</button>
    </div>`;
    html+=`<div class="msg-row ${isOut?'out':'in'}" data-id="${m.id}" data-txt="${safeTxt}" data-from="${m.from}"
      oncontextmenu='showCtxMenu(event,"${m.id}","${safeTxt}","${m.from}")'
      ontouchstart='touchStart(event,"${m.id}","${safeTxt}","${m.from}")'
      ontouchend='touchEnd()'>
      ${isOut?acts:''}
      <div class="bubble">${rqHtml}${content}<div class="bubble-time">${ts} ${tick}</div></div>
      ${!isOut?acts:''}
    </div>`;
  });
  area.innerHTML=html;
  if(atBottom)area.scrollTop=area.scrollHeight;
}

// ============================================================
// SEND MESSAGE
// ============================================================
function handleMsgKey(e){if(e.key==='Enter'&&!e.shiftKey&&appSettings.enter_send){e.preventDefault();sendMessage();}}
function onMsgInput(el){el.style.height='auto';el.style.height=Math.min(el.scrollHeight,120)+'px';pingTyping();}
async function sendMessage(){
  const inp=document.getElementById('msg-input');const text=inp.value.trim();
  if(!text||!currentFriend)return;
  inp.value='';inp.style.height='auto';
  const body={to_uid:currentFriend.uid,message:text};
  if(replyData)body.reply_to={id:replyData.id,text:replyData.text,from:replyData.from};
  cancelReply();
  try{const r=await fetch('/api/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});const d=await r.json();if(d.ok)loadMessages();else toast('Gagal kirim',2500,true);}
  catch(e){toast('Gagal kirim',2500,true);}
}

// ============================================================
// REPLY
// ============================================================
function cancelReply(){replyData=null;document.getElementById('reply-preview').classList.remove('show');}
function setReply(id,txt,from){
  const decoded=txt.replace(/&#39;/g,"'").replace(/&quot;/g,'"');
  replyData={id,text:decoded,from};
  const name=from===ME.uid?'Kamu':(currentFriend?currentFriend.name:'?');
  document.getElementById('rp-name').textContent=name;
  document.getElementById('rp-text').textContent=decoded||'Media';
  document.getElementById('reply-preview').classList.add('show');
  document.getElementById('msg-input').focus();
}

// ============================================================
// CONTEXT MENU
// ============================================================
let touchTimer=null;
function showCtxMenu(e,id,txt,from){e.preventDefault();e.stopPropagation();ctxMsgData={id,txt:txt.replace(/&#39;/g,"'").replace(/&quot;/g,'"'),from};posCtx(e.clientX,e.clientY);}
function posCtx(x,y){const m=document.getElementById('ctx-menu');m.style.display='block';const mw=m.offsetWidth||180,mh=m.offsetHeight||200;m.style.left=Math.min(x,window.innerWidth-mw-8)+'px';m.style.top=Math.min(y,window.innerHeight-mh-8)+'px';setTimeout(()=>document.addEventListener('click',()=>m.style.display='none',{once:true}),50);}
function touchStart(e,id,txt,from){touchTimer=setTimeout(()=>{ctxMsgData={id,txt:txt.replace(/&#39;/g,"'"),from};posCtx(e.touches[0].clientX,e.touches[0].clientY);},600);}
function touchEnd(){if(touchTimer){clearTimeout(touchTimer);touchTimer=null;}}
function doReply(){if(!ctxMsgData)return;setReply(ctxMsgData.id,ctxMsgData.txt,ctxMsgData.from);document.getElementById('ctx-menu').style.display='none';}
function doCopy(){if(!ctxMsgData)return;navigator.clipboard.writeText(ctxMsgData.txt).then(()=>toast('Disalin \u{1F4CB}'));document.getElementById('ctx-menu').style.display='none';}
function doForward(){
  if(!ctxMsgData)return;fwText=ctxMsgData.txt;fwTargetUid=null;
  document.getElementById('fw-list').innerHTML=allUsers.filter(u=>u.uid!==ME.uid).map(u=>
    `<div class="fw-item" id="fw-${u.uid}" onclick="selFw('${u.uid}')"><div class="fw-av">${makeAv(u,36)}</div><span style="font-weight:700;">${escHtml(u.username)}</span></div>`
  ).join('');
  document.getElementById('fw-send-btn').style.display='none';
  openPanel('fw-ov');document.getElementById('ctx-menu').style.display='none';
}
function askAIAboutMsg(){
  if(!ctxMsgData)return;const msg=ctxMsgData.txt;
  document.getElementById('ctx-menu').style.display='none';openAI();
  setTimeout(()=>{const inp=document.getElementById('ai-input');inp.value=`Tolong bantu saya membalas pesan ini: "${msg}"`;autoResizeAI(inp);},300);
}
function selFw(uid){document.querySelectorAll('.fw-item').forEach(e=>e.classList.remove('sel'));document.getElementById('fw-'+uid).classList.add('sel');fwTargetUid=uid;document.getElementById('fw-send-btn').style.display='block';}
async function execForward(){
  if(!fwTargetUid||!fwText)return;
  const r=await fetch('/api/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({to_uid:fwTargetUid,message:'\u21AA\uFE0F '+fwText})});
  const d=await r.json();if(d.ok){toast('Diteruskan');closePanel('fw-ov');}else toast('Gagal',2500,true);
}
async function doDelete(){
  if(!ctxMsgData||!currentFriend)return;document.getElementById('ctx-menu').style.display='none';if(!confirm('Hapus pesan ini?'))return;
  const r=await fetch('/api/delete_message',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message_id:ctxMsgData.id,friend_uid:currentFriend.uid})});
  const d=await r.json();if(d.ok){loadMessages();toast('Dihapus');}else toast('Gagal hapus',2500,true);
}

// ============================================================
// EMOJI
// ============================================================
function buildEmojiGrid(){document.getElementById('emoji-grid').innerHTML=EMOJIS.map(e=>`<span class="emoji-item" onclick="insertEmoji('${e}')">${e}</span>`).join('');}
function toggleEmojiPicker(){closeAllMenus();document.getElementById('emoji-picker').classList.toggle('open');}
function insertEmoji(e){
  const inp=document.getElementById('msg-input');const s=inp.selectionStart,end=inp.selectionEnd;
  inp.value=inp.value.substring(0,s)+e+inp.value.substring(end);
  inp.selectionStart=inp.selectionEnd=s+e.length;inp.focus();onMsgInput(inp);
  document.getElementById('emoji-picker').classList.remove('open');
}

// ============================================================
// FILE UPLOAD
// ============================================================
function toggleAttMenu(){closeAllMenus();document.getElementById('att-menu').classList.toggle('open');}
function triggerFile(type){document.getElementById('att-menu').classList.remove('open');document.getElementById(type==='photo'?'file-photo':'file-doc').click();}
function showUploadBar(){
  const bar=document.getElementById('upload-progress'),fill=document.getElementById('upload-fill');
  bar.classList.add('show');fill.style.width='0%';
  let w=0;const iv=setInterval(()=>{w+=Math.random()*8;if(w>=88)clearInterval(iv);fill.style.width=Math.min(w,88)+'%';},200);
  return()=>{fill.style.width='100%';setTimeout(()=>bar.classList.remove('show'),500);clearInterval(iv);};
}
async function handleUpload(input){
  if(!input.files[0]||!currentFriend)return;
  document.getElementById('att-menu').classList.remove('open');
  const done=showUploadBar(),fd=new FormData();
  fd.append('file',input.files[0]);fd.append('to_uid',currentFriend.uid);
  if(replyData){fd.append('reply_from',replyData.from);fd.append('reply_text',replyData.text);}
  try{
    const r=await fetch('/api/send_file',{method:'POST',body:fd});const d=await r.json();done();
    if(d.ok){cancelReply();loadMessages();}else toast('Upload gagal: '+(d.msg||''),3500,true);
  }catch(e){done();toast('Upload error: '+e.message,3000,true);}
  input.value='';
}

// ============================================================
// CAMERA
// ============================================================
function openCameraChat(){document.getElementById('att-menu').classList.remove('open');camMode='chat';openCamera();}
function openCameraStatus(){closePanel('cstat-ov');camMode='status';openCamera();}
async function openCamera(){
  try{
    camStream=await navigator.mediaDevices.getUserMedia({video:{facingMode:camFacing},audio:false});
    document.getElementById('cam-vid').srcObject=camStream;
    document.getElementById('cam-canvas').style.display='none';
    document.getElementById('cam-send-wrap').style.display='none';
    camPhotoBlob=null;openPanel('cam-ov');
  }catch(e){toast('Kamera tidak bisa diakses: '+e.message,3000,true);}
}
function switchCamFacing(){camFacing=camFacing==='user'?'environment':'user';closeCamera();setTimeout(openCamera,200);}
function snapPhoto(){
  const vid=document.getElementById('cam-vid'),canvas=document.getElementById('cam-canvas');
  canvas.width=vid.videoWidth;canvas.height=vid.videoHeight;
  canvas.getContext('2d').drawImage(vid,0,0);canvas.style.display='block';
  canvas.toBlob(b=>{camPhotoBlob=b;},'image/jpeg',0.92);
  document.getElementById('cam-send-wrap').style.display='block';
}
async function sendCamPhoto(){
  if(!camPhotoBlob){toast('Ambil foto dulu!',2000,true);return;}
  closeCamera();const done=showUploadBar(),fd=new FormData();
  fd.append('file',new File([camPhotoBlob],'camera.jpg',{type:'image/jpeg'}));
  if(camMode==='status'){
    fd.append('type','image');
    const r=await fetch('/api/status/upload',{method:'POST',body:fd});const d=await r.json();done();
    if(d.ok){toast('Status diposting \u2705');loadSidebarStatuses();setTimeout(openMyStatus,600);}else toast('Gagal',2500,true);
  }else{
    if(!currentFriend){done();return;}
    fd.append('to_uid',currentFriend.uid);
    const r=await fetch('/api/send_file',{method:'POST',body:fd});const d=await r.json();done();
    if(d.ok){toast('Foto terkirim');loadMessages();}else toast('Gagal',2500,true);
  }
}
function closeCamera(){if(camStream)camStream.getTracks().forEach(t=>t.stop());camStream=null;closePanel('cam-ov');}

// ============================================================
// VOICE RECORDING
// ============================================================
async function startVoice(e){
  if(e)e.preventDefault();
  if(!currentFriend){toast('Pilih chat dulu!',2000,true);return;}
  try{
    const stream=await navigator.mediaDevices.getUserMedia({audio:true});
    const mime=MediaRecorder.isTypeSupported('audio/webm')?'audio/webm':'audio/ogg';
    mediaRecorder=new MediaRecorder(stream,{mimeType:mime});
    recChunks=[];isRecording=true;
    mediaRecorder.ondataavailable=e=>recChunks.push(e.data);
    mediaRecorder.onstop=async()=>{
      const blob=new Blob(recChunks,{type:mime});stream.getTracks().forEach(t=>t.stop());
      if(blob.size>500&&currentFriend){
        const done=showUploadBar(),fd=new FormData();
        fd.append('file',new File([blob],'voice.webm',{type:mime}));fd.append('to_uid',currentFriend.uid);
        const r=await fetch('/api/send_file',{method:'POST',body:fd});const d=await r.json();done();
        if(d.ok){toast('Suara terkirim');loadMessages();}else toast('Gagal kirim suara',2500,true);
      }
    };
    mediaRecorder.start();document.getElementById('rec-btn').classList.add('recording');toast('Merekam... Lepaskan untuk kirim',15000);
  }catch(e){toast('Mikrofon tidak bisa diakses',2500,true);}
}
function stopVoice(e){
  if(e)e.preventDefault();
  if(mediaRecorder&&isRecording){mediaRecorder.stop();isRecording=false;document.getElementById('rec-btn').classList.remove('recording');toast('Mengirim...',1500);}
}
function viewImg(src){document.getElementById('img-full').src=src;openPanel('img-ov');}

// ============================================================
// TYPING
// ============================================================
async function pingTyping(){
  const now=Date.now();
  if(now-lastTypingPing<2000||!currentFriend||!appSettings.typing)return;
  lastTypingPing=now;
  await fetch('/api/typing',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({to_uid:currentFriend.uid})});
}
async function checkTyping(){
  if(!currentFriend)return;
  try{
    const r=await fetch(`/api/typing_status?friend_uid=${currentFriend.uid}`);const d=await r.json();
    const dots=document.getElementById('typing-dots');
    if(d.typing){document.getElementById('typing-text').textContent=currentFriend.name+' sedang mengetik...';dots.classList.add('show');}
    else dots.classList.remove('show');
  }catch(e){}
}

// ============================================================
// STATUS
// ============================================================
async function loadSidebarStatuses(){
  try{
    const r=await fetch('/api/status/list');const d=await r.json();
    const myStats=d.my_statuses||[],otherStats=d.statuses||[];
    document.getElementById('my-status-hint').textContent=myStats.length?`${myStats.length} status \u00b7 ${fmtTime(myStats[myStats.length-1].time)}`:'Ketuk untuk lihat atau buat status';
    const fl=document.getElementById('friends-status-list');
    const lbl=document.getElementById('friends-stat-label');
    const empty=document.getElementById('status-empty');
    const byUser={};
    otherStats.forEach(s=>{if(!byUser[s.uid])byUser[s.uid]=[];byUser[s.uid].push(s);});
    const entries=Object.entries(byUser);
    if(!entries.length){fl.innerHTML='';lbl.style.display='none';empty.style.display='';return;}
    lbl.style.display='';empty.style.display='none';
    fl.innerHTML=entries.map(([uid,sts])=>{
      const u=allUsers.find(x=>x.uid===uid)||{uid,username:'?',avatar:''};
      const latest=sts[sts.length-1];
      return`<div class="status-friend-item" onclick="viewFriendStatus('${uid}')">
        <div class="status-ring-wrap"><div class="status-ring"><div class="status-ring-inner">${makeAv(u,44)}</div></div></div>
        <div style="flex:1;min-width:0;margin-left:12px;">
          <div style="font-weight:800;font-size:14px;">${escHtml(u.username)}</div>
          <div style="font-size:12px;color:var(--st);margin-top:1px;">${fmtTime(latest.time)} \u00b7 ${sts.length} status</div>
        </div>
      </div>`;
    }).join('');
  }catch(e){}
}
async function openMyStatus(){
  try{
    const r=await fetch('/api/status/my');const d=await r.json();
    const myStats=d.statuses||[];
    if(!myStats.length){closePanel('stview-ov');openPanel('cstat-ov');return;}
    closePanel('cstat-ov');
    const u={uid:ME.uid,username:ME.username,avatar:document.querySelector('#my-av-el img')?.src||''};
    stvData={user:u,statuses:myStats};stvIdx=0;renderSTV();openPanel('stview-ov');
  }catch(e){toast('Gagal memuat status',2000,true);openPanel('cstat-ov');}
}
async function viewFriendStatus(uid){
  try{
    const r=await fetch(`/api/status/user/${uid}`);const d=await r.json();
    if(!d.statuses||!d.statuses.length){toast('Status tidak tersedia',2000);return;}
    const uFound=allUsers.find(x=>x.uid===uid);
    const firstStat=d.statuses[0];
    const u=uFound||{uid,username:firstStat.username||uid.slice(0,8),avatar:firstStat.avatar||''};
    stvData={user:u,statuses:d.statuses};stvIdx=0;renderSTV();openPanel('stview-ov');
  }catch(e){toast('Gagal memuat status',2500,true);}
}
function closeStatusViewer(){clearStvTimer();closePanel('stview-ov');}
function clearStvTimer(){if(stvTimerInt){clearInterval(stvTimerInt);stvTimerInt=null;}}
function prevStatus(){if(stvIdx>0){stvIdx--;renderSTV();}}
function nextStatus(){if(stvData&&stvIdx<stvData.statuses.length-1){stvIdx++;renderSTV();}else closeStatusViewer();}
function renderSTV(){
  if(!stvData)return;clearStvTimer();
  const{user,statuses}=stvData,s=statuses[stvIdx];
  document.getElementById('stv-av').innerHTML=makeAv(user,34);
  document.getElementById('stv-name').textContent=user.username;
  document.getElementById('stv-time').textContent=fmtTime(s.time);
  document.getElementById('stv-progress').innerHTML=statuses.map((_,i)=>`<div class="stv-seg"><div class="stv-fill" id="stv-f-${i}" style="width:${i<stvIdx?'100':'0'}%"></div></div>`).join('');
  let body='';
  if(s.type==='text'){const bgs=['#005c4b','#1a56db','#7c3aed','#dc2626','#d97706'];body=`<div class="stv-text" style="background:${bgs[stvIdx%bgs.length]};border-radius:12px;width:100%;min-height:160px;display:flex;align-items:center;justify-content:center;">${escHtml(s.content)}</div>`;}
  else if(s.type==='image'){body=`<img class="stv-img" src="${s.media_url}" alt="status">`;}
  else if(s.type==='video'){body=`<video src="${s.media_url}" controls autoplay playsinline style="max-width:100%;max-height:360px;border-radius:12px;display:block;"></video>`;}
  document.getElementById('stv-body').innerHTML=body;
  document.getElementById('stv-prev-btn').disabled=(stvIdx===0);
  document.getElementById('stv-next-btn').textContent=stvIdx>=statuses.length-1?'Tutup \u00d7':'Next \u25b6';
  requestAnimationFrame(()=>{const fill=document.getElementById(`stv-f-${stvIdx}`);if(fill){fill.style.transition='none';fill.style.width='0%';requestAnimationFrame(()=>{fill.style.transition='width 5s linear';fill.style.width='100%';});}});
  stvTimerInt=setInterval(()=>{if(stvData&&stvIdx<stvData.statuses.length-1){stvIdx++;renderSTV();}else closeStatusViewer();},5000);
}
function showTextStatusForm(){document.getElementById('text-stat-form').style.display='block';}
async function postTextStatus(){
  const txt=document.getElementById('stat-text-inp').value.trim();
  if(!txt){toast('Tulis status dulu!',2000,true);return;}
  const r=await fetch('/api/status/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:'text',content:txt})});
  const d=await r.json();
  if(d.ok){toast('Status diposting \u2705');closePanel('cstat-ov');document.getElementById('stat-text-inp').value='';document.getElementById('text-stat-form').style.display='none';await loadSidebarStatuses();setTimeout(openMyStatus,600);}
  else toast('Gagal: '+(d.msg||''),3000,true);
}
async function uploadStatus(input,type){
  if(!input.files[0])return;
  const file=input.files[0];if(file.size>20*1024*1024){toast('Max 20MB',2500,true);return;}
  const done=showUploadBar(),fd=new FormData();fd.append('file',file);fd.append('type',type);
  try{
    const r=await fetch('/api/status/upload',{method:'POST',body:fd});const d=await r.json();done();
    if(d.ok){toast('Status diposting!');closePanel('cstat-ov');await loadSidebarStatuses();setTimeout(openMyStatus,600);}
    else toast('Upload status gagal',3000,true);
  }catch(e){done();toast('Upload error',3000,true);}
  input.value='';
}

// ============================================================
// PROFILE
// ============================================================
async function uploadAvatar(input){
  if(!input.files[0])return;if(input.files[0].size>10*1024*1024){toast('Max 10MB',2500,true);return;}
  const done=showUploadBar(),fd=new FormData();fd.append('avatar',input.files[0]);
  try{const r=await fetch('/api/upload_avatar',{method:'POST',body:fd});const d=await r.json();done();
    if(d.ok){const url=d.url+'?t='+Date.now();document.getElementById('pav-big').innerHTML=`<img src="${url}" style="width:100%;height:100%;object-fit:cover;">`;document.getElementById('my-av-el').innerHTML=`<img src="${url}" style="width:40px;height:40px;border-radius:50%;object-fit:cover;">`;toast('Foto profil diperbarui \u2705');}
    else toast('Gagal: '+(d.msg||''),3000,true);
  }catch(e){done();toast('Gagal upload',2500,true);}
  input.value='';
}
async function saveProfile(){
  const u=document.getElementById('edit-username').value.trim(),b=document.getElementById('edit-bio').value.trim();
  if(!u){toast('Username kosong!',2500,true);return;}
  const fd=new FormData();fd.append('username',u);fd.append('bio',b);
  const r=await fetch('/api/update_profile',{method:'POST',body:fd});const d=await r.json();
  if(d.ok){document.getElementById('pname').textContent=u;toast('Profil disimpan \u2705');closePanel('prof-ov');setTimeout(()=>location.reload(),800);}
  else toast('Gagal: '+(d.msg||''),3000,true);
}
function doLogout(){if(confirm('Logout?'))fetch('/logout',{method:'POST'}).then(()=>location.href='/');}

// ============================================================
// NOTIFICATIONS
// ============================================================
async function checkNotifCount(){try{const r=await fetch('/api/notifications');const d=await r.json();const n=(d.notifications||[]).filter(x=>!x.read).length;const b=document.getElementById('notif-badge');b.style.display=n>0?'':'none';b.textContent=n>9?'9+':n;}catch(e){}}
async function loadNotifications(){
  const r=await fetch('/api/notifications');const d=await r.json();
  const el=document.getElementById('notif-list');const notifs=d.notifications||[];
  if(!notifs.length){el.innerHTML='<div style="text-align:center;color:var(--st);padding:22px;">Tidak ada notifikasi</div>';return;}
  el.innerHTML=notifs.slice().reverse().map(n=>{
    const u=allUsers.find(x=>x.uid===n.from);const nm=u?.username||'?';
    return`<div class="notif-item" onclick="closePanel('notif-ov');openChat('${n.from}','${(nm).replace(/'/g,"\\'")}','${u?.avatar||''}','')">
      <div class="notif-av">${makeAv(u||{username:nm},42)}</div>
      <div style="flex:1;"><div style="font-weight:800;font-size:14px;">${escHtml(nm)}</div><div style="font-size:12px;color:var(--st);">${escHtml(n.message)}</div><div style="font-size:11px;color:var(--st);">${fmtTime(n.time)}</div></div>
      ${!n.read?'<div class="notif-dot"></div>':''}
    </div>`;
  }).join('');
}
async function markNotifsRead(){await fetch('/api/notifications/read',{method:'POST'});checkNotifCount();}

// ============================================================
// ====== AGORA VIDEO/AUDIO CALL ======
// ============================================================
async function startAgoraCall(type){
  if(!currentFriend){toast('Pilih teman dulu!',2000,true);return;}
  if(!AGORA_APP_ID||AGORA_APP_ID==='YOUR_AGOR_APP_ID'){toast('Agora App ID belum dikonfigurasi!',3000,true);return;}
  agoraCallType=type;

  // Notify the other user via Firebase
  const channelName='call_'+[ME.uid,currentFriend.uid].sort().join('_')+'_'+Date.now();
  const r=await fetch('/api/call/offer',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({to_uid:currentFriend.uid,sdp:{channel:channelName},call_type:type})});
  const d=await r.json();
  agoraCurrentCallId=d.call_id;

  showAgoraCallUI(currentFriend,type,'outgoing');
  await joinAgoraChannel(channelName,type,false);
  pollAgoraAnswer();
}

async function joinAgoraChannel(channelName,type,asViewer=false){
  try{
    agoraClient=AgoraRTC.createClient({mode:'rtc',codec:'vp8'});
    await agoraClient.join(AGORA_APP_ID,channelName,null,ME.uid.slice(0,32));

    if(!asViewer){
      if(type==='video'||type==='both'){
        agoraLocalVideoTrack=await AgoraRTC.createCameraVideoTrack();
        agoraLocalVideoTrack.play('agora-local-container');
        await agoraClient.publish([agoraLocalVideoTrack]);
        if(agoraLocalAudioTrack){await agoraClient.publish([agoraLocalAudioTrack]);}
      }
      agoraLocalAudioTrack=await AgoraRTC.createMicrophoneAudioTrack();
      await agoraClient.publish([agoraLocalAudioTrack]);
    }

    agoraClient.on('user-published',async(user,mediaType)=>{
      await agoraClient.subscribe(user,mediaType);
      if(mediaType==='video'){
        const remoteContainer=document.getElementById('agora-remote-container');
        remoteContainer.innerHTML='';
        user.videoTrack.play('agora-remote-container');
        document.getElementById('call-status-txt').textContent='Terhubung \u2705';
        document.getElementById('call-status-txt').style.color='#00a884';
        if(!callTimerInt)startCallTimer();
      }
      if(mediaType==='audio'){user.audioTrack.play();}
    });
    agoraClient.on('user-unpublished',(user,mediaType)=>{
      if(mediaType==='video'){document.getElementById('agora-remote-container').innerHTML='<div style="color:rgba(255,255,255,.4);font-size:14px;text-align:center;"><div style="font-size:48px;margin-bottom:8px;">\u{1F464}</div>Kamera dimatikan</div>';}
    });
    agoraClient.on('user-left',()=>{toast('Panggilan berakhir',2000);agoraEndCall();});

  }catch(e){
    toast('Gagal bergabung: '+e.message,3000,true);
    console.error('Agora join error:',e);
  }
}

async function pollAgoraAnswer(){
  if(!agoraCurrentCallId)return;
  try{
    const r=await fetch(`/api/call/status/${agoraCurrentCallId}`);const d=await r.json();
    if(d.status==='answered'){
      document.getElementById('call-status-txt').textContent='Menghubungkan...';
      startCallTimer();
    }else if(d.status==='rejected'){toast('Panggilan ditolak',3000);agoraEndCall();}
    else if(d.status==='pending')setTimeout(pollAgoraAnswer,2000);
    else if(d.status==='ended')agoraEndCall();
  }catch(e){}
}

function showAgoraCallUI(friend,type,dir){
  document.getElementById('call-ui').classList.add('active');
  const name=friend.name||friend.username||'?';
  document.getElementById('call-av').innerHTML=friend.avatar?`<img src="${friend.avatar}" style="width:120px;height:120px;border-radius:50%;object-fit:cover;">`:(name[0]||'?').toUpperCase();
  document.getElementById('call-name').textContent=name;
  document.getElementById('call-status-txt').textContent=dir==='outgoing'?'Memanggil...':'Panggilan masuk...';
  document.getElementById('call-status-txt').style.color='rgba(255,255,255,.55)';
  document.getElementById('call-timer').style.display='none';
  // Show video grid for video, audio info for audio
  const isVideo=(type==='video');
  document.getElementById('call-video-grid').style.display=isVideo?'flex':'none';
  document.getElementById('audio-call-info').style.display=isVideo?'none':'flex';
  document.getElementById('cam-ctrl-wrap').style.display=isVideo?'flex':'none';
  micMuted=false;camOff=false;speakerOff=false;
  ['cbtn-mic','cbtn-cam','cbtn-spk'].forEach(id=>{const b=document.getElementById(id);if(b){b.className='call-cbtn cbtn-toggle cbtn-on';}});
  document.getElementById('cbtn-mic').textContent='\u{1F3A4}';
  document.getElementById('cbtn-cam').textContent='\u{1F4F7}';
  document.getElementById('cbtn-spk').textContent='\u{1F50A}';
}

async function answerAgoraCall(type){
  if(!incCallInfo)return;
  agoraCurrentCallId=incCallInfo.call_id;
  agoraCallType=type;
  document.getElementById('incoming-call').classList.remove('show');
  const caller=allUsers.find(u=>u.uid===incCallInfo.from)||{username:'?',avatar:'',uid:incCallInfo.from,name:'?'};
  showAgoraCallUI(caller,type,'incoming');
  const channelName=incCallInfo.sdp?.channel||('call_'+[ME.uid,incCallInfo.from].sort().join('_'));
  await joinAgoraChannel(channelName,type,false);
  await fetch('/api/call/answer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({call_id:agoraCurrentCallId,answer:{channel:channelName}})});
  document.getElementById('call-status-txt').textContent='Terhubung \u2705';
  document.getElementById('call-status-txt').style.color='#00a884';
  startCallTimer();
}

function rejectAgoraCall(){
  if(incCallInfo)fetch('/api/call/reject',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({call_id:incCallInfo.call_id})});
  document.getElementById('incoming-call').classList.remove('show');incCallInfo=null;
}

async function agoraEndCall(){
  if(agoraLocalAudioTrack){agoraLocalAudioTrack.close();agoraLocalAudioTrack=null;}
  if(agoraLocalVideoTrack){agoraLocalVideoTrack.close();agoraLocalVideoTrack=null;}
  if(agoraClient){await agoraClient.leave();agoraClient=null;}
  if(callTimerInt){clearInterval(callTimerInt);callTimerInt=null;}
  if(agoraCurrentCallId){fetch('/api/call/end',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({call_id:agoraCurrentCallId})});agoraCurrentCallId=null;}
  document.getElementById('call-ui').classList.remove('active');
  document.getElementById('call-video-grid').style.display='none';
  document.getElementById('audio-call-info').style.display='flex';
  callSecs=0;
}

function agoraToggleMic(){
  micMuted=!micMuted;
  if(agoraLocalAudioTrack)agoraLocalAudioTrack.setEnabled(!micMuted);
  const btn=document.getElementById('cbtn-mic');
  btn.textContent=micMuted?'\u{1F507}':'\u{1F3A4}';
  btn.className='call-cbtn cbtn-toggle '+(micMuted?'cbtn-off-state':'cbtn-on');
}
function agoraToggleCam(){
  camOff=!camOff;
  if(agoraLocalVideoTrack)agoraLocalVideoTrack.setEnabled(!camOff);
  const btn=document.getElementById('cbtn-cam');
  btn.textContent=camOff?'\u{1F6AB}':'\u{1F4F7}';
  btn.className='call-cbtn cbtn-toggle '+(camOff?'cbtn-off-state':'cbtn-on');
}
function agoraToggleSpeaker(){
  speakerOff=!speakerOff;
  const btn=document.getElementById('cbtn-spk');
  btn.textContent=speakerOff?'\u{1F507}':'\u{1F50A}';
  btn.className='call-cbtn cbtn-toggle '+(speakerOff?'cbtn-off-state':'cbtn-on');
  toast(speakerOff?'Speaker dimatikan':'Speaker aktif',1500);
}

function startCallTimer(){
  callSecs=0;document.getElementById('call-timer').style.display='block';
  if(callTimerInt)clearInterval(callTimerInt);
  callTimerInt=setInterval(()=>{
    callSecs++;
    const m=Math.floor(callSecs/60).toString().padStart(2,'0'),s=(callSecs%60).toString().padStart(2,'0');
    document.getElementById('call-timer').textContent=m+':'+s;
  },1000);
}

async function checkIncomingCall(){
  if(agoraClient)return;
  try{
    const r=await fetch('/api/call/incoming');const d=await r.json();
    if(d.call&&(!incCallInfo||incCallInfo.call_id!==d.call.call_id)){
      incCallInfo=d.call;
      const caller=allUsers.find(u=>u.uid===d.call.from)||{username:'Seseorang',avatar:'',uid:d.call.from};
      document.getElementById('inc-av').innerHTML=makeAv(caller,56);
      document.getElementById('inc-name').textContent=caller.username;
      document.getElementById('inc-type').textContent=d.call.call_type==='video'?'\u{1F4F9} Video Call Masuk':'\u{1F4DE} Panggilan Masuk';
      document.getElementById('incoming-call').classList.add('show');
      setTimeout(()=>{if(incCallInfo&&incCallInfo.call_id===d.call.call_id)rejectAgoraCall();},30000);
    }
  }catch(e){}
}

// ============================================================
// ====== AGORA LIVE STREAMING ======
// ============================================================
async function startLiveStream(){
  if(!AGORA_APP_ID||AGORA_APP_ID==='YOUR_AGOR_APP_ID'){toast('Agora App ID belum dikonfigurasi!',3000,true);return;}
  liveChannelName='live_'+ME.uid+'_'+Date.now();
  isLiveHost=true;
  // Register live in Firebase
  await fetch('/api/live/start',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({channel:liveChannelName,host_uid:ME.uid,host_name:ME.username})});
  document.getElementById('live-streamer-name').textContent=ME.username;
  document.getElementById('live-end-btn').style.display='block';
  document.getElementById('live-ui').classList.add('active');
  document.getElementById('live-badge').textContent='\u25cf LIVE';
  try{
    agoraLiveClient=AgoraRTC.createClient({mode:'live',codec:'vp8'});
    agoraLiveClient.setClientRole('host');
    await agoraLiveClient.join(AGORA_APP_ID,liveChannelName,null,ME.uid.slice(0,32));
    agoraLiveLocalVideoTrack=await AgoraRTC.createCameraVideoTrack();
    agoraLiveLocalAudioTrack=await AgoraRTC.createMicrophoneAudioTrack();
    agoraLiveLocalVideoTrack.play('live-local-video');
    await agoraLiveClient.publish([agoraLiveLocalVideoTrack,agoraLiveLocalAudioTrack]);
    agoraLiveClient.on('user-joined',(user)=>{
      liveViewers.push(user.uid);
      document.getElementById('live-viewer-count').textContent='\u{1F441} '+liveViewers.length+' penonton';
      addLiveComment('','['+user.uid.slice(0,8)+'... bergabung]','system');
    });
    agoraLiveClient.on('user-left',(user)=>{
      liveViewers=liveViewers.filter(u=>u!==user.uid);
      document.getElementById('live-viewer-count').textContent='\u{1F441} '+liveViewers.length+' penonton';
    });
    liveCommentPollTimer=setInterval(pollLiveComments,3000);
    toast('Live streaming dimulai! \u{1F534}',2000);
  }catch(e){toast('Gagal mulai live: '+e.message,3000,true);closeLiveUI();}
}

async function watchLive(channelName,hostName,liveId){
  if(!AGORA_APP_ID||AGORA_APP_ID==='YOUR_AGOR_APP_ID'){toast('Agora App ID belum dikonfigurasi!',3000,true);return;}
  liveChannelName=channelName;isLiveHost=false;currentLiveData={id:liveId};
  document.getElementById('live-streamer-name').textContent=hostName;
  document.getElementById('live-end-btn').style.display='none';
  document.getElementById('live-ui').classList.add('active');
  // Join as audience
  await fetch('/api/live/join',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({live_id:liveId,uid:ME.uid})});
  try{
    agoraLiveClient=AgoraRTC.createClient({mode:'live',codec:'vp8'});
    agoraLiveClient.setClientRole('audience');
    await agoraLiveClient.join(AGORA_APP_ID,channelName,null,ME.uid.slice(0,32));
    agoraLiveClient.on('user-published',async(user,mediaType)=>{
      await agoraLiveClient.subscribe(user,mediaType);
      if(mediaType==='video')user.videoTrack.play('live-remote-video');
      if(mediaType==='audio')user.audioTrack.play();
    });
    agoraLiveClient.on('user-left',()=>{toast('Siaran berakhir',2000);closeLiveUI();});
    liveCommentPollTimer=setInterval(pollLiveComments,3000);
    toast('Bergabung ke live!',1500);
  }catch(e){toast('Gagal bergabung: '+e.message,3000,true);closeLiveUI();}
}

async function endLiveStream(){
  if(!isLiveHost)return;
  if(!confirm('Akhiri live streaming?'))return;
  await fetch('/api/live/end',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({channel:liveChannelName,host_uid:ME.uid})});
  closeLiveUI();toast('Live streaming berakhir',2000);
}

async function closeLiveUI(){
  if(liveCommentPollTimer){clearInterval(liveCommentPollTimer);liveCommentPollTimer=null;}
  if(agoraLiveLocalVideoTrack){agoraLiveLocalVideoTrack.close();agoraLiveLocalVideoTrack=null;}
  if(agoraLiveLocalAudioTrack){agoraLiveLocalAudioTrack.close();agoraLiveLocalAudioTrack=null;}
  if(agoraLiveClient){await agoraLiveClient.leave();agoraLiveClient=null;}
  document.getElementById('live-ui').classList.remove('active');
  document.getElementById('live-comments').innerHTML='';
  document.getElementById('live-local-video').innerHTML='';
  document.getElementById('live-remote-video').innerHTML='';
  liveViewers=[];isLiveHost=false;
  loadLiveList();
}

async function sendLiveComment(){
  const inp=document.getElementById('live-comment-input');
  const text=inp.value.trim();if(!text)return;
  inp.value='';
  addLiveComment(ME.uid,text,ME.username);
  await fetch('/api/live/comment',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({channel:liveChannelName,uid:ME.uid,username:ME.username,text})});
}

async function pollLiveComments(){
  try{
    const r=await fetch(`/api/live/comments/${liveChannelName}`);const d=await r.json();
    const comments=d.comments||[];
    const container=document.getElementById('live-comments');
    // Only add new comments
    const existing=container.querySelectorAll('.live-comment').length;
    if(comments.length>existing){
      for(let i=existing;i<comments.length;i++){
        const c=comments[i];
        addLiveComment(c.uid,c.text,c.username);
      }
    }
  }catch(e){}
}

function addLiveComment(uid,text,username){
  const container=document.getElementById('live-comments');
  const div=document.createElement('div');div.className='live-comment';
  const isSystem=username==='system';
  div.innerHTML=isSystem?`<span style="color:rgba(255,255,255,.5);font-style:italic;">${escHtml(text)}</span>`
    :`<span class="cname">${escHtml(username)}</span>${escHtml(text)}`;
  container.appendChild(div);
  // Keep max 8 comments visible
  while(container.children.length>8)container.removeChild(container.firstChild);
  // Auto scroll
  container.scrollTop=container.scrollHeight;
}

async function loadLiveList(){
  try{
    const r=await fetch('/api/live/list');const d=await r.json();
    const el=document.getElementById('live-list');
    const lives=d.lives||[];
    if(!lives.length){el.innerHTML='<div style="padding:24px;text-align:center;color:var(--st);font-size:13px;">Tidak ada siaran live saat ini \u{1F4FA}</div>';return;}
    el.innerHTML=lives.map(l=>{
      const u=allUsers.find(x=>x.uid===l.host_uid)||{username:l.host_name||'?',avatar:''};
      return`<div class="live-item" onclick="watchLive('${l.channel}','${escHtml(l.host_name||'?')}','${l.id}')">
        <div class="live-thumb"><div style="width:100%;height:100%;background:#1a0a38;display:flex;align-items:center;justify-content:center;font-size:24px;">\u{1F4FA}</div><div class="live-thumb-badge">LIVE</div></div>
        <div style="flex:1;min-width:0;">
          <div style="font-weight:800;font-size:14px;">${escHtml(l.host_name||'?')}</div>
          <div style="font-size:12px;color:var(--g);">\u{1F441} ${l.viewer_count||0} penonton</div>
          <div style="font-size:11px;color:var(--st);">${fmtTime(l.started_at)}</div>
        </div>
        <div class="live-badge" style="font-size:10px;padding:3px 8px;">\u25cf LIVE</div>
      </div>`;
    }).join('');
  }catch(e){document.getElementById('live-list').innerHTML='<div style="padding:24px;text-align:center;color:var(--st);">Gagal memuat</div>';}
}

function toggleLiveViewers(){
  const panel=document.getElementById('live-viewers-panel');
  if(panel.style.display==='none'||!panel.style.display){
    panel.style.display='block';
    panel.innerHTML='<div style="font-size:12px;color:rgba(255,255,255,.6);font-weight:800;margin-bottom:8px;">\u{1F465} Penonton ('+liveViewers.length+')</div>'+
      (liveViewers.length?liveViewers.map(uid=>`<div class="live-viewer-item">\u{1F464} ${uid.slice(0,12)}...</div>`).join(''):'<div style="color:rgba(255,255,255,.4);font-size:12px;">Belum ada penonton</div>');
  }else panel.style.display='none';
}

// ============================================================
// AI ASSISTANT
// ============================================================
function openAI(){document.getElementById('ai-drawer').classList.add('open');setTimeout(()=>document.getElementById('ai-input').focus(),300);}
function closeAI(){document.getElementById('ai-drawer').classList.remove('open');}
function handleAIKey(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendAIFromInput();}}
function autoResizeAI(el){el.style.height='auto';el.style.height=Math.min(el.scrollHeight,100)+'px';}
async function sendAIFromInput(){const inp=document.getElementById('ai-input');const text=inp.value.trim();if(!text)return;inp.value='';inp.style.height='auto';await sendAIMsg(text);}
async function sendAIMsg(text){
  if(!text)return;
  document.getElementById('ai-chips').style.display='none';
  const container=document.getElementById('ai-messages');
  const uDiv=document.createElement('div');uDiv.className='ai-msg user';
  uDiv.innerHTML=`<div class="ai-msg-av">\u{1F464}</div><div class="ai-bubble">${escHtml(text)}</div>`;
  container.appendChild(uDiv);
  aiHistory.push({role:'user',content:text});
  const thinkDiv=document.createElement('div');thinkDiv.className='ai-msg ai';const thinkId='ai-t-'+Date.now();thinkDiv.id=thinkId;
  thinkDiv.innerHTML=`<div class="ai-msg-av">\u{1F916}</div><div class="ai-thinking-bubble"><span></span><span></span><span></span></div>`;
  container.appendChild(thinkDiv);container.scrollTop=container.scrollHeight;
  try{
    let sys='Kamu adalah WaClone AI, asisten pintar. Jawab dalam Bahasa Indonesia yang ramah dan natural. ';
    if(currentFriend)sys+=`Pengguna sedang chat dengan ${currentFriend.name}. `;
    let rawHistory=[...aiHistory];
    while(rawHistory.length>0&&rawHistory[0].role!=='user')rawHistory.shift();
    const cleanMsgs=[];
    for(const m of rawHistory){if(!cleanMsgs.length||cleanMsgs[cleanMsgs.length-1].role!==m.role)cleanMsgs.push({role:m.role,content:m.content});else cleanMsgs[cleanMsgs.length-1].content+='\n'+m.content;}
    const finalMsgs=cleanMsgs.slice(-10);
    if(!finalMsgs.length||finalMsgs[0].role!=='user')finalMsgs.unshift({role:'user',content:text});
    const res=await fetch('/api/ai/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({system:sys,messages:finalMsgs})});
    const thinkEl=document.getElementById(thinkId);if(thinkEl)thinkEl.remove();
    const rData=await res.json();
    let reply=rData.ok?(rData.reply||'Maaf, tidak ada jawaban.'):('\u26a0\ufe0f '+(rData.msg||'Tidak bisa menjawab sekarang.'));
    if(rData.ok)aiHistory.push({role:'assistant',content:reply});
    const aDiv=document.createElement('div');aDiv.className='ai-msg ai';
    const formatted=escHtml(reply).replace(/\*\*(.*?)\*\*/gs,'<strong>$1</strong>').replace(/\n/g,'<br>');
    aDiv.innerHTML=`<div class="ai-msg-av">\u{1F916}</div><div><div class="ai-bubble">${formatted}</div></div>`;
    const isReplyHelp=text.toLowerCase().includes('balas')||text.toLowerCase().includes('pesan')||text.toLowerCase().includes('tulis');
    if(currentFriend&&isReplyHelp&&rData.ok){
      const btn=document.createElement('button');btn.className='copy-to-chat-btn';btn.innerHTML='\u{1F4CB} Salin ke chat';btn.style.marginLeft='38px';
      const replyTxt=reply;btn.onclick=()=>{document.getElementById('msg-input').value=replyTxt;onMsgInput(document.getElementById('msg-input'));closeAI();document.getElementById('msg-input').focus();toast('Pesan disalin ke chat \u2705');};
      aDiv.querySelector('div').appendChild(btn);
    }
    container.appendChild(aDiv);container.scrollTop=container.scrollHeight;
  }catch(e){
    const thinkEl=document.getElementById(thinkId);if(thinkEl)thinkEl.remove();
    const errDiv=document.createElement('div');errDiv.className='ai-msg ai';
    errDiv.innerHTML=`<div class="ai-msg-av">\u{1F916}</div><div class="ai-bubble" style="background:rgba(220,38,38,.1);border-color:rgba(220,38,38,.3);color:#fca5a5;">Terjadi kesalahan. Coba lagi \u{1F614}</div>`;
    container.appendChild(errDiv);container.scrollTop=container.scrollHeight;
  }
}

// ============================================================
// INIT
// ============================================================
buildEmojiGrid();
loadSettings();
loadUsers();
async function updatePresence(){try{await fetch('/api/presence',{method:'POST'});}catch(e){}}
updatePresence();
setInterval(()=>{loadUsers();checkNotifCount();updatePresence();checkIncomingCall();},5000);

document.addEventListener('click',e=>{
  if(!document.getElementById('att-menu').contains(e.target)&&!e.target.closest('[title="Lampiran"]'))document.getElementById('att-menu').classList.remove('open');
  if(!document.getElementById('emoji-picker').contains(e.target)&&!e.target.closest('[title="Emoji"]'))document.getElementById('emoji-picker').classList.remove('open');
});

window.addEventListener('popstate',function(e){e.preventDefault();goBack();history.pushState(null,'',location.href);});
history.pushState(null,'',location.href);

function checkMobile(){
  const isMobile=window.innerWidth<=700;
  const bb=document.getElementById('back-btn');
  if(bb)bb.style.cssText=isMobile?'display:flex!important;flex-shrink:0;width:36px;height:36px;border:none;background:transparent;color:#e9edef;border-radius:50%;align-items:center;justify-content:center;cursor:pointer;':'display:none!important;';
  if(!isMobile)document.getElementById('sidebar').classList.remove('hidden');
}
checkMobile();
window.addEventListener('resize',checkMobile);
</script>
</body>
</html>"""


def main_app_html(u):
    import json
    uid      = u.get("uid", "")
    username = u.get("username", "User")
    email    = u.get("email", "")
    avatar   = u.get("avatar", "")
    bio      = u.get("bio", "Hey there! I am using WaClone.")
    initial  = username[0].upper() if username else "U"

    uid_js      = json.dumps(uid)
    username_js = json.dumps(username)
    username_html = username.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;')
    email_html    = email.replace('&','&amp;').replace('<','&lt;').replace('"','&quot;')
    bio_html      = bio.replace('&','&amp;').replace('<','&lt;').replace('"','&quot;')

    if avatar:
        sidebar_av = f'<img src="{avatar}" style="width:42px;height:42px;border-radius:50%;object-fit:cover;">'
    else:
        colors = ['#00a884','#7c3aed','#1a56db','#dc2626','#d97706','#059669']
        bg = colors[ord(username[0]) % len(colors)] if username else '#00a884'
        sidebar_av = f'<div style="width:42px;height:42px;border-radius:50%;background:{bg};display:flex;align-items:center;justify-content:center;font-weight:900;font-size:18px;color:#fff;">{initial}</div>'

    if avatar:
        profile_av = f'<img src="{avatar}" style="width:100%;height:100%;object-fit:cover;">'
    else:
        profile_av = f'<span style="font-size:40px;font-weight:900;">{initial}</span>'

    html = MAIN_HTML
    html = html.replace('"__UID__"',      uid_js)
    html = html.replace('"__USERNAME__"', username_js)
    html = html.replace("__USERNAME__",   username_html)
    html = html.replace("__EMAIL__",      email_html)
    html = html.replace("__BIO__",        bio_html)
    html = html.replace("__SIDEBAR_AV__", sidebar_av)
    html = html.replace("__PROFILE_AV__", profile_av)
    # Inject API keys
    html = html.replace("__AGORA_APP_ID__", AGORA_APP_ID)
    html = html.replace("__SUPABASE_PROJECT__", SUPABASE_PROJECT_ID)
    return html


# ============================
# ROUTES
# ============================
@app.route("/")
def index():
    user = get_current_user(request)
    if user: return redirect("/home")
    resp = make_response(AUTH_PAGE.encode('utf-8'))
    resp.headers['Content-Type'] = 'text/html; charset=utf-8'
    return resp

@app.route("/home")
def home():
    user = get_current_user(request)
    if not user: return redirect("/")
    html = main_app_html(user)
    resp = make_response(html.encode('utf-8'))
    resp.headers['Content-Type'] = 'text/html; charset=utf-8'
    return resp

@app.route("/firebase_config")
def firebase_config():
    return jsonify({
        "apiKey": "AIzaSyBqk6r41LW4rS2dEuikLEYT1TIQFwmh_4M",
        "authDomain": "data-base-d7fda.firebaseapp.com",
        "projectId": "data-base-d7fda",
        "storageBucket": "data-base-d7fda.firebasestorage.app",
        "messagingSenderId": "545012284213",
        "appId": "1:545012284213:web:1b00d7ad94350aae2cea7c"
    })

@app.route("/api/config")
def api_config():
    """Expose public config to frontend"""
    return jsonify({
        "supabase_project": SUPABASE_PROJECT_ID,
        "supabase_url": SUPABASE_URL,
        "agora_app_id": AGORA_APP_ID
    })

@app.route("/google_auth", methods=["POST"])
def google_auth():
    data = request.get_json()
    id_token = data.get("id_token","")
    if not id_token: return jsonify({"ok":False,"msg":"Token tidak valid"})
    try:
        decoded = auth.verify_id_token(id_token)
        uid   = decoded["uid"]
        email = decoded.get("email","")
        name  = decoded.get("name", email.split("@")[0] if email else "User")
        name  = ''.join(c for c in name if c.isalnum() or c in '_- ')[:20].strip().replace(' ','_') or "User"
        photo = decoded.get("picture","")
        doc = db.collection("users").document(uid).get()
        if not doc.exists:
            base_name = name; suffix = 0
            while db.collection("users").where("username","==",name).get():
                suffix += 1; name = f"{base_name}{suffix}"
            db.collection("users").document(uid).set({
                "uid":uid,"username":name,"email":email,
                "avatar":photo,"bio":"Hey there! I am using WaClone.",
                "online":True,"last_seen":int(time.time()),
                "created_at":int(time.time()),"auth_provider":"google","password":""
            })
        else:
            upd = {"online":True,"last_seen":int(time.time())}
            if photo and not doc.to_dict().get("avatar"): upd["avatar"] = photo
            db.collection("users").document(uid).update(upd)
        resp = make_response(jsonify({"ok":True}))
        resp.set_cookie("uid", uid, max_age=30*24*3600, httponly=True, samesite='Lax')
        return resp
    except Exception as e:
        print("Google auth error:", e, file=sys.stderr)
        return jsonify({"ok":False,"msg":"Token tidak valid atau sudah kadaluarsa"})

@app.route("/register", methods=["POST"])
def register():
    username = request.form.get("username","").strip()
    email    = request.form.get("email","").strip()
    password = request.form.get("password","")
    if not username or not email or not password:
        return jsonify({"ok":False,"msg":"Semua field harus diisi"})
    if len(password) < 6: return jsonify({"ok":False,"msg":"Password minimal 6 karakter"})
    if not all(c.isalnum() or c in '_' for c in username):
        return jsonify({"ok":False,"msg":"Username hanya boleh huruf, angka, dan underscore"})
    if len(username) < 3: return jsonify({"ok":False,"msg":"Username minimal 3 karakter"})
    try:
        if db.collection("users").where("username","==",username).get():
            return jsonify({"ok":False,"msg":"Username sudah dipakai"})
        try:
            auth.get_user_by_email(email)
            return jsonify({"ok":False,"msg":"Email sudah terdaftar"})
        except auth.UserNotFoundError: pass
        fu = auth.create_user(email=email, password=password)
        db.collection("users").document(fu.uid).set({
            "uid":fu.uid,"username":username,"email":email,
            "password":generate_password_hash(password),
            "bio":"Hey there! I am using WaClone.","avatar":"",
            "online":True,"last_seen":int(time.time()),
            "created_at":int(time.time()),"auth_provider":"email"
        })
        resp = make_response(jsonify({"ok":True}))
        resp.set_cookie("uid", fu.uid, max_age=30*24*3600, httponly=True, samesite='Lax')
        return resp
    except Exception as e:
        print("Register error:", e, file=sys.stderr)
        return jsonify({"ok":False,"msg":str(e)})

@app.route("/login", methods=["POST"])
def login():
    email    = request.form.get("email","").strip()
    password = request.form.get("password","")
    if not email or not password: return jsonify({"ok":False,"msg":"Email/password kosong"})
    try:
        users = db.collection("users").where("email","==",email).get()
        if not users: return jsonify({"ok":False,"msg":"Email tidak ditemukan"})
        u = users[0].to_dict()
        if u.get("auth_provider") == "google":
            return jsonify({"ok":False,"msg":"Akun ini terdaftar via Google"})
        if not u.get("password"): return jsonify({"ok":False,"msg":"Akun ini tidak memiliki password"})
        if check_password_hash(u.get("password",""), password):
            uid = u.get("uid")
            db.collection("users").document(uid).update({"online":True,"last_seen":int(time.time())})
            resp = make_response(jsonify({"ok":True}))
            resp.set_cookie("uid", uid, max_age=30*24*3600, httponly=True, samesite='Lax')
            return resp
        return jsonify({"ok":False,"msg":"Password salah"})
    except Exception as e:
        print("Login error:", e, file=sys.stderr)
        return jsonify({"ok":False,"msg":"Login gagal, coba lagi"})

@app.route("/logout", methods=["POST"])
def logout():
    user = get_current_user(request)
    if user:
        try: db.collection("users").document(user["uid"]).update({"online":False,"last_seen":int(time.time())})
        except: pass
    resp = make_response(jsonify({"ok":True}))
    resp.set_cookie("uid","",expires=0)
    return resp

@app.route("/api/users")
def api_users():
    user = get_current_user(request)
    if not user: return jsonify({"users":[]})
    try:
        current_uid = user["uid"]
        docs = db.collection("users").stream()
        users = []
        for doc in docs:
            u = doc.to_dict()
            if u.get("uid") == current_uid: continue
            chat_id = "_".join(sorted([current_uid, u["uid"]]))
            unread=0; last_msg=""; last_time=0
            try:
                unread = sum(1 for _ in db.collection("chats").document(chat_id).collection("messages")
                             .where("to","==",current_uid).where("status","!=","read").stream())
            except: pass
            try:
                cd = db.collection("chats").document(chat_id).get()
                if cd.exists:
                    data = cd.to_dict()
                    last_msg  = data.get("last_message","")
                    last_time = data.get("last_time",0)
            except: pass
            users.append({
                "uid":u.get("uid"),"username":u.get("username",""),
                "bio":u.get("bio",""),"avatar":u.get("avatar",""),
                "online":u.get("online",False),"last_seen":u.get("last_seen",0),
                "unread_count":unread,"last_msg":last_msg,"last_time":last_time
            })
        users.sort(key=lambda x: x.get("last_time",0), reverse=True)
        return jsonify({"users":users})
    except Exception as e:
        return jsonify({"users":[],"error":str(e)})

@app.route("/api/messages")
def api_messages():
    user = get_current_user(request)
    if not user: return jsonify({"messages":[]})
    friend_uid = request.args.get("friend_uid")
    if not friend_uid: return jsonify({"messages":[]})
    return jsonify({"messages": load_messages(user["uid"], friend_uid)})

@app.route("/api/send", methods=["POST"])
def api_send():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    data = request.get_json()
    to_uid  = data.get("to_uid")
    message = data.get("message","").strip()
    reply_to = data.get("reply_to")
    if not to_uid or not message: return jsonify({"ok":False})
    save_message(user["uid"], to_uid, message, reply_to=reply_to)
    return jsonify({"ok":True})

@app.route("/api/send_file", methods=["POST"])
def api_send_file():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    to_uid = request.form.get("to_uid")
    f = request.files.get("file")
    if not f or not to_uid: return jsonify({"ok":False,"msg":"Data tidak lengkap"})
    if not allowed_file(f.filename): return jsonify({"ok":False,"msg":"Tipe file tidak diizinkan"})
    try:
        file_url, file_type = upload_to_storage(f, "chats")
        reply_to = None
        rt = request.form.get("reply_text")
        rf = request.form.get("reply_from")
        if rt: reply_to = {"text":rt,"from":rf or ""}
        save_message(user["uid"], to_uid, "", file_url=file_url, file_type=file_type, reply_to=reply_to)
        return jsonify({"ok":True,"file_url":file_url})
    except Exception as e:
        print("send_file error:", e, file=sys.stderr)
        return jsonify({"ok":False,"msg":str(e)})

@app.route("/api/delete_message", methods=["POST"])
def api_delete_message():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    data = request.get_json()
    message_id = data.get("message_id")
    friend_uid = data.get("friend_uid")
    if not message_id or not friend_uid: return jsonify({"ok":False})
    try:
        chat_id = "_".join(sorted([user["uid"], friend_uid]))
        msg_ref = db.collection("chats").document(chat_id).collection("messages").document(message_id)
        msg = msg_ref.get()
        if not msg.exists: return jsonify({"ok":False,"msg":"Pesan tidak ditemukan"})
        if msg.to_dict().get("from") != user["uid"]:
            return jsonify({"ok":False,"msg":"Tidak bisa hapus pesan orang lain"})
        msg_ref.update({"deleted":True,"message":"Pesan ini telah dihapus","file":None})
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"ok":False,"msg":str(e)})

@app.route("/api/upload_avatar", methods=["POST"])
def api_upload_avatar():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False,"msg":"Tidak terautentikasi"})
    f = request.files.get("avatar")
    if not f: return jsonify({"ok":False,"msg":"Tidak ada file"})
    allowed_img = {'png','jpg','jpeg','gif','webp','bmp','heic','heif'}
    ext = f.filename.rsplit('.',1)[-1].lower() if '.' in f.filename else ''
    if ext not in allowed_img: return jsonify({"ok":False,"msg":f"Format tidak didukung ({ext})"})
    try:
        url, _ = upload_to_storage(f, "avatars")
        db.collection("users").document(user["uid"]).update({"avatar":url})
        return jsonify({"ok":True,"url":url})
    except Exception as e:
        return jsonify({"ok":False,"msg":f"Upload gagal: {str(e)}"})

@app.route("/api/update_profile", methods=["POST"])
def api_update_profile():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    username = request.form.get("username","").strip()
    bio      = request.form.get("bio","").strip()
    if not username: return jsonify({"ok":False,"msg":"Username tidak boleh kosong"})
    try:
        upd = {"bio":bio}
        if username != user.get("username"):
            existing = db.collection("users").where("username","==",username).get()
            if existing: return jsonify({"ok":False,"msg":"Username sudah dipakai"})
            upd["username"] = username
        db.collection("users").document(user["uid"]).update(upd)
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"ok":False,"msg":str(e)})

@app.route("/api/mark_read", methods=["POST"])
def api_mark_read():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    data = request.get_json()
    if data and data.get("friend_uid"):
        mark_messages_read(user["uid"], data["friend_uid"])
    return jsonify({"ok":True})

@app.route("/api/typing", methods=["POST"])
def api_typing():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    data = request.get_json()
    to_uid = data.get("to_uid")
    if not to_uid: return jsonify({"ok":False})
    try:
        db.collection("typing").document(f"{user['uid']}_{to_uid}").set({
            "from":user["uid"],"to":to_uid,"time":int(time.time())
        })
        return jsonify({"ok":True})
    except: return jsonify({"ok":False})

@app.route("/api/typing_status")
def api_typing_status():
    user = get_current_user(request)
    if not user: return jsonify({"typing":False})
    friend_uid = request.args.get("friend_uid")
    if not friend_uid: return jsonify({"typing":False})
    try:
        doc = db.collection("typing").document(f"{friend_uid}_{user['uid']}").get()
        if doc.exists:
            t = doc.to_dict().get("time",0)
            return jsonify({"typing": int(time.time())-t < 5})
        return jsonify({"typing":False})
    except: return jsonify({"typing":False})

@app.route("/api/notifications")
def api_notifications():
    user = get_current_user(request)
    if not user: return jsonify({"notifications":[]})
    try:
        notifs = db.collection("notifications").where("to","==",user["uid"]).order_by("time").limit(50).stream()
        return jsonify({"notifications":[n.to_dict() for n in notifs]})
    except: return jsonify({"notifications":[]})

@app.route("/api/notifications/read", methods=["POST"])
def api_notifs_read():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    try:
        for n in db.collection("notifications").where("to","==",user["uid"]).where("read","==",False).stream():
            n.reference.update({"read":True})
        return jsonify({"ok":True})
    except: return jsonify({"ok":False})

@app.route("/api/presence", methods=["POST"])
def api_presence():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    try: db.collection("users").document(user["uid"]).update({"online":True,"last_seen":int(time.time())})
    except: pass
    return jsonify({"ok":True})

# ============================================================
# STATUS
# ============================================================
@app.route("/api/status/create", methods=["POST"])
def api_status_create():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    data = request.get_json()
    try:
        db.collection("statuses").add({
            "uid":user["uid"],"type":data.get("type","text"),
            "content":data.get("content","")[:200],"media_url":None,
            "time":int(time.time()),"viewers":[]
        })
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"ok":False,"msg":str(e)})

@app.route("/api/status/upload", methods=["POST"])
def api_status_upload():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False,"msg":"Tidak terautentikasi"})
    f = request.files.get("file")
    stype = request.form.get("type","image")
    if not f: return jsonify({"ok":False,"msg":"Tidak ada file"})
    if not allowed_file(f.filename): return jsonify({"ok":False,"msg":"Tipe file tidak didukung"})
    try:
        url, ct = upload_to_storage(f, "statuses")
        db.collection("statuses").add({
            "uid":user["uid"],"type":stype,"content":"","media_url":url,
            "time":int(time.time()),"viewers":[]
        })
        return jsonify({"ok":True,"url":url})
    except Exception as e:
        return jsonify({"ok":False,"msg":str(e)})

@app.route("/api/status/list")
def api_status_list():
    user = get_current_user(request)
    if not user: return jsonify({"statuses":[],"my_statuses":[]})
    try:
        cutoff = int(time.time()) - 86400
        docs = db.collection("statuses").where("time",">=",cutoff).order_by("time").stream()
        all_statuses = [{**d.to_dict(),"id":d.id} for d in docs]
        uid_set = set(s.get("uid") for s in all_statuses if s.get("uid"))
        user_cache = {}
        for uid in uid_set:
            try:
                udoc = db.collection("users").document(uid).get()
                if udoc.exists:
                    ud = udoc.to_dict()
                    user_cache[uid] = {"username": ud.get("username","?"), "avatar": ud.get("avatar","")}
            except: pass
        for s in all_statuses:
            uid = s.get("uid","")
            if uid in user_cache:
                s["username"] = user_cache[uid]["username"]
                s["avatar"]   = user_cache[uid]["avatar"]
        others  = [s for s in all_statuses if s.get("uid") != user["uid"]]
        my_own  = [s for s in all_statuses if s.get("uid") == user["uid"]]
        return jsonify({"statuses":others,"my_statuses":my_own})
    except Exception as e:
        return jsonify({"statuses":[],"my_statuses":[]})

@app.route("/api/status/my")
def api_status_my():
    user = get_current_user(request)
    if not user: return jsonify({"statuses":[]})
    try:
        cutoff = int(time.time()) - 86400
        docs = db.collection("statuses").where("uid","==",user["uid"]).where("time",">=",cutoff).order_by("time").stream()
        return jsonify({"statuses":[{**d.to_dict(),"id":d.id} for d in docs]})
    except: return jsonify({"statuses":[]})

@app.route("/api/status/user/<uid>")
def api_status_user(uid):
    user = get_current_user(request)
    if not user: return jsonify({"statuses":[]})
    try:
        cutoff = int(time.time()) - 86400
        docs = db.collection("statuses").where("uid","==",uid).where("time",">=",cutoff).order_by("time").stream()
        result = [{**d.to_dict(),"id":d.id} for d in docs]
        if not result: return jsonify({"statuses":[]})
        try:
            udoc = db.collection("users").document(uid).get()
            if udoc.exists:
                ud = udoc.to_dict()
                for s in result:
                    s["username"] = ud.get("username","?")
                    s["avatar"]   = ud.get("avatar","")
        except: pass
        for s in result:
            if user["uid"] not in s.get("viewers",[]):
                db.collection("statuses").document(s["id"]).update({"viewers":firestore.ArrayUnion([user["uid"]])})
        return jsonify({"statuses":result})
    except Exception as e:
        return jsonify({"statuses":[]})

# ============================================================
# CALL ROUTES (Firebase signaling, Agora for media)
# ============================================================
@app.route("/api/call/offer", methods=["POST"])
def api_call_offer():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    data = request.get_json()
    call_id = str(uuid.uuid4())
    try:
        db.collection("calls").document(call_id).set({
            "from":user["uid"],"to":data["to_uid"],
            "sdp":data["sdp"],"status":"pending",
            "call_type":data.get("call_type","audio"),
            "time":int(time.time())
        })
        return jsonify({"ok":True,"call_id":call_id})
    except Exception as e:
        return jsonify({"ok":False,"msg":str(e)})

@app.route("/api/call/status/<call_id>")
def api_call_status(call_id):
    user = get_current_user(request)
    if not user: return jsonify({"status":"error"})
    try:
        doc = db.collection("calls").document(call_id).get()
        if not doc.exists: return jsonify({"status":"ended"})
        d = doc.to_dict()
        return jsonify({"status":d.get("status","pending"),"answer":d.get("answer")})
    except: return jsonify({"status":"error"})

@app.route("/api/call/answer", methods=["POST"])
def api_call_answer():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    data = request.get_json()
    try:
        db.collection("calls").document(data["call_id"]).update({"status":"answered","answer":data["answer"]})
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"ok":False,"msg":str(e)})

@app.route("/api/call/reject", methods=["POST"])
def api_call_reject():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    data = request.get_json()
    try:
        db.collection("calls").document(data["call_id"]).update({"status":"rejected"})
        return jsonify({"ok":True})
    except: return jsonify({"ok":False})

@app.route("/api/call/end", methods=["POST"])
def api_call_end():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    data = request.get_json()
    try:
        db.collection("calls").document(data["call_id"]).update({"status":"ended"})
        return jsonify({"ok":True})
    except: return jsonify({"ok":False})

@app.route("/api/call/incoming")
def api_call_incoming():
    user = get_current_user(request)
    if not user: return jsonify({"call":None})
    try:
        cutoff = int(time.time()) - 60
        calls = db.collection("calls")\
            .where("to","==",user["uid"])\
            .where("status","==","pending")\
            .where("time",">=",cutoff)\
            .order_by("time","DESCENDING").limit(1).stream()
        for c in calls:
            d = c.to_dict(); d["call_id"] = c.id
            return jsonify({"call":d})
        return jsonify({"call":None})
    except: return jsonify({"call":None})

# ============================================================
# LIVE STREAMING ROUTES
# ============================================================
@app.route("/api/live/start", methods=["POST"])
def api_live_start():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    data = request.get_json()
    live_id = str(uuid.uuid4())
    try:
        db.collection("lives").document(live_id).set({
            "id": live_id,
            "channel": data.get("channel", ""),
            "host_uid": user["uid"],
            "host_name": user.get("username", data.get("host_name","")),
            "host_avatar": user.get("avatar",""),
            "started_at": int(time.time()),
            "status": "live",
            "viewer_count": 0,
            "viewers": [],
            "comments": []
        })
        return jsonify({"ok":True,"live_id":live_id})
    except Exception as e:
        return jsonify({"ok":False,"msg":str(e)})

@app.route("/api/live/end", methods=["POST"])
def api_live_end():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    data = request.get_json()
    channel = data.get("channel","")
    try:
        lives = db.collection("lives").where("channel","==",channel).where("host_uid","==",user["uid"]).stream()
        for l in lives:
            l.reference.update({"status":"ended","ended_at":int(time.time())})
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"ok":False,"msg":str(e)})

@app.route("/api/live/list")
def api_live_list():
    user = get_current_user(request)
    if not user: return jsonify({"lives":[]})
    try:
        docs = db.collection("lives").where("status","==","live").order_by("started_at","DESCENDING").limit(20).stream()
        lives = []
        for d in docs:
            l = d.to_dict(); l["id"] = d.id
            # Auto-expire lives older than 4 hours
            if int(time.time()) - l.get("started_at",0) > 14400:
                d.reference.update({"status":"ended"})
                continue
            lives.append(l)
        return jsonify({"lives":lives})
    except Exception as e:
        return jsonify({"lives":[]})

@app.route("/api/live/join", methods=["POST"])
def api_live_join():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    data = request.get_json()
    live_id = data.get("live_id","")
    try:
        doc = db.collection("lives").document(live_id).get()
        if not doc.exists: return jsonify({"ok":False,"msg":"Live tidak ditemukan"})
        db.collection("lives").document(live_id).update({
            "viewers": firestore.ArrayUnion([user["uid"]]),
            "viewer_count": firestore.Increment(1)
        })
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"ok":False,"msg":str(e)})

@app.route("/api/live/comment", methods=["POST"])
def api_live_comment():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    data = request.get_json()
    channel = data.get("channel","")
    try:
        lives = db.collection("lives").where("channel","==",channel).where("status","==","live").stream()
        comment = {
            "uid": user["uid"],
            "username": user.get("username","?"),
            "text": data.get("text","")[:200],
            "time": int(time.time())
        }
        for l in lives:
            comments = l.to_dict().get("comments",[])
            comments.append(comment)
            # Keep last 50 comments
            l.reference.update({"comments": comments[-50:]})
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"ok":False,"msg":str(e)})

@app.route("/api/live/comments/<channel>")
def api_live_comments(channel):
    user = get_current_user(request)
    if not user: return jsonify({"comments":[]})
    try:
        lives = db.collection("lives").where("channel","==",channel).where("status","==","live").limit(1).stream()
        for l in lives:
            return jsonify({"comments": l.to_dict().get("comments",[])})
        return jsonify({"comments":[]})
    except: return jsonify({"comments":[]})

# ============================================================
# AI PROXY
# ============================================================
def get_anthropic_key():
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key: return key
    for path in ["/etc/secrets/ANTHROPIC_API_KEY","/etc/secrets/anthropic_api_key","/run/secrets/ANTHROPIC_API_KEY"]:
        try:
            with open(path, "r") as f:
                key = f.read().strip()
                if key: return key
        except: pass
    return ""

@app.route("/api/ai/chat", methods=["POST"])
def api_ai_chat():
    user = get_current_user(request)
    if not user: return jsonify({"ok": False, "msg": "Login dulu"})
    data = request.get_json()
    messages = data.get("messages", [])
    system = data.get("system", "Kamu adalah WaClone AI, asisten pintar. Jawab dalam Bahasa Indonesia.")
    if not messages: return jsonify({"ok": False, "msg": "Pesan kosong"})
    valid = [m for m in messages if m.get("role") in ("user","assistant") and m.get("content","").strip()]
    while valid and valid[0]["role"] != "user": valid.pop(0)
    fixed = []
    for m in valid:
        if not fixed or fixed[-1]["role"] != m["role"]: fixed.append({"role": m["role"], "content": m["content"]})
        else: fixed[-1]["content"] += "\n" + m["content"]
    if not fixed: return jsonify({"ok": False, "msg": "Tidak ada pesan yang valid"})
    api_key = get_anthropic_key()
    if not api_key: return jsonify({"ok": False, "msg": "API key tidak dikonfigurasi."})
    try:
        import urllib.request as _req, json as _json
        payload = _json.dumps({"model":"claude-haiku-4-5-20251001","max_tokens":1024,"system":system,"messages":fixed}).encode("utf-8")
        req = _req.Request("https://api.anthropic.com/v1/messages",data=payload,
            headers={"Content-Type":"application/json","anthropic-version":"2023-06-01","x-api-key":api_key},method="POST")
        with _req.urlopen(req,timeout=30) as resp:
            result = _json.loads(resp.read().decode("utf-8"))
            reply = result.get("content",[{}])[0].get("text","Maaf, tidak bisa menjawab.")
            return jsonify({"ok":True,"reply":reply})
    except Exception as e:
        print("AI error:", e, file=sys.stderr)
        return jsonify({"ok":False,"msg":"AI error: "+str(e)[:200]})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
