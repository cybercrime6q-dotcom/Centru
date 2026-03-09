from flask import Flask, request, jsonify, redirect, make_response
import firebase_admin
from firebase_admin import credentials, firestore, storage, auth
from werkzeug.security import generate_password_hash, check_password_hash
import time, sys, os, uuid

app = Flask(__name__)
db = None
bucket = None

# ===============================
# FIREBASE INIT
# ===============================
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
            "last_message": text or ("ðŸ“Ž Media" if file_url else ""),
            "last_time": int(time.time()),
            "last_from": from_uid
        }, merge=True)
        db.collection("notifications").add({
            "to": to_uid, "from": from_uid,
            "message": text or "ðŸ“Ž Media",
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

# ===============================
# AUTH PAGE
# ===============================
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
        <input id="lp" type="password" placeholder="â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢" onkeydown="if(event.key==='Enter')doLogin()">
        <span class="eye" onclick="togglePw('lp',this)">ðŸ‘ï¸</span>
      </div>
      <div class="err" id="le2"></div>
      <button class="btn" id="lbtn" onclick="doLogin()">Masuk â†’</button>
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
        <span class="eye" onclick="togglePw('rp',this)">ðŸ‘ï¸</span>
      </div>
      <div class="err" id="re2"></div>
      <button class="btn" id="rbtn" onclick="doReg()">Daftar â†’</button>
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
function togglePw(id,el){const i=document.getElementById(id);i.type=i.type==='password'?'text':'password';el.textContent=i.type==='password'?'ðŸ‘ï¸':'ðŸ™ˆ';}
function setLoading(btn,loading){const b=document.getElementById(btn);if(loading){b.disabled=true;b.innerHTML='<span class="spin"></span>';}else{b.disabled=false;b.textContent=btn==='lbtn'?'Masuk â†’':'Daftar â†’';}}
async function doLogin(){
  const email=document.getElementById('le').value.trim(),pass=document.getElementById('lp').value;
  const err=document.getElementById('le2');if(!email||!pass){err.textContent='Isi semua field!';return;}
  setLoading('lbtn',true);const fd=new FormData();fd.append('email',email);fd.append('password',pass);
  const r=await fetch('/login',{method:'POST',body:fd});const d=await r.json();setLoading('lbtn',false);
  if(d.ok){toast('Login berhasil! ðŸŽ‰');setTimeout(()=>location.href='/home',700);}else err.textContent=d.msg||'Login gagal';
}
async function doReg(){
  const u=document.getElementById('ru').value.trim(),e=document.getElementById('re').value.trim(),p=document.getElementById('rp').value;
  const err=document.getElementById('re2');if(!u||!e||!p){err.textContent='Isi semua field!';return;}
  if(p.length<6){err.textContent='Password minimal 6 karakter';return;}
  if(!/^[a-zA-Z0-9_]+$/.test(u)){err.textContent='Username hanya huruf, angka, dan underscore';return;}
  setLoading('rbtn',true);const fd=new FormData();fd.append('username',u);fd.append('email',e);fd.append('password',p);
  const r=await fetch('/register',{method:'POST',body:fd});const d=await r.json();setLoading('rbtn',false);
  if(d.ok){toast('Registrasi berhasil! ðŸŽ‰');setTimeout(()=>location.href='/home',700);}else err.textContent=d.msg||'Registrasi gagal';
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
    if(d.ok){toast('Login Google berhasil! ðŸŽ‰');setTimeout(()=>location.href='/home',700);}
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

# ===============================
# MAIN APP HTML
# ===============================
MAIN_HTML = r"""<!DOCTYPE html>
<html>
<head>
<title>WaClone</title>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800;900&display=swap" rel="stylesheet">
<style>
:root{
  --g:#00a884;--dk:#111b21;--pn:#202c33;--bo:#005c4b;--bi:#202c33;
  --bd:#2a3942;--tx:#e9edef;--st:#8696a0;--hv:#2a3942;--rd:#f15c6d;--bl:#53bdeb;
  --inp:#2a3942;
}
*{margin:0;padding:0;box-sizing:border-box;}
html,body{height:100%;overflow:hidden;}
body{font-family:'Nunito',sans-serif;background:var(--dk);color:var(--tx);display:flex;height:100vh;}
::-webkit-scrollbar{width:5px;}::-webkit-scrollbar-thumb{background:var(--bd);border-radius:3px;}
input,textarea{outline:none;border:none;background:transparent;color:var(--tx);font-family:'Nunito',sans-serif;}
button{cursor:pointer;font-family:'Nunito',sans-serif;border:none;}

/* ===== SIDEBAR ===== */
.sb{width:380px;min-width:320px;max-width:380px;background:var(--pn);display:flex;flex-direction:column;border-right:1px solid var(--bd);height:100vh;overflow:hidden;}
.sbh{padding:10px 16px;display:flex;align-items:center;gap:10px;height:62px;border-bottom:1px solid var(--bd);flex-shrink:0;}
.my-av{width:42px;height:42px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-weight:900;font-size:18px;color:#fff;cursor:pointer;flex-shrink:0;overflow:hidden;}
.my-av img{width:42px;height:42px;object-fit:cover;border-radius:50%;}
.sbh-title{font-size:20px;font-weight:900;flex:1;color:var(--tx);}
.icon-btn{width:40px;height:40px;border-radius:50%;background:transparent;color:var(--st);display:flex;align-items:center;justify-content:center;transition:.2s;position:relative;flex-shrink:0;}
.icon-btn:hover{background:var(--hv);color:var(--tx);}
.badge{position:absolute;top:4px;right:4px;background:var(--rd);color:#fff;border-radius:50%;width:17px;height:17px;font-size:10px;font-weight:900;display:flex;align-items:center;justify-content:center;}

.sbtabs{display:flex;border-bottom:1px solid var(--bd);flex-shrink:0;}
.stab{flex:1;padding:12px;text-align:center;font-size:13px;font-weight:800;color:var(--st);cursor:pointer;border-bottom:2.5px solid transparent;transition:.2s;}
.stab.active{color:var(--g);border-bottom-color:var(--g);}

.search-wrap{padding:8px 12px;flex-shrink:0;}
.search-inner{position:relative;display:flex;align-items:center;}
.search-inner svg{position:absolute;left:12px;color:var(--st);pointer-events:none;}
.search-inner input{width:100%;padding:9px 16px 9px 40px;border-radius:10px;background:var(--dk);font-size:14px;color:var(--tx);border:1.5px solid transparent;}
.search-inner input:focus{border-color:var(--g);}

.chat-list{flex:1;overflow-y:auto;}
.chat-item{display:flex;align-items:center;gap:12px;padding:10px 16px;cursor:pointer;border-bottom:1px solid rgba(255,255,255,.03);transition:.15s;}
.chat-item:hover{background:var(--hv);}
.chat-item.active{background:var(--hv);}
.chat-av{width:50px;height:50px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-weight:900;font-size:20px;color:#fff;flex-shrink:0;position:relative;overflow:hidden;}
.chat-av img{width:50px;height:50px;border-radius:50%;object-fit:cover;}
.online-dot{position:absolute;bottom:2px;right:2px;width:13px;height:13px;background:#44c56a;border-radius:50%;border:2.5px solid var(--pn);}
.chat-info{flex:1;min-width:0;}
.chat-name{font-weight:800;font-size:15px;color:var(--tx);}
.chat-prev{font-size:13px;color:var(--st);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px;}
.chat-meta{display:flex;flex-direction:column;align-items:flex-end;gap:4px;flex-shrink:0;}
.chat-time{font-size:11px;color:var(--st);}
.unread-badge{background:var(--g);color:#fff;border-radius:50%;min-width:20px;height:20px;font-size:11px;font-weight:900;display:flex;align-items:center;justify-content:center;padding:0 4px;}

/* ===== MAIN PANEL ===== */
.main{flex:1;display:flex;flex-direction:column;overflow:hidden;position:relative;height:100vh;}
.no-chat{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;color:var(--st);gap:12px;}
.no-chat svg{opacity:.12;}
.no-chat h2{font-size:22px;font-weight:900;color:var(--tx);}
.no-chat p{font-size:14px;}

/* ===== CHAT HEADER ===== */
.chat-header{height:62px;background:var(--pn);display:flex;align-items:center;gap:10px;padding:0 12px 0 16px;border-bottom:1px solid var(--bd);flex-shrink:0;}
.header-av{width:42px;height:42px;border-radius:50%;overflow:hidden;flex-shrink:0;cursor:pointer;}
.header-av img,.header-av div{width:42px;height:42px;border-radius:50%;}
.header-info{flex:1;cursor:pointer;}
.header-info h3{font-weight:900;font-size:16px;color:var(--tx);}
.header-info p{font-size:12px;color:var(--g);}
.header-btn{width:42px;height:42px;border-radius:50%;background:transparent;color:var(--st);display:flex;align-items:center;justify-content:center;transition:.2s;flex-shrink:0;}
.header-btn:hover{background:var(--hv);color:var(--tx);}
.back-btn{display:none;width:36px;height:36px;border-radius:50%;background:transparent;color:var(--st);align-items:center;justify-content:center;font-size:20px;flex-shrink:0;}

/* ===== MESSAGES AREA ===== */
.messages-area{flex:1;overflow-y:auto;padding:8px 20px 4px;display:flex;flex-direction:column;gap:2px;
  background-color:var(--dk);
  background-image:url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='%23ffffff' fill-opacity='0.015'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/svg%3E");}

.msg-row{display:flex;margin:1px 0;align-items:flex-end;gap:4px;position:relative;}
.msg-row:hover .msg-actions{opacity:1;}
.msg-row.out{justify-content:flex-end;}
.msg-row.in{justify-content:flex-start;}
.msg-actions{opacity:0;transition:opacity .15s;display:flex;gap:3px;align-items:center;}
.msg-row.out .msg-actions{order:-1;}
.act-btn{width:26px;height:26px;border-radius:50%;background:rgba(32,44,51,.9);border:1px solid var(--bd);color:var(--st);font-size:12px;display:flex;align-items:center;justify-content:center;transition:.15s;}
.act-btn:hover{background:var(--hv);color:var(--tx);}

.bubble{max-width:65%;padding:7px 11px 4px;border-radius:12px;font-size:14.5px;line-height:1.5;word-break:break-word;box-shadow:0 1px 2px rgba(0,0,0,.3);position:relative;}
.msg-row.out .bubble{background:var(--bo);border-bottom-right-radius:3px;}
.msg-row.in .bubble{background:#1e2c33;border-bottom-left-radius:3px;}
.bubble-time{font-size:11px;color:rgba(255,255,255,.45);text-align:right;margin-top:2px;display:flex;align-items:center;justify-content:flex-end;gap:3px;white-space:nowrap;}
.tick{font-size:12px;}
.tick.read{color:var(--bl);}
.bubble img{max-width:260px;max-height:260px;border-radius:8px;display:block;margin-bottom:3px;cursor:pointer;object-fit:cover;}
.bubble audio{width:220px;margin-bottom:3px;}
.bubble video{max-width:260px;border-radius:8px;display:block;margin-bottom:3px;}
.bubble a.file-link{color:var(--bl);text-decoration:none;font-size:13px;display:flex;align-items:center;gap:6px;padding:6px 0;}
.date-divider{text-align:center;color:var(--st);font-size:12px;margin:8px 0;}
.date-divider span{background:rgba(17,27,33,.8);padding:4px 14px;border-radius:20px;border:1px solid var(--bd);}

/* Reply quote */
.reply-quote{background:rgba(255,255,255,.07);border-left:3px solid var(--g);border-radius:6px;padding:5px 8px;margin-bottom:5px;font-size:12px;cursor:pointer;}
.reply-quote .rq-name{font-weight:800;color:var(--g);font-size:11px;margin-bottom:2px;}
.reply-quote .rq-text{color:var(--st);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:220px;}

/* Typing indicator */
.typing-wrap{padding:4px 20px;min-height:28px;display:flex;align-items:center;}
.typing-dots{display:none;align-items:center;gap:6px;}
.typing-dots.show{display:flex;}
.dot-anim{display:flex;gap:3px;}
.dot-anim span{width:6px;height:6px;background:var(--st);border-radius:50%;animation:dotBounce 1.4s infinite;}
.dot-anim span:nth-child(2){animation-delay:.2s;}
.dot-anim span:nth-child(3){animation-delay:.4s;}
@keyframes dotBounce{0%,60%,100%{transform:translateY(0);}30%{transform:translateY(-5px);}}
.typing-text{font-size:12px;color:var(--st);}

/* ===== INPUT AREA - KEY FIX ===== */
.input-area{background:var(--pn);padding:6px 10px 8px;border-top:1px solid var(--bd);flex-shrink:0;display:flex;flex-direction:column;gap:6px;}
.reply-preview{display:none;background:rgba(0,168,132,.1);border-left:3px solid var(--g);border-radius:8px;padding:7px 10px;align-items:center;justify-content:space-between;gap:8px;}
.reply-preview.show{display:flex;}
.rp-content{flex:1;min-width:0;}
.rp-name{color:var(--g);font-weight:800;font-size:11px;}
.rp-text{color:var(--st);font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.rp-close{width:24px;height:24px;border-radius:50%;background:var(--bd);color:var(--st);font-size:14px;display:flex;align-items:center;justify-content:center;flex-shrink:0;}
.rp-close:hover{background:var(--hv);color:var(--tx);}

.input-row{display:flex;align-items:flex-end;gap:6px;}
.side-btn{width:40px;height:40px;border-radius:50%;background:transparent;color:var(--st);display:flex;align-items:center;justify-content:center;font-size:20px;flex-shrink:0;transition:.2s;}
.side-btn:hover{background:var(--hv);color:var(--tx);}
.msg-textarea{flex:1;background:var(--inp);border:1.5px solid transparent;border-radius:22px;padding:10px 16px;font-size:15px;color:var(--tx);resize:none;max-height:120px;min-height:44px;line-height:1.4;transition:.2s;display:block;}
.msg-textarea:focus{border-color:var(--g);outline:none;}
.msg-textarea::placeholder{color:var(--st);}
.send-btn{width:44px;height:44px;border-radius:50%;background:var(--g);color:#fff;display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:.2s;}
.send-btn:hover{background:#009070;transform:scale(1.06);}
.rec-btn{width:44px;height:44px;border-radius:50%;background:var(--dk);border:1.5px solid var(--bd);color:var(--st);display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:.2s;}
.rec-btn:hover{background:var(--hv);}
.rec-btn.recording{background:var(--rd);border-color:var(--rd);color:#fff;animation:recPulse 1s infinite;}
@keyframes recPulse{0%,100%{transform:scale(1);}50%{transform:scale(1.1);}}

/* Upload progress */
.upload-progress{height:3px;background:var(--bd);border-radius:3px;overflow:hidden;display:none;}
.upload-progress.show{display:block;}
.upload-fill{height:100%;background:var(--g);width:0%;transition:width .3s;border-radius:3px;}

/* ===== EMOJI PICKER ===== */
.emoji-picker{position:absolute;bottom:70px;right:56px;background:var(--pn);border:1px solid var(--bd);border-radius:16px;padding:10px;box-shadow:0 8px 30px rgba(0,0,0,.6);z-index:200;display:none;width:290px;}
.emoji-picker.open{display:block;}
.emoji-cats{display:flex;gap:2px;margin-bottom:8px;overflow-x:auto;padding-bottom:4px;}
.emoji-cat{padding:4px 8px;border-radius:8px;font-size:14px;cursor:pointer;color:var(--st);}
.emoji-cat.active,.emoji-cat:hover{background:var(--hv);color:var(--tx);}
.emoji-grid{display:flex;flex-wrap:wrap;gap:2px;max-height:180px;overflow-y:auto;}
.emoji-item{font-size:22px;cursor:pointer;padding:4px;border-radius:8px;transition:.1s;line-height:1;}
.emoji-item:hover{background:var(--hv);}

/* ===== ATTACHMENT MENU ===== */
.att-menu{position:absolute;bottom:70px;left:10px;background:var(--pn);border:1px solid var(--bd);border-radius:16px;padding:12px;box-shadow:0 8px 30px rgba(0,0,0,.6);z-index:200;display:none;flex-wrap:wrap;gap:8px;width:230px;}
.att-menu.open{display:flex;}
.att-opt{display:flex;flex-direction:column;align-items:center;gap:5px;cursor:pointer;width:calc(33% - 6px);padding:6px 0;border-radius:10px;transition:.15s;}
.att-opt:hover{background:var(--hv);}
.att-ic{width:46px;height:46px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:20px;}
.att-lbl{font-size:10px;font-weight:700;color:var(--st);}

/* ===== CONTEXT MENU ===== */
.ctx-menu{position:fixed;background:var(--pn);border:1px solid var(--bd);border-radius:14px;box-shadow:0 8px 30px rgba(0,0,0,.6);z-index:500;min-width:180px;overflow:hidden;display:none;}
.ctx-item{padding:11px 18px;font-size:14px;font-weight:700;cursor:pointer;display:flex;align-items:center;gap:10px;transition:.15s;color:var(--tx);}
.ctx-item:hover{background:var(--hv);}
.ctx-item.danger{color:var(--rd);}

/* ===== OVERLAYS ===== */
.overlay{position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:300;display:none;align-items:center;justify-content:center;}
.overlay.open{display:flex;}
.panel{background:var(--pn);border-radius:20px;width:400px;max-height:88vh;overflow-y:auto;border:1px solid var(--bd);box-shadow:0 20px 60px rgba(0,0,0,.6);}
.panel-header{padding:18px 22px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--bd);position:sticky;top:0;background:var(--pn);z-index:1;}
.panel-header h2{font-size:18px;font-weight:900;}
.close-btn{background:var(--hv);border:none;color:var(--st);width:32px;height:32px;border-radius:50%;font-size:16px;display:flex;align-items:center;justify-content:center;cursor:pointer;}
.close-btn:hover{color:var(--tx);}
.panel-body{padding:20px 22px;}

/* Profile panel */
.pav-wrap{text-align:center;margin-bottom:16px;position:relative;display:inline-block;left:50%;transform:translateX(-50%);}
.pav-big{width:100px;height:100px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-size:40px;font-weight:900;color:#fff;overflow:hidden;cursor:pointer;border:3px solid var(--bd);transition:.2s;}
.pav-big:hover{border-color:var(--g);}
.pav-big img{width:100%;height:100%;object-fit:cover;}
.pav-edit-btn{position:absolute;bottom:2px;right:0;background:var(--g);width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.4);font-size:13px;}
.prof-name{font-size:20px;font-weight:900;text-align:center;}
.prof-email{color:var(--st);font-size:13px;text-align:center;margin-top:4px;}
.field-group{margin-bottom:14px;}
.field-group label{display:block;font-size:11px;font-weight:800;color:var(--g);text-transform:uppercase;letter-spacing:.6px;margin-bottom:6px;}
.field-group input,.field-group textarea{width:100%;padding:10px 14px;border-radius:10px;background:var(--dk);border:1.5px solid var(--bd);color:var(--tx);font-size:14px;font-family:'Nunito',sans-serif;transition:.2s;}
.field-group input:focus,.field-group textarea:focus{border-color:var(--g);outline:none;}
.field-group textarea{resize:none;height:72px;line-height:1.5;}
.save-btn{width:100%;padding:12px;background:var(--g);color:#fff;border:none;border-radius:12px;font-size:15px;font-weight:800;margin-top:6px;transition:.2s;cursor:pointer;}
.save-btn:hover{background:#009070;}
.logout-btn{width:100%;padding:11px;background:transparent;color:var(--rd);border:1.5px solid var(--rd);border-radius:12px;font-size:15px;font-weight:800;margin-top:8px;transition:.2s;cursor:pointer;}
.logout-btn:hover{background:var(--rd);color:#fff;}

/* Notification item */
.notif-item{display:flex;gap:10px;align-items:center;padding:10px 0;border-bottom:1px solid var(--bd);cursor:pointer;}
.notif-item:last-child{border-bottom:none;}
.notif-av{width:44px;height:44px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-weight:900;font-size:18px;color:#fff;flex-shrink:0;overflow:hidden;}
.notif-av img{width:44px;height:44px;object-fit:cover;}
.notif-dot{width:9px;height:9px;background:var(--g);border-radius:50%;flex-shrink:0;}

/* Status */
.status-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;}
.status-card{background:var(--dk);border-radius:12px;padding:12px;border:1px solid var(--bd);cursor:pointer;transition:.2s;position:relative;overflow:hidden;}
.status-card:hover{border-color:var(--g);}
.status-card .st-av{width:44px;height:44px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-weight:900;font-size:18px;color:#fff;margin-bottom:8px;overflow:hidden;border:2px solid var(--g);}
.status-card .st-av img{width:44px;height:44px;object-fit:cover;}
.status-thumb{width:100%;height:60px;border-radius:8px;object-fit:cover;margin-bottom:6px;background:var(--bd);}
.my-status-create{background:var(--dk);border:2px dashed var(--bd);border-radius:12px;padding:14px;text-align:center;cursor:pointer;margin-bottom:14px;transition:.2s;}
.my-status-create:hover{border-color:var(--g);}
.create-opts{display:flex;flex-direction:column;gap:8px;}
.create-opt{display:flex;align-items:center;gap:12px;padding:12px;background:var(--dk);border-radius:10px;border:1.5px solid var(--bd);cursor:pointer;transition:.2s;}
.create-opt:hover{border-color:var(--g);}
.create-opt-ic{width:44px;height:44px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:20px;flex-shrink:0;}

/* Status viewer */
.stv{background:#000;width:100%;max-width:460px;border-radius:20px;overflow:hidden;}
.stv-progress{display:flex;gap:3px;padding:10px 12px 6px;}
.stv-seg{flex:1;height:3px;background:rgba(255,255,255,.3);border-radius:3px;overflow:hidden;}
.stv-fill{height:100%;background:#fff;width:0%;transition:width linear;}
.stv-head{display:flex;align-items:center;gap:10px;padding:6px 14px;}
.stv-av{width:34px;height:34px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-weight:900;color:#fff;font-size:14px;overflow:hidden;}
.stv-av img{width:100%;height:100%;object-fit:cover;}
.stv-body{min-height:200px;display:flex;align-items:center;justify-content:center;padding:16px;}
.stv-text{font-size:22px;font-weight:800;text-align:center;color:#fff;padding:24px 16px;width:100%;}
.stv-img{max-width:100%;max-height:400px;object-fit:contain;border-radius:4px;}

/* Camera */
.cam-wrap{background:#000;border-radius:12px;overflow:hidden;}
.cam-wrap video{width:100%;display:block;max-height:280px;object-fit:cover;}
.cam-controls{display:flex;gap:10px;justify-content:center;margin-top:12px;}
.cam-btn{width:52px;height:52px;border-radius:50%;border:none;display:flex;align-items:center;justify-content:center;font-size:20px;cursor:pointer;transition:.2s;}

/* Forward */
.fw-list{display:flex;flex-direction:column;gap:6px;max-height:280px;overflow-y:auto;}
.fw-item{display:flex;align-items:center;gap:10px;padding:10px;background:var(--dk);border-radius:10px;cursor:pointer;border:1.5px solid var(--bd);transition:.15s;}
.fw-item:hover,.fw-item.sel{border-color:var(--g);}
.fw-av{width:38px;height:38px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-weight:900;font-size:15px;color:#fff;flex-shrink:0;overflow:hidden;}
.fw-av img{width:38px;height:38px;object-fit:cover;}

/* Image full view */
.img-fullview{max-width:90vw;max-height:88vh;border-radius:8px;object-fit:contain;}

/* Call UI */
.call-ui{position:fixed;inset:0;background:rgba(0,0,0,.95);z-index:900;display:none;flex-direction:column;align-items:center;justify-content:center;gap:20px;}
.call-ui.active{display:flex;}
.call-video-wrap{display:none;width:100%;max-width:900px;}
.call-vids{display:flex;gap:12px;align-items:center;justify-content:center;}
.call-vids video{border-radius:16px;background:#1a1a2e;}
#remoteVid{width:68%;max-height:68vh;object-fit:cover;}
#localVid{width:28%;max-height:38vh;object-fit:cover;border:2px solid var(--g);}
.call-audio-info{text-align:center;}
.call-person-av{width:110px;height:110px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-size:46px;font-weight:900;color:#fff;margin:0 auto 14px;overflow:hidden;}
.call-person-av img{width:100%;height:100%;object-fit:cover;}
.call-name{font-size:26px;font-weight:900;color:#fff;}
.call-status{font-size:15px;color:rgba(255,255,255,.6);margin-top:6px;}
.call-timer{font-size:18px;color:var(--g);font-weight:800;margin-top:8px;display:none;}
.call-actions{display:flex;gap:18px;margin-top:20px;}
.call-action-btn{width:62px;height:62px;border-radius:50%;border:none;display:flex;align-items:center;justify-content:center;font-size:24px;cursor:pointer;transition:.2s;}
.call-end{background:var(--rd);}
.call-end:hover{transform:scale(1.08);}
.call-toggle{background:#2a2a3e;}
.call-toggle:hover{background:#3a3a5e;}
.call-toggle.on{background:var(--g);}

.incoming-call{position:fixed;bottom:28px;right:28px;background:var(--pn);border:1px solid var(--bd);border-radius:18px;padding:18px;z-index:950;box-shadow:0 20px 60px rgba(0,0,0,.7);min-width:260px;display:none;animation:slideIn .3s ease;}
.incoming-call.show{display:block;}
@keyframes slideIn{from{transform:translateX(100%);opacity:0;}to{transform:none;opacity:1;}}
.inc-av{width:56px;height:56px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-size:22px;font-weight:900;color:#fff;margin:0 auto 8px;overflow:hidden;}
.inc-av img{width:100%;height:100%;object-fit:cover;}
.inc-actions{display:flex;gap:8px;margin-top:12px;}
.inc-ans{flex:1;padding:11px;background:var(--g);color:#fff;border:none;border-radius:10px;font-size:14px;font-weight:800;cursor:pointer;}
.inc-dec{flex:1;padding:11px;background:var(--rd);color:#fff;border:none;border-radius:10px;font-size:14px;font-weight:800;cursor:pointer;}

/* Toast */
.toast{position:fixed;bottom:28px;left:50%;transform:translateX(-50%);background:var(--pn);color:var(--tx);padding:10px 22px;border-radius:12px;border-left:4px solid var(--g);z-index:9999;box-shadow:0 8px 32px rgba(0,0,0,.5);opacity:0;transition:opacity .3s;pointer-events:none;font-weight:700;white-space:nowrap;}
.toast.show{opacity:1;}
.toast.err{border-left-color:var(--rd);}

/* ===== RESPONSIVE MOBILE ===== */
@media(max-width:700px){
  .sb{position:fixed;left:0;top:0;z-index:10;width:100%;max-width:100%;transform:translateX(0);transition:.25s;}
  .sb.hidden{transform:translateX(-100%);}
  .main{width:100%;}
  .back-btn{display:flex!important;}
  .messages-area{padding:8px 10px 4px;}
  .bubble{max-width:80%;}
}
</style>
</head>
<body>

<!-- ===== SIDEBAR ===== -->
<div class="sb" id="sidebar">
  <div class="sbh">
    <div class="my-av" onclick="openPanel('prof-ov')" id="my-av-el">__SIDEBAR_AV__</div>
    <span class="sbh-title">WaClone</span>
    <button class="icon-btn" onclick="openPanel('stat-ov');setTimeout(loadStatuses,80)" title="Status">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><circle cx="12" cy="12" r="10"/><path d="M12 8v4l3 3"/></svg>
    </button>
    <button class="icon-btn" onclick="openNotifPanel()" title="Notifikasi">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M12 22c1.1 0 2-.9 2-2h-4c0 1.1.9 2 2 2zm6-6v-5c0-3.07-1.63-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 1.5v.68C7.64 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z"/></svg>
      <span class="badge" id="notif-badge" style="display:none">0</span>
    </button>
  </div>

  <div class="sbtabs">
    <div class="stab active" onclick="switchTab('chats')" id="tab-chats">ðŸ’¬ Chat</div>
    <div class="stab" onclick="switchTab('contacts')" id="tab-contacts">ðŸ‘¥ Kontak</div>
  </div>

  <div class="search-wrap">
    <div class="search-inner">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M15.5 14h-.79l-.28-.27A6.471 6.471 0 0016 9.5 6.5 6.5 0 109.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/></svg>
      <input type="text" id="search-input" placeholder="Cari pengguna..." oninput="filterList(this.value)">
    </div>
  </div>

  <div class="chat-list" id="chat-list">
    <div style="padding:30px;text-align:center;color:var(--st);font-size:14px;">Memuat...</div>
  </div>
</div>

<!-- ===== MAIN PANEL ===== -->
<div class="main" id="main-panel">
  <!-- No chat selected -->
  <div class="no-chat" id="no-chat">
    <svg width="90" height="90" viewBox="0 0 24 24" fill="currentColor"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg>
    <h2>WaClone</h2>
    <p>Pilih kontak untuk mulai chat ðŸ‘‹</p>
  </div>

  <!-- Chat area (hidden until chat opened) -->
  <div id="chat-wrap" style="display:none;flex-direction:column;height:100%;overflow:hidden;">

    <!-- Header -->
    <div class="chat-header" id="chat-header">
      <button class="back-btn" id="back-btn" onclick="goBack()">&#8592;</button>
      <div class="header-av" id="header-av"></div>
      <div class="header-info" id="header-info">
        <h3 id="header-name">â€”</h3>
        <p id="header-status">â€”</p>
      </div>
      <button class="header-btn" id="btn-audio-call" onclick="startCall('audio')" title="Telepon">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M6.6 10.8c1.4 2.8 3.8 5.1 6.6 6.6l2.2-2.2c.3-.3.7-.4 1-.2 1.1.4 2.3.6 3.6.6.6 0 1 .4 1 1V20c0 .6-.4 1-1 1-9.4 0-17-7.6-17-17 0-.6.4-1 1-1h3.5c.6 0 1 .4 1 1 0 1.3.2 2.5.6 3.6.1.3 0 .7-.2 1L6.6 10.8z"/></svg>
      </button>
      <button class="header-btn" id="btn-video-call" onclick="startCall('video')" title="Video Call">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z"/></svg>
      </button>
    </div>

    <!-- Messages -->
    <div class="messages-area" id="messages-area"></div>

    <!-- Typing indicator -->
    <div class="typing-wrap">
      <div class="typing-dots" id="typing-dots">
        <div class="dot-anim"><span></span><span></span><span></span></div>
        <span class="typing-text" id="typing-text"></span>
      </div>
    </div>

    <!-- Attachment Menu (positioned relative to .main) -->
    <div class="att-menu" id="att-menu">
      <div class="att-opt" onclick="triggerFile('photo')">
        <div class="att-ic" style="background:#1a56db22;">ðŸ“·</div><span class="att-lbl">Foto/Video</span>
      </div>
      <div class="att-opt" onclick="triggerFile('doc')">
        <div class="att-ic" style="background:#7c3aed22;">ðŸ“„</div><span class="att-lbl">Dokumen</span>
      </div>
      <div class="att-opt" onclick="openCameraChat()">
        <div class="att-ic" style="background:#05966922;">ðŸ“¸</div><span class="att-lbl">Kamera</span>
      </div>
    </div>
    <input type="file" id="file-photo" style="display:none" accept="image/*,video/*" onchange="handleUpload(this)">
    <input type="file" id="file-doc" style="display:none" accept=".pdf,.txt,.doc,.docx,.xls,.xlsx,.zip,.rar" onchange="handleUpload(this)">

    <!-- Emoji Picker (positioned relative to .main) -->
    <div class="emoji-picker" id="emoji-picker">
      <div class="emoji-grid" id="emoji-grid"></div>
    </div>

    <!-- Upload progress bar -->
    <div class="upload-progress" id="upload-progress">
      <div class="upload-fill" id="upload-fill"></div>
    </div>

    <!-- ===== INPUT AREA - THE MAIN FIX ===== -->
    <div class="input-area" id="input-area">
      <!-- Reply preview (shown when replying) -->
      <div class="reply-preview" id="reply-preview">
        <div class="rp-content">
          <div class="rp-name" id="rp-name"></div>
          <div class="rp-text" id="rp-text"></div>
        </div>
        <button class="rp-close" onclick="cancelReply()">âœ•</button>
      </div>

      <!-- Main input row -->
      <div class="input-row">
        <!-- Attachment button -->
        <button class="side-btn" onclick="toggleAttMenu()" title="Lampiran">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M16.5 6v11.5c0 2.21-1.79 4-4 4s-4-1.79-4-4V5c0-1.38 1.12-2.5 2.5-2.5s2.5 1.12 2.5 2.5v10.5c0 .55-.45 1-1 1s-1-.45-1-1V6H10v9.5c0 1.38 1.12 2.5 2.5 2.5s2.5-1.12 2.5-2.5V5c0-2.21-1.79-4-4-4S7 2.79 7 5v12.5c0 3.04 2.46 5.5 5.5 5.5s5.5-2.46 5.5-5.5V6h-1.5z"/></svg>
        </button>

        <!-- Emoji button -->
        <button class="side-btn" onclick="toggleEmojiPicker()" title="Emoji">ðŸ˜Š</button>

        <!-- TEXT INPUT - Main focus of the fix -->
        <textarea
          id="msg-input"
          class="msg-textarea"
          rows="1"
          placeholder="Ketik pesan..."
          onkeydown="handleMsgKey(event)"
          oninput="onMsgInput(this)"
        ></textarea>

        <!-- Voice record button (hold to record) -->
        <button class="rec-btn" id="rec-btn"
          onmousedown="startVoice()"
          onmouseup="stopVoice()"
          ontouchstart="startVoice(event)"
          ontouchend="stopVoice(event)"
          title="Tahan untuk merekam suara">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M12 14c1.66 0 2.99-1.34 2.99-3L15 5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.3-3c0 3-2.54 5.1-5.3 5.1S6.7 14 6.7 11H5c0 3.41 2.72 6.23 6 6.72V21h2v-3.28c3.28-.48 6-3.3 6-6.72h-1.7z"/></svg>
        </button>

        <!-- Send button -->
        <button class="send-btn" onclick="sendMessage()" title="Kirim">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="white"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
        </button>
      </div>
    </div>
    <!-- END INPUT AREA -->

  </div><!-- end chat-wrap -->
</div><!-- end main-panel -->

<!-- ===== CONTEXT MENU ===== -->
<div class="ctx-menu" id="ctx-menu">
  <div class="ctx-item" onclick="doReply()">â†©ï¸ Balas</div>
  <div class="ctx-item" onclick="doCopy()">ðŸ“‹ Salin</div>
  <div class="ctx-item" onclick="doForward()">â†ªï¸ Teruskan</div>
  <div class="ctx-item danger" onclick="doDelete()">ðŸ—‘ï¸ Hapus</div>
</div>

<!-- ===== PROFILE OVERLAY ===== -->
<div class="overlay" id="prof-ov">
  <div class="panel">
    <div class="panel-header">
      <h2>ðŸ‘¤ Profil Saya</h2>
      <button class="close-btn" onclick="closePanel('prof-ov')">âœ•</button>
    </div>
    <div class="panel-body">
      <div class="pav-wrap">
        <div class="pav-big" id="pav-big" onclick="document.getElementById('avatar-input').click()">__PROFILE_AV__</div>
        <div class="pav-edit-btn" onclick="document.getElementById('avatar-input').click()">ðŸ“·</div>
        <input type="file" id="avatar-input" style="display:none" accept="image/*,image/heic,image/heif" onchange="uploadAvatar(this)">
      </div>
      <div class="prof-name" id="pname">__USERNAME__</div>
      <div class="prof-email">__EMAIL__</div>
      <div style="margin-top:18px;">
        <div class="field-group">
          <label>Username</label>
          <input id="edit-username" value="__USERNAME__" placeholder="username baru">
        </div>
        <div class="field-group">
          <label>Bio / Status</label>
          <textarea id="edit-bio">__BIO__</textarea>
        </div>
      </div>
      <button class="save-btn" onclick="saveProfile()">ðŸ’¾ Simpan Profil</button>
      <button class="logout-btn" onclick="doLogout()">ðŸšª Logout</button>
    </div>
  </div>
</div>

<!-- ===== NOTIFICATIONS OVERLAY ===== -->
<div class="overlay" id="notif-ov">
  <div class="panel">
    <div class="panel-header">
      <h2>ðŸ”” Notifikasi</h2>
      <button class="close-btn" onclick="closePanel('notif-ov');markNotifsRead()">âœ•</button>
    </div>
    <div class="panel-body" id="notif-list">
      <div style="text-align:center;color:var(--st);padding:20px;">Tidak ada notifikasi</div>
    </div>
  </div>
</div>

<!-- ===== STATUS OVERLAY ===== -->
<div class="overlay" id="stat-ov">
  <div class="panel">
    <div class="panel-header">
      <h2>ðŸ“Š Status</h2>
      <button class="close-btn" onclick="closePanel('stat-ov')">âœ•</button>
    </div>
    <div class="panel-body">
      <div class="my-status-create" onclick="openCreateStatus()">
        <div style="font-size:26px;margin-bottom:4px;">âž•</div>
        <div style="font-weight:800;">Buat Status Baru</div>
        <div style="font-size:12px;color:var(--st);margin-top:2px;">Foto, video, atau teks</div>
      </div>
      <div id="status-list"><div style="text-align:center;color:var(--st);">Memuat...</div></div>
    </div>
  </div>
</div>

<!-- ===== CREATE STATUS OVERLAY ===== -->
<div class="overlay" id="cstat-ov">
  <div class="panel">
    <div class="panel-header">
      <h2>âœï¸ Buat Status</h2>
      <button class="close-btn" onclick="closePanel('cstat-ov')">âœ•</button>
    </div>
    <div class="panel-body">
      <div class="create-opts">
        <div class="create-opt" onclick="showTextStatusForm()">
          <div class="create-opt-ic" style="background:#2563eb22;">âœï¸</div>
          <div><div style="font-weight:800;">Teks</div><div style="font-size:12px;color:var(--st);">Tulis status teks</div></div>
        </div>
        <div class="create-opt" onclick="document.getElementById('stat-photo-in').click()">
          <div class="create-opt-ic" style="background:#dc262622;">ðŸ–¼ï¸</div>
          <div><div style="font-weight:800;">Foto</div><div style="font-size:12px;color:var(--st);">Upload foto</div></div>
        </div>
        <div class="create-opt" onclick="document.getElementById('stat-video-in').click()">
          <div class="create-opt-ic" style="background:#7c3aed22;">ðŸŽ¥</div>
          <div><div style="font-weight:800;">Video</div><div style="font-size:12px;color:var(--st);">Upload video</div></div>
        </div>
        <div class="create-opt" onclick="openCameraStatus()">
          <div class="create-opt-ic" style="background:#05966922;">ðŸ“¸</div>
          <div><div style="font-weight:800;">Kamera</div><div style="font-size:12px;color:var(--st);">Ambil foto langsung</div></div>
        </div>
      </div>
      <input type="file" id="stat-photo-in" accept="image/*,image/heic,image/heif" style="display:none" onchange="uploadStatus(this,'image')">
      <input type="file" id="stat-video-in" accept="video/*" style="display:none" onchange="uploadStatus(this,'video')">
      <div id="text-status-form" style="display:none;margin-top:16px;">
        <div class="field-group">
          <label>Teks Status</label>
          <textarea id="stat-text-inp" placeholder="Tulis status kamu..." style="height:90px;" maxlength="200" oninput="document.getElementById('stat-charcount').textContent=this.value.length+'/200'"></textarea>
          <div style="font-size:11px;color:var(--st);text-align:right;margin-top:3px;" id="stat-charcount">0/200</div>
        </div>
        <button class="save-btn" onclick="postTextStatus()">ðŸ“¤ Posting Status</button>
      </div>
    </div>
  </div>
</div>

<!-- ===== STATUS VIEWER ===== -->
<div class="overlay" id="stview-ov" onclick="closePanel('stview-ov');clearStatusTimer()">
  <div class="stv" onclick="event.stopPropagation()">
    <div class="stv-progress" id="stv-progress"></div>
    <div class="stv-head">
      <div class="stv-av" id="stv-av"></div>
      <div style="flex:1;">
        <div style="font-weight:800;font-size:14px;" id="stv-name"></div>
        <div style="font-size:11px;color:rgba(255,255,255,.6);" id="stv-time"></div>
      </div>
      <button class="close-btn" onclick="closePanel('stview-ov');clearStatusTimer()" style="background:rgba(255,255,255,.1);">âœ•</button>
    </div>
    <div class="stv-body" id="stv-body"></div>
  </div>
</div>

<!-- ===== CAMERA OVERLAY ===== -->
<div class="overlay" id="cam-ov">
  <div class="panel" style="width:420px;">
    <div class="panel-header">
      <h2>ðŸ“· Kamera</h2>
      <button class="close-btn" onclick="closeCamera()">âœ•</button>
    </div>
    <div class="panel-body">
      <div class="cam-wrap"><video id="cam-vid" autoplay playsinline muted></video></div>
      <canvas id="cam-canvas" style="display:none;width:100%;border-radius:10px;margin-top:8px;"></canvas>
      <div class="cam-controls">
        <button class="cam-btn" style="background:var(--g);" onclick="snapPhoto()">ðŸ“¸</button>
        <button class="cam-btn" style="background:#2a3942;" onclick="switchCamFacing()">ðŸ”„</button>
        <button class="cam-btn" style="background:var(--rd);" onclick="closeCamera()">âœ•</button>
      </div>
      <div id="cam-send-wrap" style="display:none;margin-top:10px;">
        <button class="save-btn" onclick="sendCamPhoto()">ðŸ“¤ Kirim Foto</button>
      </div>
    </div>
  </div>
</div>

<!-- ===== FORWARD OVERLAY ===== -->
<div class="overlay" id="fw-ov">
  <div class="panel">
    <div class="panel-header">
      <h2>â†ªï¸ Teruskan Pesan</h2>
      <button class="close-btn" onclick="closePanel('fw-ov')">âœ•</button>
    </div>
    <div class="panel-body">
      <div class="fw-list" id="fw-list"></div>
      <button class="save-btn" id="fw-send-btn" style="display:none;margin-top:14px;" onclick="execForward()">ðŸ“¤ Kirim</button>
    </div>
  </div>
</div>

<!-- ===== IMAGE FULLSCREEN ===== -->
<div class="overlay" id="img-ov" onclick="closePanel('img-ov')">
  <img class="img-fullview" id="img-full" src="" alt="preview">
</div>

<!-- ===== CALL UI ===== -->
<div class="call-ui" id="call-ui">
  <div class="call-video-wrap" id="call-video-wrap">
    <div class="call-vids">
      <video id="remoteVid" autoplay playsinline></video>
      <video id="localVid" autoplay playsinline muted></video>
    </div>
  </div>
  <div class="call-audio-info" id="call-audio-info">
    <div class="call-person-av" id="call-av"></div>
    <div class="call-name" id="call-name"></div>
    <div class="call-status" id="call-status">Memanggil...</div>
    <div class="call-timer" id="call-timer">00:00</div>
  </div>
  <div class="call-actions">
    <button class="call-action-btn call-toggle on" id="btn-mute" onclick="toggleMute()" title="Mute">ðŸŽ¤</button>
    <button class="call-action-btn call-end" onclick="endCall()" title="Akhiri">ðŸ”´</button>
    <button class="call-action-btn call-toggle" id="btn-cam-call" onclick="toggleCamCall()" title="Kamera" style="display:none;">ðŸ“·</button>
    <button class="call-action-btn call-toggle on" id="btn-spk" onclick="toast('Speaker ðŸ”Š',1500)">ðŸ”Š</button>
  </div>
</div>

<!-- ===== INCOMING CALL ===== -->
<div class="incoming-call" id="incoming-call">
  <div class="inc-av" id="inc-av"></div>
  <div style="text-align:center;font-size:17px;font-weight:900;" id="inc-name"></div>
  <div style="text-align:center;font-size:12px;color:var(--st);margin-top:2px;" id="inc-type"></div>
  <div class="inc-actions">
    <button class="inc-ans" onclick="answerCall()">ðŸ“ž Angkat</button>
    <button class="inc-dec" onclick="rejectCall()">ðŸ”´ Tolak</button>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
// ==============================
// CONSTANTS & STATE
// ==============================
const ME = { uid: "__UID__", username: "__USERNAME__" };
const STUN = { iceServers: [{ urls: "stun:stun.l.google.com:19302" }, { urls: "stun:stun1.l.google.com:19302" }] };

const EMOJIS = [
  'ðŸ˜€','ðŸ˜‚','ðŸ˜','ðŸ¥°','ðŸ˜Ž','ðŸ¤”','ðŸ˜­','ðŸ˜¡','ðŸ‘','ðŸ‘Ž','â¤ï¸','ðŸ”¥','âœ…','â­','ðŸŽ‰','ðŸ™',
  'ðŸ’ª','ðŸ˜´','ðŸ¤£','ðŸ˜Š','ðŸ˜˜','ðŸ¤—','ðŸ¥º','ðŸ˜…','ðŸ˜¬','ðŸ¤™','ðŸ’€','ðŸ’‹','ðŸ«‚','ðŸŒŸ','ðŸ’¯','ðŸŽŠ',
  'ðŸ¤©','ðŸ˜±','ðŸ¤¯','ðŸ«¡','ðŸ¥³','ðŸ˜¤','ðŸ«¶','ðŸ‘‹','ðŸ™Œ','ðŸ‘€','ðŸŽµ','ðŸŒˆ','ðŸ•','â˜•','ðŸš€','ðŸ’¡',
  'ðŸŽ¯','ðŸ†','ðŸ’Ž','ðŸŒ¸','ðŸ¦‹','ðŸŒ™','â˜€ï¸','ðŸŒŠ','ðŸ€','ðŸ¶','ðŸ±','ðŸ¦','ðŸ»','ðŸ¦Š','ðŸ¨','ðŸ¼'
];

let allUsers = [], currentFriend = null, pollTimer = null;
let replyData = null, ctxMsgData = null;
let mediaRecorder = null, recChunks = [], isRecording = false;
let pc = null, localStream = null, currentCallId = null, callType = 'audio';
let callTimerInt = null, callSecs = 0, isMuted = false, isCamOff = false;
let incCallInfo = null, camStream = null, camFacing = 'user', camMode = 'chat';
let statusView = null, statusIdx = 0, statusTimerInt = null;
let fwText = '', fwTargetUid = null;
let lastTypingPing = 0;
let camPhotoBlob = null;

// ==============================
// UTILS
// ==============================
function toast(msg, dur = 2500, isErr = false) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast show' + (isErr ? ' err' : '');
  setTimeout(() => t.classList.remove('show'), dur);
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function fmtTime(ts) {
  const d = new Date(ts * 1000), now = new Date();
  if (d.toDateString() === now.toDateString())
    return d.getHours().toString().padStart(2,'0') + ':' + d.getMinutes().toString().padStart(2,'0');
  const diff = Math.floor((now - d) / 86400000);
  if (diff === 1) return 'Kemarin';
  if (diff < 7) return ['Min','Sen','Sel','Rab','Kam','Jum','Sab'][d.getDay()];
  return d.getDate() + '/' + (d.getMonth() + 1);
}

function makeAvatarHtml(u, size = 50) {
  if (u && u.avatar) {
    return `<img src="${u.avatar}" style="width:${size}px;height:${size}px;border-radius:50%;object-fit:cover;" onerror="this.style.display='none'">`;
  }
  const name = (u && u.username) ? u.username : '?';
  const colors = ['#00a884','#7c3aed','#1a56db','#dc2626','#d97706','#059669','#0891b2','#be185d'];
  const bg = colors[(name.charCodeAt(0) || 0) % colors.length];
  const fs = Math.floor(size * 0.42);
  return `<div style="width:${size}px;height:${size}px;border-radius:50%;background:${bg};display:flex;align-items:center;justify-content:center;font-weight:900;font-size:${fs}px;color:#fff;flex-shrink:0;">${name[0].toUpperCase()}</div>`;
}

// ==============================
// PANELS
// ==============================
function openPanel(id) { document.getElementById(id).classList.add('open'); }
function closePanel(id) { document.getElementById(id).classList.remove('open'); }
function openNotifPanel() { openPanel('notif-ov'); loadNotifications(); }
function closeAllMenus() {
  document.getElementById('att-menu').classList.remove('open');
  document.getElementById('emoji-picker').classList.remove('open');
  document.getElementById('ctx-menu').style.display = 'none';
}

// ==============================
// TABS
// ==============================
function switchTab(t) {
  document.querySelectorAll('.stab').forEach(e => e.classList.remove('active'));
  document.getElementById('tab-' + t).classList.add('active');
  renderList();
}

// ==============================
// LOAD USERS
// ==============================
async function loadUsers() {
  try {
    const r = await fetch('/api/users');
    const d = await r.json();
    allUsers = d.users || [];
    renderList();
    checkNotifCount();
  } catch (e) {}
}

function filterList(q) {
  const q2 = q.toLowerCase();
  document.querySelectorAll('.chat-item').forEach(el => {
    el.style.display = el.dataset.name.toLowerCase().includes(q2) ? '' : 'none';
  });
}

function renderList() {
  const list = document.getElementById('chat-list');
  const others = allUsers.filter(u => u.uid !== ME.uid);
  if (!others.length) {
    list.innerHTML = '<div style="padding:30px;text-align:center;color:var(--st);font-size:14px;">Belum ada pengguna lain ðŸ‘¥</div>';
    return;
  }
  list.innerHTML = others.map(u => {
    const av = makeAvatarHtml(u, 50);
    const onlineDot = u.online ? '<div class="online-dot"></div>' : '';
    const preview = escHtml(u.last_msg || u.bio || 'Tap untuk chat').substring(0, 42);
    const tm = u.last_time ? fmtTime(u.last_time) : '';
    const badge = u.unread_count > 0 ? `<div class="unread-badge">${u.unread_count > 99 ? '99+' : u.unread_count}</div>` : '';
    const isActive = currentFriend && currentFriend.uid === u.uid;
    const uname = u.username.replace(/'/g, "\\'").replace(/"/g, '&quot;');
    const uavatar = (u.avatar || '').replace(/'/g, "\\'");
    const ubio = (u.bio || '').replace(/'/g, "\\'");
    return `<div class="chat-item${isActive ? ' active' : ''}" data-uid="${u.uid}" data-name="${u.username}"
      onclick="openChat('${u.uid}','${uname}','${uavatar}','${ubio}')">
      <div class="chat-av">${av}${onlineDot}</div>
      <div class="chat-info">
        <div class="chat-name">${escHtml(u.username)}</div>
        <div class="chat-prev">${preview}</div>
      </div>
      <div class="chat-meta">
        <div class="chat-time">${tm}</div>
        ${badge}
      </div>
    </div>`;
  }).join('');
}

// ==============================
// OPEN CHAT
// ==============================
function openChat(friendUid, friendName, friendAvatar, friendBio) {
  currentFriend = { uid: friendUid, name: friendName, avatar: friendAvatar, bio: friendBio };

  // Show chat area, hide no-chat
  document.getElementById('no-chat').style.display = 'none';
  const cw = document.getElementById('chat-wrap');
  cw.style.display = 'flex';

  // Mobile: hide sidebar
  document.getElementById('sidebar').classList.add('hidden');

  // Update header
  const headerAvEl = document.getElementById('header-av');
  headerAvEl.innerHTML = makeAvatarHtml(currentFriend, 42);

  document.getElementById('header-name').textContent = friendName;
  document.getElementById('header-status').textContent = 'Memuat...';

  // Highlight in list
  document.querySelectorAll('.chat-item').forEach(e => e.classList.toggle('active', e.dataset.uid === friendUid));

  cancelReply();
  closeAllMenus();

  // Load messages
  loadMessages();

  // Start polling
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(() => { loadMessages(); checkTypingStatus(); }, 3000);

  // Mark as read
  fetch('/api/mark_read', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ friend_uid: friendUid }) });

  // Focus the input
  setTimeout(() => document.getElementById('msg-input').focus(), 200);
}

function goBack() {
  document.getElementById('sidebar').classList.remove('hidden');
  document.getElementById('chat-wrap').style.display = 'none';
  document.getElementById('no-chat').style.display = 'flex';
  currentFriend = null;
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
}

// ==============================
// MESSAGES
// ==============================
async function loadMessages() {
  if (!currentFriend) return;
  try {
    const r = await fetch(`/api/messages?friend_uid=${currentFriend.uid}`);
    const d = await r.json();
    renderMessages(d.messages || []);
    // Update status in header
    const f = allUsers.find(u => u.uid === currentFriend.uid);
    if (f) {
      const st = document.getElementById('header-status');
      if (st) st.textContent = f.online ? 'ðŸŸ¢ Online' : (f.last_seen ? `Terakhir ${fmtTime(f.last_seen)}` : 'âš« Offline');
    }
  } catch (e) {}
}

function renderMessages(msgs) {
  const area = document.getElementById('messages-area');
  const atBottom = area.scrollHeight - area.clientHeight <= area.scrollTop + 100;

  if (!msgs.length) {
    area.innerHTML = `<div style="text-align:center;color:var(--st);padding:40px;font-size:14px;">Belum ada pesan. Mulai percakapan! ðŸ‘‹</div>`;
    return;
  }

  let html = '';
  let lastDate = '';

  msgs.forEach(m => {
    const d = new Date(m.time * 1000);
    const ds = d.toLocaleDateString('id-ID', { day: '2-digit', month: 'long', year: 'numeric' });
    if (ds !== lastDate) {
      html += `<div class="date-divider"><span>${ds}</span></div>`;
      lastDate = ds;
    }

    const isOut = m.from === ME.uid;
    const hh = d.getHours().toString().padStart(2,'0');
    const mm2 = d.getMinutes().toString().padStart(2,'0');
    const ts = `${hh}:${mm2}`;

    let tick = '';
    if (isOut) {
      if (m.status === 'read') tick = '<span class="tick read">âœ“âœ“</span>';
      else if (m.status === 'delivered') tick = '<span class="tick">âœ“âœ“</span>';
      else tick = '<span class="tick">âœ“</span>';
    }

    // Reply quote
    let rqHtml = '';
    if (m.reply_to && m.reply_to.text) {
      const rSender = m.reply_to.from === ME.uid ? 'Kamu' : (currentFriend ? currentFriend.name : '?');
      rqHtml = `<div class="reply-quote"><div class="rq-name">${escHtml(rSender)}</div><div class="rq-text">${escHtml(m.reply_to.text)}</div></div>`;
    }

    // Content
    let content = '';
    if (m.file) {
      const ft = m.file_type || '';
      if (ft.startsWith('image/') || /\.(jpg|jpeg|png|gif|webp|bmp|heic|heif)$/i.test(m.file)) {
        content += `<img src="${m.file}" onclick="viewImg('${m.file}')" alt="foto" loading="lazy">`;
      } else if (ft.startsWith('video/') || /\.(mp4|webm|mov|avi|mkv)$/i.test(m.file)) {
        content += `<video src="${m.file}" controls style="max-width:260px;border-radius:8px;display:block;margin-bottom:3px;"></video>`;
      } else if (ft.startsWith('audio/') || /\.(ogg|m4a|wav|mp3|webm)$/i.test(m.file)) {
        content += `<audio src="${m.file}" controls></audio>`;
      } else {
        const fname = m.file.split('/').pop().split('?')[0].substring(0, 32);
        content += `<a class="file-link" href="${m.file}" target="_blank">ðŸ“„ ${escHtml(fname)}</a>`;
      }
    }
    if (m.message) content += `<span>${escHtml(m.message)}</span>`;

    // Safe text for data attributes
    const safeTxt = (m.message || '').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    const safeTxtDbl = safeTxt.replace(/\\/g, '\\\\');

    // Action buttons
    const acts = `<div class="msg-actions">
      <button class="act-btn" onclick='quickReply("${m.id}","${safeTxtDbl}","${m.from}")' title="Balas">â†©</button>
      <button class="act-btn" onclick='showCtxMenu(event,"${m.id}","${safeTxtDbl}","${m.from}")' title="Lainnya">â‹¯</button>
    </div>`;

    html += `<div class="msg-row ${isOut ? 'out' : 'in'}" data-id="${m.id}" data-txt="${safeTxt}" data-from="${m.from}"
      oncontextmenu='showCtxMenu(event,"${m.id}","${safeTxtDbl}","${m.from}")'
      ontouchstart='touchStart(event,"${m.id}","${safeTxtDbl}","${m.from}")'
      ontouchend='touchEnd()'>
      ${isOut ? acts : ''}
      <div class="bubble">${rqHtml}${content}<div class="bubble-time">${ts} ${tick}</div></div>
      ${!isOut ? acts : ''}
    </div>`;
  });

  area.innerHTML = html;
  if (atBottom) area.scrollTop = area.scrollHeight;
}

// ==============================
// INPUT HANDLING - FIXED
// ==============================
function handleMsgKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
}

function onMsgInput(el) {
  // Auto-resize textarea
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 120) + 'px';
  // Typing indicator
  pingTyping();
}

async function sendMessage() {
  const input = document.getElementById('msg-input');
  const text = input.value.trim();
  if (!text || !currentFriend) return;

  // Clear input immediately for responsive feel
  input.value = '';
  input.style.height = 'auto';

  const body = { to_uid: currentFriend.uid, message: text };
  if (replyData) body.reply_to = { id: replyData.id, text: replyData.text, from: replyData.from };

  cancelReply();

  try {
    const r = await fetch('/api/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    const d = await r.json();
    if (d.ok) {
      loadMessages();
    } else {
      toast('Gagal kirim pesan ðŸ˜•', 2500, true);
    }
  } catch (e) {
    toast('Gagal kirim pesan ðŸ˜•', 2500, true);
  }
}

// ==============================
// REPLY
// ==============================
function cancelReply() {
  replyData = null;
  document.getElementById('reply-preview').classList.remove('show');
}

function setReply(id, text, fromUid) {
  replyData = { id, text, from: fromUid };
  const name = fromUid === ME.uid ? 'Kamu' : (currentFriend ? currentFriend.name : '?');
  document.getElementById('rp-name').textContent = name;
  document.getElementById('rp-text').textContent = text || 'Media';
  document.getElementById('reply-preview').classList.add('show');
  document.getElementById('msg-input').focus();
}

function quickReply(id, txt, from) {
  const decoded = txt.replace(/&#39;/g, "'").replace(/&quot;/g, '"');
  setReply(id, decoded, from);
}

// ==============================
// CONTEXT MENU
// ==============================
let touchHoldTimer = null;

function showCtxMenu(e, id, txt, from) {
  e.preventDefault();
  e.stopPropagation();
  ctxMsgData = { id, txt: txt.replace(/&#39;/g, "'").replace(/&quot;/g, '"'), from };
  positionCtx(e.clientX, e.clientY);
}

function positionCtx(x, y) {
  const m = document.getElementById('ctx-menu');
  m.style.display = 'block';
  const mw = m.offsetWidth || 180, mh = m.offsetHeight || 160;
  m.style.left = Math.min(x, window.innerWidth - mw - 10) + 'px';
  m.style.top = Math.min(y, window.innerHeight - mh - 10) + 'px';
  setTimeout(() => document.addEventListener('click', () => { m.style.display = 'none'; }, { once: true }), 50);
}

function touchStart(e, id, txt, from) {
  touchHoldTimer = setTimeout(() => {
    ctxMsgData = { id, txt: txt.replace(/&#39;/g, "'"), from };
    positionCtx(e.touches[0].clientX, e.touches[0].clientY);
  }, 600);
}
function touchEnd() { if (touchHoldTimer) { clearTimeout(touchHoldTimer); touchHoldTimer = null; } }

function doReply() {
  if (!ctxMsgData) return;
  setReply(ctxMsgData.id, ctxMsgData.txt, ctxMsgData.from);
  document.getElementById('ctx-menu').style.display = 'none';
}

function doCopy() {
  if (!ctxMsgData) return;
  navigator.clipboard.writeText(ctxMsgData.txt).then(() => toast('Pesan disalin ðŸ“‹'));
  document.getElementById('ctx-menu').style.display = 'none';
}

function doForward() {
  if (!ctxMsgData) return;
  fwText = ctxMsgData.txt;
  fwTargetUid = null;
  const list = document.getElementById('fw-list');
  const others = allUsers.filter(u => u.uid !== ME.uid);
  list.innerHTML = others.map(u => `<div class="fw-item" id="fw-${u.uid}" onclick="selectFw('${u.uid}')">
    <div class="fw-av">${makeAvatarHtml(u, 38)}</div>
    <span style="font-weight:700;">${escHtml(u.username)}</span>
  </div>`).join('');
  document.getElementById('fw-send-btn').style.display = 'none';
  openPanel('fw-ov');
  document.getElementById('ctx-menu').style.display = 'none';
}

function selectFw(uid) {
  document.querySelectorAll('.fw-item').forEach(e => e.classList.remove('sel'));
  document.getElementById('fw-' + uid).classList.add('sel');
  fwTargetUid = uid;
  document.getElementById('fw-send-btn').style.display = 'block';
}

async function execForward() {
  if (!fwTargetUid || !fwText) return;
  const r = await fetch('/api/send', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ to_uid: fwTargetUid, message: 'â†ªï¸ ' + fwText }) });
  const d = await r.json();
  if (d.ok) { toast('Pesan diteruskan â†ªï¸'); closePanel('fw-ov'); }
  else toast('Gagal meneruskan', 2500, true);
}

async function doDelete() {
  if (!ctxMsgData || !currentFriend) return;
  document.getElementById('ctx-menu').style.display = 'none';
  if (!confirm('Hapus pesan ini?')) return;
  const r = await fetch('/api/delete_message', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ message_id: ctxMsgData.id, friend_uid: currentFriend.uid }) });
  const d = await r.json();
  if (d.ok) { loadMessages(); toast('Pesan dihapus ðŸ—‘ï¸'); }
  else toast('Gagal hapus: ' + (d.msg || ''), 2500, true);
}

// ==============================
// EMOJI PICKER
// ==============================
function buildEmojiGrid() {
  document.getElementById('emoji-grid').innerHTML = EMOJIS.map(e =>
    `<span class="emoji-item" onclick="insertEmoji('${e}')">${e}</span>`
  ).join('');
}

function toggleEmojiPicker() {
  closeAllMenus();
  document.getElementById('emoji-picker').classList.toggle('open');
}

function insertEmoji(e) {
  const inp = document.getElementById('msg-input');
  const s = inp.selectionStart, end = inp.selectionEnd;
  inp.value = inp.value.substring(0, s) + e + inp.value.substring(end);
  inp.selectionStart = inp.selectionEnd = s + e.length;
  inp.focus();
  onMsgInput(inp);
  document.getElementById('emoji-picker').classList.remove('open');
}

// ==============================
// ATTACHMENT MENU
// ==============================
function toggleAttMenu() {
  closeAllMenus();
  document.getElementById('att-menu').classList.toggle('open');
}

function triggerFile(type) {
  document.getElementById('att-menu').classList.remove('open');
  document.getElementById(type === 'photo' ? 'file-photo' : 'file-doc').click();
}

function showUploadBar() {
  const bar = document.getElementById('upload-progress');
  const fill = document.getElementById('upload-fill');
  bar.classList.add('show'); fill.style.width = '0%';
  let w = 0;
  const iv = setInterval(() => { w += Math.random() * 12; if (w >= 88) clearInterval(iv); fill.style.width = Math.min(w, 88) + '%'; }, 200);
  return () => { fill.style.width = '100%'; setTimeout(() => bar.classList.remove('show'), 500); clearInterval(iv); };
}

async function handleUpload(input) {
  if (!input.files[0] || !currentFriend) return;
  document.getElementById('att-menu').classList.remove('open');
  const done = showUploadBar();
  const fd = new FormData();
  fd.append('file', input.files[0]);
  fd.append('to_uid', currentFriend.uid);
  if (replyData) { fd.append('reply_from', replyData.from); fd.append('reply_text', replyData.text); }
  try {
    const r = await fetch('/api/send_file', { method: 'POST', body: fd });
    const d = await r.json(); done();
    if (d.ok) { toast('Terkirim! ðŸ“Ž'); cancelReply(); loadMessages(); }
    else toast('Gagal upload: ' + (d.msg || ''), 3000, true);
  } catch (e) { done(); toast('Gagal upload ðŸ˜•', 2500, true); }
  input.value = '';
}

// ==============================
// CAMERA
// ==============================
function openCameraChat() { document.getElementById('att-menu').classList.remove('open'); camMode = 'chat'; openCamera(); }
function openCameraStatus() { closePanel('cstat-ov'); camMode = 'status'; openCamera(); }

async function openCamera() {
  try {
    camStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: camFacing }, audio: false });
    document.getElementById('cam-vid').srcObject = camStream;
    document.getElementById('cam-canvas').style.display = 'none';
    document.getElementById('cam-send-wrap').style.display = 'none';
    camPhotoBlob = null;
    openPanel('cam-ov');
  } catch (e) { toast('Kamera tidak dapat diakses: ' + e.message, 3000, true); }
}

function switchCamFacing() {
  camFacing = camFacing === 'user' ? 'environment' : 'user';
  closeCamera(); setTimeout(openCamera, 200);
}

function snapPhoto() {
  const vid = document.getElementById('cam-vid');
  const canvas = document.getElementById('cam-canvas');
  canvas.width = vid.videoWidth; canvas.height = vid.videoHeight;
  canvas.getContext('2d').drawImage(vid, 0, 0);
  canvas.style.display = 'block';
  canvas.toBlob(blob => { camPhotoBlob = blob; }, 'image/jpeg', 0.92);
  document.getElementById('cam-send-wrap').style.display = 'block';
}

async function sendCamPhoto() {
  if (!camPhotoBlob) { toast('Ambil foto dulu!', 2000, true); return; }
  closeCamera();
  const done = showUploadBar();
  const fd = new FormData();
  fd.append('file', new File([camPhotoBlob], 'camera.jpg', { type: 'image/jpeg' }));
  if (camMode === 'status') {
    fd.append('type', 'image');
    const r = await fetch('/api/status/upload', { method: 'POST', body: fd });
    const d = await r.json(); done();
    if (d.ok) { toast('Status diposting! âœ…'); openPanel('stat-ov'); loadStatuses(); }
    else toast('Gagal upload status', 2500, true);
  } else {
    if (!currentFriend) { done(); toast('Pilih chat dulu!', 2000, true); return; }
    fd.append('to_uid', currentFriend.uid);
    const r = await fetch('/api/send_file', { method: 'POST', body: fd });
    const d = await r.json(); done();
    if (d.ok) { toast('Foto terkirim! ðŸ“¸'); loadMessages(); }
    else toast('Gagal kirim foto', 2500, true);
  }
}

function closeCamera() {
  if (camStream) camStream.getTracks().forEach(t => t.stop());
  camStream = null; closePanel('cam-ov');
}

// ==============================
// VOICE RECORDING
// ==============================
async function startVoice(e) {
  if (e) e.preventDefault();
  if (!currentFriend) { toast('Pilih chat dulu!', 2000, true); return; }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const mime = MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : 'audio/ogg';
    mediaRecorder = new MediaRecorder(stream, { mimeType: mime });
    recChunks = []; isRecording = true;
    mediaRecorder.ondataavailable = e => recChunks.push(e.data);
    mediaRecorder.onstop = async () => {
      const blob = new Blob(recChunks, { type: mime });
      stream.getTracks().forEach(t => t.stop());
      if (blob.size > 500 && currentFriend) {
        const done = showUploadBar();
        const fd = new FormData();
        fd.append('file', new File([blob], 'voice.webm', { type: mime }));
        fd.append('to_uid', currentFriend.uid);
        const r = await fetch('/api/send_file', { method: 'POST', body: fd });
        const d = await r.json(); done();
        if (d.ok) { toast('Pesan suara terkirim ðŸŽ™ï¸'); loadMessages(); }
        else toast('Gagal kirim suara', 2500, true);
      }
    };
    mediaRecorder.start();
    document.getElementById('rec-btn').classList.add('recording');
    toast('Merekam... Lepaskan untuk kirim ðŸŽ™ï¸', 15000);
  } catch (e) { toast('Mikrofon tidak dapat diakses', 2500, true); }
}

function stopVoice(e) {
  if (e) e.preventDefault();
  if (mediaRecorder && isRecording) {
    mediaRecorder.stop(); isRecording = false;
    document.getElementById('rec-btn').classList.remove('recording');
    toast('Mengirim suara...', 1500);
  }
}

// ==============================
// IMAGE VIEWER
// ==============================
function viewImg(src) { document.getElementById('img-full').src = src; openPanel('img-ov'); }

// ==============================
// TYPING INDICATOR
// ==============================
async function pingTyping() {
  const now = Date.now();
  if (now - lastTypingPing < 2000 || !currentFriend) return;
  lastTypingPing = now;
  await fetch('/api/typing', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ to_uid: currentFriend.uid }) });
}

async function checkTypingStatus() {
  if (!currentFriend) return;
  try {
    const r = await fetch(`/api/typing_status?friend_uid=${currentFriend.uid}`);
    const d = await r.json();
    const dots = document.getElementById('typing-dots');
    if (d.typing) {
      document.getElementById('typing-text').textContent = currentFriend.name + ' sedang mengetik...';
      dots.classList.add('show');
    } else {
      dots.classList.remove('show');
    }
  } catch (e) {}
}

// ==============================
// PROFILE
// ==============================
async function uploadAvatar(input) {
  if (!input.files[0]) return;
  const file = input.files[0];
  if (file.size > 10 * 1024 * 1024) { toast('Ukuran foto max 10MB', 2500, true); return; }
  const done = showUploadBar();
  const fd = new FormData(); fd.append('avatar', file);
  try {
    const r = await fetch('/api/upload_avatar', { method: 'POST', body: fd });
    const d = await r.json(); done();
    if (d.ok) {
      const url = d.url + '?t=' + Date.now();
      document.getElementById('pav-big').innerHTML = `<img src="${url}" style="width:100%;height:100%;object-fit:cover;">`;
      document.getElementById('my-av-el').innerHTML = `<img src="${url}" style="width:42px;height:42px;border-radius:50%;object-fit:cover;">`;
      toast('Foto profil diperbarui âœ…');
    } else toast('Gagal upload: ' + (d.msg || ''), 3000, true);
  } catch (e) { done(); toast('Gagal upload foto', 2500, true); }
  input.value = '';
}

async function saveProfile() {
  const u = document.getElementById('edit-username').value.trim();
  const b = document.getElementById('edit-bio').value.trim();
  if (!u) { toast('Username tidak boleh kosong', 2500, true); return; }
  const fd = new FormData(); fd.append('username', u); fd.append('bio', b);
  const r = await fetch('/api/update_profile', { method: 'POST', body: fd });
  const d = await r.json();
  if (d.ok) {
    document.getElementById('pname').textContent = u;
    toast('Profil disimpan âœ…'); closePanel('prof-ov');
    setTimeout(() => location.reload(), 800);
  } else toast('Gagal simpan: ' + (d.msg || ''), 3000, true);
}

function doLogout() {
  if (confirm('Yakin mau logout?')) {
    fetch('/logout', { method: 'POST' }).then(() => location.href = '/');
  }
}

// ==============================
// NOTIFICATIONS
// ==============================
async function checkNotifCount() {
  try {
    const r = await fetch('/api/notifications');
    const d = await r.json();
    const cnt = (d.notifications || []).filter(n => !n.read).length;
    const b = document.getElementById('notif-badge');
    b.style.display = cnt > 0 ? '' : 'none';
    b.textContent = cnt > 9 ? '9+' : cnt;
  } catch (e) {}
}

async function loadNotifications() {
  const r = await fetch('/api/notifications');
  const d = await r.json();
  const el = document.getElementById('notif-list');
  const notifs = d.notifications || [];
  if (!notifs.length) { el.innerHTML = '<div style="text-align:center;color:var(--st);padding:24px;">Tidak ada notifikasi ðŸŽ‰</div>'; return; }
  el.innerHTML = notifs.slice().reverse().map(n => {
    const u = allUsers.find(u => u.uid === n.from);
    const nm = u?.username || 'Pengguna';
    const av = u ? makeAvatarHtml(u, 44) : `<div style="width:44px;height:44px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:900;color:#fff;">${nm[0].toUpperCase()}</div>`;
    return `<div class="notif-item" onclick="closePanel('notif-ov');openChat('${n.from}','${(nm).replace(/'/g,"\\'")}','${u?.avatar||''}','')">
      <div class="notif-av">${av}</div>
      <div style="flex:1;">
        <div style="font-weight:800;font-size:14px;">${escHtml(nm)}</div>
        <div style="font-size:12px;color:var(--st);margin-top:2px;">${escHtml(n.message)}</div>
        <div style="font-size:11px;color:var(--st);margin-top:2px;">${fmtTime(n.time)}</div>
      </div>
      ${!n.read ? '<div class="notif-dot"></div>' : ''}
    </div>`;
  }).join('');
}

async function markNotifsRead() {
  await fetch('/api/notifications/read', { method: 'POST' });
  checkNotifCount();
}

// ==============================
// STATUS
// ==============================
async function loadStatuses() {
  try {
    const r = await fetch('/api/status/list');
    const d = await r.json();
    const sl = document.getElementById('status-list');
    const stats = d.statuses || [];
    const myStats = d.my_statuses || [];
    let html = '';

    if (myStats.length > 0) {
      const latest = myStats[myStats.length - 1];
      const thumb = latest.type === 'image' && latest.media_url ? `<img class="status-thumb" src="${latest.media_url}" alt="">` : '';
      html += `<div style="margin-bottom:14px;">
        <div style="font-size:11px;font-weight:800;color:var(--st);text-transform:uppercase;letter-spacing:.6px;margin-bottom:8px;">Status Saya</div>
        <div class="status-card" onclick="viewMyStatus()" style="border-color:var(--g);">
          ${thumb}
          <div class="st-av">${makeAvatarHtml({username:ME.username}, 44)}</div>
          <div style="font-weight:800;font-size:13px;">${escHtml(ME.username)}</div>
          <div style="font-size:11px;color:var(--st);">${fmtTime(latest.time)} Â· ${myStats.length} status</div>
        </div>
      </div>`;
    }

    if (stats.length > 0) {
      const byUser = {};
      stats.forEach(s => { if (!byUser[s.uid]) byUser[s.uid] = []; byUser[s.uid].push(s); });
      html += `<div style="font-size:11px;font-weight:800;color:var(--st);text-transform:uppercase;letter-spacing:.6px;margin-bottom:8px;">Terbaru</div>`;
      html += `<div class="status-grid">` + Object.entries(byUser).map(([uid, sts]) => {
        const u = allUsers.find(x => x.uid === uid) || { uid, username: '?', avatar: '' };
        const latest = sts[sts.length - 1];
        const thumb = latest.type === 'image' && latest.media_url ? `<img class="status-thumb" src="${latest.media_url}" alt="">` : '';
        return `<div class="status-card" onclick="viewStatus('${uid}')">
          ${u.online ? '<div style="position:absolute;top:8px;right:8px;width:9px;height:9px;background:#44c56a;border-radius:50%;"></div>' : ''}
          ${thumb}
          <div class="st-av">${makeAvatarHtml(u, 44)}</div>
          <div style="font-weight:800;font-size:13px;">${escHtml(u.username)}</div>
          <div style="font-size:11px;color:var(--st);">${fmtTime(latest.time)} Â· ${sts.length} status</div>
        </div>`;
      }).join('') + `</div>`;
    }

    if (!html) html = '<div style="text-align:center;color:var(--st);padding:20px;">Belum ada status ðŸ“­</div>';
    sl.innerHTML = html;
  } catch (e) { console.error('loadStatuses:', e); }
}

async function viewMyStatus() {
  const r = await fetch('/api/status/my');
  const d = await r.json();
  const sts = d.statuses || [];
  if (!sts.length) return;
  statusView = { uid: ME.uid, user: { uid: ME.uid, username: ME.username, avatar: '' }, statuses: sts };
  statusIdx = 0; renderStatusView(); openPanel('stview-ov');
}

async function viewStatus(uid) {
  const r = await fetch(`/api/status/user/${uid}`);
  const d = await r.json();
  const sts = d.statuses || [];
  if (!sts.length) return;
  const u = allUsers.find(x => x.uid === uid) || { username: '?', avatar: '', uid };
  statusView = { uid, user: u, statuses: sts };
  statusIdx = 0; renderStatusView(); openPanel('stview-ov');
}

function clearStatusTimer() { if (statusTimerInt) { clearInterval(statusTimerInt); statusTimerInt = null; } }

function renderStatusView() {
  const { user, statuses } = statusView;
  const s = statuses[statusIdx];
  document.getElementById('stv-av').innerHTML = makeAvatarHtml(user, 34);
  document.getElementById('stv-name').textContent = user.username;
  document.getElementById('stv-time').textContent = fmtTime(s.time);
  document.getElementById('stv-progress').innerHTML = statuses.map((_, i) =>
    `<div class="stv-seg"><div class="stv-fill" id="stv-f-${i}" style="width:${i < statusIdx ? 100 : 0}%"></div></div>`
  ).join('');
  let body = '';
  if (s.type === 'text') {
    const bgColors = ['#005c4b','#1a56db','#7c3aed','#dc2626','#d97706'];
    const bg = bgColors[statusIdx % bgColors.length];
    body = `<div class="stv-text" style="background:${bg};border-radius:12px;width:100%;">${escHtml(s.content)}</div>`;
  } else if (s.type === 'image') {
    body = `<img class="stv-img" src="${s.media_url}" alt="status">`;
  } else if (s.type === 'video') {
    body = `<video src="${s.media_url}" controls autoplay style="max-width:100%;max-height:380px;border-radius:10px;"></video>`;
  }
  document.getElementById('stv-body').innerHTML = body;
  clearStatusTimer();
  const fill = document.getElementById(`stv-f-${statusIdx}`);
  if (fill) {
    fill.style.transition = ''; fill.style.width = '0%';
    requestAnimationFrame(() => { fill.style.transition = 'width 5s linear'; fill.style.width = '100%'; });
  }
  statusTimerInt = setInterval(() => {
    statusIdx++;
    if (statusIdx >= statuses.length) { clearStatusTimer(); closePanel('stview-ov'); }
    else renderStatusView();
  }, 5000);
}

function openCreateStatus() { closePanel('stat-ov'); document.getElementById('text-status-form').style.display = 'none'; openPanel('cstat-ov'); }
function showTextStatusForm() { document.getElementById('text-status-form').style.display = 'block'; }

async function postTextStatus() {
  const txt = document.getElementById('stat-text-inp').value.trim();
  if (!txt) { toast('Tulis status dulu!', 2000, true); return; }
  const r = await fetch('/api/status/create', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ type: 'text', content: txt }) });
  const d = await r.json();
  if (d.ok) {
    toast('Status diposting! âœ…'); closePanel('cstat-ov');
    document.getElementById('stat-text-inp').value = '';
    document.getElementById('stat-charcount').textContent = '0/200';
    openPanel('stat-ov'); loadStatuses();
  } else toast('Gagal posting: ' + (d.msg || ''), 3000, true);
}

async function uploadStatus(input, type) {
  if (!input.files[0]) return;
  const done = showUploadBar();
  const fd = new FormData(); fd.append('file', input.files[0]); fd.append('type', type);
  const r = await fetch('/api/status/upload', { method: 'POST', body: fd });
  const d = await r.json(); done();
  if (d.ok) { toast('Status diposting! âœ…'); closePanel('cstat-ov'); openPanel('stat-ov'); loadStatuses(); }
  else toast('Gagal upload status: ' + (d.msg || ''), 3000, true);
  input.value = '';
}

// ==============================
// CALLS (WebRTC)
// ==============================
async function startCall(type) {
  if (!currentFriend) { toast('Pilih teman dulu'); return; }
  callType = type;
  try {
    localStream = await navigator.mediaDevices.getUserMedia(type === 'video' ? { video: true, audio: true } : { audio: true });
  } catch (e) { toast('Tidak bisa akses ' + (type === 'video' ? 'kamera/' : '') + 'mikrofon: ' + e.message, 3000, true); return; }
  showCallPanel(currentFriend, type, 'outgoing');
  pc = new RTCPeerConnection(STUN);
  localStream.getTracks().forEach(t => pc.addTrack(t, localStream));
  if (type === 'video') document.getElementById('localVid').srcObject = localStream;
  pc.ontrack = e => { document.getElementById('remoteVid').srcObject = e.streams[0]; };
  pc.onicecandidate = e => { if (e.candidate) sendIce({ candidate: e.candidate }); };
  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  const r = await fetch('/api/call/offer', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ to_uid: currentFriend.uid, sdp: offer, call_type: type }) });
  const d = await r.json();
  currentCallId = d.call_id;
  pollCallAnswer();
}

async function pollCallAnswer() {
  if (!currentCallId) return;
  const r = await fetch(`/api/call/status/${currentCallId}`);
  const d = await r.json();
  if (d.status === 'answered') {
    await pc.setRemoteDescription(new RTCSessionDescription(d.answer));
    document.getElementById('call-status').textContent = 'Terhubung âœ…';
    startCallTimer();
    if (callType === 'video') {
      document.getElementById('call-video-wrap').style.display = 'block';
      document.getElementById('call-audio-info').style.display = 'none';
      document.getElementById('btn-cam-call').style.display = '';
    }
    pollIce();
  } else if (d.status === 'rejected') { toast('Panggilan ditolak ðŸ”´', 3000); endCall(); }
  else if (d.status === 'pending') setTimeout(pollCallAnswer, 2000);
  else if (d.status === 'ended') endCall();
}

async function sendIce(data) {
  if (!currentCallId) return;
  await fetch('/api/call/ice', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ call_id: currentCallId, type: 'ice', data }) });
}

async function pollIce() {
  if (!currentCallId || !pc) return;
  const r = await fetch(`/api/call/ice/${currentCallId}?uid=${ME.uid}`);
  const d = await r.json();
  for (const c of (d.candidates || [])) { try { await pc.addIceCandidate(new RTCIceCandidate(c)); } catch (e) {} }
  if (currentCallId) setTimeout(pollIce, 2000);
}

async function answerCall() {
  if (!incCallInfo) return;
  currentCallId = incCallInfo.call_id; callType = incCallInfo.call_type || 'audio';
  document.getElementById('incoming-call').classList.remove('show');
  const caller = allUsers.find(u => u.uid === incCallInfo.from) || { username: '?', avatar: '', uid: incCallInfo.from };
  try {
    localStream = await navigator.mediaDevices.getUserMedia(callType === 'video' ? { video: true, audio: true } : { audio: true });
  } catch (e) { toast('Tidak bisa akses media', 2500, true); return; }
  showCallPanel(caller, callType, 'incoming');
  pc = new RTCPeerConnection(STUN);
  localStream.getTracks().forEach(t => pc.addTrack(t, localStream));
  if (callType === 'video') {
    document.getElementById('localVid').srcObject = localStream;
    document.getElementById('call-video-wrap').style.display = 'block';
    document.getElementById('call-audio-info').style.display = 'none';
    document.getElementById('btn-cam-call').style.display = '';
  }
  pc.ontrack = e => { document.getElementById('remoteVid').srcObject = e.streams[0]; };
  pc.onicecandidate = e => { if (e.candidate) sendIce({ candidate: e.candidate }); };
  await pc.setRemoteDescription(new RTCSessionDescription(incCallInfo.sdp));
  const answer = await pc.createAnswer();
  await pc.setLocalDescription(answer);
  await fetch('/api/call/answer', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ call_id: currentCallId, answer }) });
  document.getElementById('call-status').textContent = 'Terhubung âœ…';
  startCallTimer(); pollIce();
}

function rejectCall() {
  if (incCallInfo) fetch('/api/call/reject', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ call_id: incCallInfo.call_id }) });
  document.getElementById('incoming-call').classList.remove('show'); incCallInfo = null;
}

function showCallPanel(friend, type, dir) {
  document.getElementById('call-ui').classList.add('active');
  const name = friend.username || friend.name || '?';
  const avHtml = friend.avatar ? `<img src="${friend.avatar}" style="width:110px;height:110px;border-radius:50%;object-fit:cover;">` : name[0].toUpperCase();
  document.getElementById('call-av').innerHTML = avHtml;
  document.getElementById('call-name').textContent = name;
  document.getElementById('call-status').textContent = dir === 'outgoing' ? 'Memanggil...' : 'Panggilan masuk...';
  document.getElementById('call-timer').style.display = 'none';
  document.getElementById('call-audio-info').style.display = 'block';
  document.getElementById('call-video-wrap').style.display = 'none';
  document.getElementById('btn-cam-call').style.display = 'none';
}

function endCall() {
  if (pc) { pc.close(); pc = null; }
  if (localStream) localStream.getTracks().forEach(t => t.stop()); localStream = null;
  if (callTimerInt) { clearInterval(callTimerInt); callTimerInt = null; }
  if (currentCallId) { fetch('/api/call/end', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ call_id: currentCallId }) }); currentCallId = null; }
  document.getElementById('call-ui').classList.remove('active');
  callSecs = 0; isMuted = false; isCamOff = false;
}

function startCallTimer() {
  callSecs = 0; document.getElementById('call-timer').style.display = 'block';
  callTimerInt = setInterval(() => {
    callSecs++;
    const m = Math.floor(callSecs / 60).toString().padStart(2, '0');
    const s = (callSecs % 60).toString().padStart(2, '0');
    document.getElementById('call-timer').textContent = m + ':' + s;
  }, 1000);
}

function toggleMute() {
  isMuted = !isMuted;
  if (localStream) localStream.getAudioTracks().forEach(t => t.enabled = !isMuted);
  const btn = document.getElementById('btn-mute');
  btn.textContent = isMuted ? 'ðŸ”‡' : 'ðŸŽ¤';
  btn.classList.toggle('on', !isMuted);
}

function toggleCamCall() {
  isCamOff = !isCamOff;
  if (localStream) localStream.getVideoTracks().forEach(t => t.enabled = !isCamOff);
  const btn = document.getElementById('btn-cam-call');
  btn.textContent = isCamOff ? 'ðŸš«ðŸ“·' : 'ðŸ“·';
  btn.classList.toggle('on', !isCamOff);
}

async function checkIncomingCall() {
  if (pc) return;
  try {
    const r = await fetch('/api/call/incoming');
    const d = await r.json();
    if (d.call && (!incCallInfo || incCallInfo.call_id !== d.call.call_id)) {
      incCallInfo = d.call;
      const caller = allUsers.find(u => u.uid === d.call.from) || { username: 'Seseorang', avatar: '', uid: d.call.from };
      document.getElementById('inc-av').innerHTML = makeAvatarHtml(caller, 56);
      document.getElementById('inc-name').textContent = caller.username;
      document.getElementById('inc-type').textContent = d.call.call_type === 'video' ? 'ðŸ“¹ Video Call Masuk' : 'ðŸ“ž Panggilan Masuk';
      document.getElementById('incoming-call').classList.add('show');
      setTimeout(() => { if (incCallInfo && incCallInfo.call_id === d.call.call_id) rejectCall(); }, 30000);
    }
  } catch (e) {}
}

// ==============================
// INIT
// ==============================
buildEmojiGrid();
loadUsers();

async function updatePresence() {
  try { await fetch('/api/presence', { method: 'POST' }); } catch (e) {}
}
updatePresence();

// Main polling interval: users, notifs, presence, incoming calls
setInterval(() => {
  loadUsers(); checkNotifCount(); updatePresence(); checkIncomingCall();
}, 5000);

// Close menus on outside click
document.addEventListener('click', e => {
  const attMenu = document.getElementById('att-menu');
  const emojiPicker = document.getElementById('emoji-picker');
  if (!attMenu.contains(e.target) && !e.target.closest('.side-btn[title="Lampiran"]')) {
    attMenu.classList.remove('open');
  }
  if (!emojiPicker.contains(e.target) && !e.target.closest('.side-btn[title="Emoji"]')) {
    emojiPicker.classList.remove('open');
  }
});

// Make sidebar hidden by default on mobile check
function checkMobile() {
  if (window.innerWidth <= 700) {
    document.getElementById('back-btn').style.display = 'flex';
    if (currentFriend) document.getElementById('sidebar').classList.add('hidden');
  } else {
    document.getElementById('back-btn').style.display = 'none';
    document.getElementById('sidebar').classList.remove('hidden');
  }
}
checkMobile();
window.addEventListener('resize', checkMobile);
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
    return html

# ============================
# ROUTES
# ============================
@app.route("/")
def index():
    user = get_current_user(request)
    return redirect("/home") if user else AUTH_PAGE

@app.route("/home")
def home():
    user = get_current_user(request)
    if not user: return redirect("/")
    return main_app_html(user)

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

@app.route("/google_auth", methods=["POST"])
def google_auth():
    data = request.get_json()
    id_token = data.get("id_token","")
    if not id_token:
        return jsonify({"ok":False,"msg":"Token tidak valid"})
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
        resp.set_cookie("uid", uid, max_age=7*24*3600, httponly=True, samesite='Lax')
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
    if len(password) < 6:
        return jsonify({"ok":False,"msg":"Password minimal 6 karakter"})
    if not all(c.isalnum() or c in '_' for c in username):
        return jsonify({"ok":False,"msg":"Username hanya boleh huruf, angka, dan underscore"})
    if len(username) < 3:
        return jsonify({"ok":False,"msg":"Username minimal 3 karakter"})
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
        resp.set_cookie("uid", fu.uid, max_age=7*24*3600, httponly=True, samesite='Lax')
        return resp
    except Exception as e:
        print("Register error:", e, file=sys.stderr)
        return jsonify({"ok":False,"msg":str(e)})

@app.route("/login", methods=["POST"])
def login():
    email    = request.form.get("email","").strip()
    password = request.form.get("password","")
    if not email or not password:
        return jsonify({"ok":False,"msg":"Email/password kosong"})
    try:
        users = db.collection("users").where("email","==",email).get()
        if not users: return jsonify({"ok":False,"msg":"Email tidak ditemukan"})
        u = users[0].to_dict()
        if u.get("auth_provider") == "google":
            return jsonify({"ok":False,"msg":"Akun ini terdaftar via Google, gunakan tombol 'Lanjutkan dengan Google'"})
        if not u.get("password"):
            return jsonify({"ok":False,"msg":"Akun ini tidak memiliki password"})
        if check_password_hash(u.get("password",""), password):
            uid = u.get("uid")
            db.collection("users").document(uid).update({"online":True,"last_seen":int(time.time())})
            resp = make_response(jsonify({"ok":True}))
            resp.set_cookie("uid", uid, max_age=7*24*3600, httponly=True, samesite='Lax')
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
    if not f: return jsonify({"ok":False,"msg":"Tidak ada file yang diupload"})
    allowed_img = {'png','jpg','jpeg','gif','webp','bmp','heic','heif'}
    ext = f.filename.rsplit('.',1)[-1].lower() if '.' in f.filename else ''
    if ext not in allowed_img:
        return jsonify({"ok":False,"msg":f"Format gambar tidak didukung ({ext})"})
    try:
        url, _ = upload_to_storage(f, "avatars")
        db.collection("users").document(user["uid"]).update({"avatar":url})
        return jsonify({"ok":True,"url":url})
    except Exception as e:
        print("upload_avatar error:", e, file=sys.stderr)
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
        print("status_upload error:", e, file=sys.stderr)
        return jsonify({"ok":False,"msg":str(e)})

@app.route("/api/status/list")
def api_status_list():
    user = get_current_user(request)
    if not user: return jsonify({"statuses":[],"my_statuses":[]})
    try:
        cutoff = int(time.time()) - 86400
        docs = db.collection("statuses").where("time",">=",cutoff).order_by("time").stream()
        all_statuses = [{**d.to_dict(),"id":d.id} for d in docs]
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
        for s in result:
            if user["uid"] not in s.get("viewers",[]):
                db.collection("statuses").document(s["id"]).update({"viewers":firestore.ArrayUnion([user["uid"]])})
        return jsonify({"statuses":result})
    except: return jsonify({"statuses":[]})

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
            "time":int(time.time()),"ice_caller":[],"ice_callee":[]
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

@app.route("/api/call/ice", methods=["POST"])
def api_call_ice():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    data = request.get_json()
    call_id = data.get("call_id")
    try:
        doc = db.collection("calls").document(call_id).get()
        if not doc.exists: return jsonify({"ok":False})
        d = doc.to_dict()
        field = "ice_caller" if user["uid"]==d["from"] else "ice_callee"
        candidates = d.get(field,[])
        candidates.append(data["data"].get("candidate"))
        db.collection("calls").document(call_id).update({field:candidates})
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"ok":False,"msg":str(e)})

@app.route("/api/call/ice/<call_id>")
def api_call_get_ice(call_id):
    user = get_current_user(request)
    if not user: return jsonify({"candidates":[]})
    try:
        doc = db.collection("calls").document(call_id).get()
        if not doc.exists: return jsonify({"candidates":[]})
        d = doc.to_dict()
        field = "ice_callee" if user["uid"]==d["from"] else "ice_caller"
        return jsonify({"candidates":[c for c in d.get(field,[]) if c]})
    except: return jsonify({"candidates":[]})

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

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)