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
MAIN_HTML = """<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>WaClone</title>
<link href="https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800;900&display=swap" rel="stylesheet">
<style>
:root{
  --g:#00a884;--dk:#111b21;--pn:#202c33;--bo:#005c4b;--bi:#1e2c33;
  --bd:#2a3942;--tx:#e9edef;--st:#8696a0;--hv:#2a3942;--rd:#f15c6d;
  --bl:#53bdeb;--inp:#2a3942;--pur:#7c3aed;
}
*{margin:0;padding:0;box-sizing:border-box;}
html,body{height:100%;overflow:hidden;}
body{font-family:'Nunito',sans-serif;background:var(--dk);color:var(--tx);display:flex;height:100vh;}
::-webkit-scrollbar{width:5px;}::-webkit-scrollbar-thumb{background:var(--bd);border-radius:3px;}
input,textarea{outline:none;border:none;background:transparent;color:var(--tx);font-family:'Nunito',sans-serif;}
button{cursor:pointer;font-family:'Nunito',sans-serif;border:none;}

/* SIDEBAR */
.sb{width:370px;min-width:300px;max-width:370px;background:var(--pn);display:flex;flex-direction:column;
  border-right:1px solid var(--bd);height:100vh;overflow:hidden;flex-shrink:0;}
.sbh{padding:8px 12px;display:flex;align-items:center;gap:7px;height:58px;border-bottom:1px solid var(--bd);flex-shrink:0;}
.my-av{width:38px;height:38px;border-radius:50%;background:var(--g);display:flex;align-items:center;
  justify-content:center;font-weight:900;font-size:16px;color:#fff;cursor:pointer;flex-shrink:0;overflow:hidden;}
.my-av img{width:38px;height:38px;object-fit:cover;border-radius:50%;}
.sbh-title{font-size:18px;font-weight:900;flex:1;}
.icon-btn{width:36px;height:36px;border-radius:50%;background:transparent;color:var(--st);display:flex;
  align-items:center;justify-content:center;transition:.2s;flex-shrink:0;}
.icon-btn:hover{background:var(--hv);color:var(--tx);}
.nbadge{position:absolute;top:2px;right:2px;background:var(--rd);color:#fff;border-radius:50%;
  width:15px;height:15px;font-size:8px;font-weight:900;display:flex;align-items:center;justify-content:center;}
.icon-btn{position:relative;}

/* TABS */
.sbtabs{display:flex;border-bottom:1px solid var(--bd);flex-shrink:0;}
.stab{flex:1;padding:9px 4px;text-align:center;font-size:12px;font-weight:800;color:var(--st);
  cursor:pointer;border-bottom:2.5px solid transparent;transition:.2s;user-select:none;}
.stab.active{color:var(--g);border-bottom-color:var(--g);}
.tab-icon{font-size:13px;margin-right:3px;}

/* SEARCH */
.search-wrap{padding:6px 10px;flex-shrink:0;}
.search-inner{position:relative;display:flex;align-items:center;}
.search-svg{position:absolute;left:10px;color:var(--st);pointer-events:none;}
.search-inner input{width:100%;padding:7px 12px 7px 34px;border-radius:10px;background:var(--dk);
  font-size:13px;color:var(--tx);border:1.5px solid transparent;transition:.2s;}
.search-inner input:focus{border-color:var(--g);}

/* PANELS */
.sb-panel{flex:1;overflow-y:auto;display:none;flex-direction:column;}
.sb-panel.active{display:flex;}

/* CHAT LIST */
.chat-item{display:flex;align-items:center;gap:10px;padding:8px 12px;cursor:pointer;
  border-bottom:1px solid rgba(255,255,255,.03);transition:.15s;}
.chat-item:hover,.chat-item.active{background:var(--hv);}
.av48{width:46px;height:46px;border-radius:50%;background:var(--g);display:flex;align-items:center;
  justify-content:center;font-weight:900;font-size:18px;color:#fff;flex-shrink:0;position:relative;overflow:hidden;}
.av48 img{width:46px;height:46px;border-radius:50%;object-fit:cover;}
.online-ring{position:absolute;bottom:1px;right:1px;width:11px;height:11px;background:#44c56a;
  border-radius:50%;border:2px solid var(--pn);}
.chat-info{flex:1;min-width:0;}
.chat-name{font-weight:800;font-size:13.5px;}
.chat-prev{font-size:11.5px;color:var(--st);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:1px;}
.chat-meta{display:flex;flex-direction:column;align-items:flex-end;gap:3px;flex-shrink:0;}
.chat-time{font-size:10.5px;color:var(--st);}
.ubadge{background:var(--g);color:#fff;border-radius:50%;min-width:18px;height:18px;
  font-size:10px;font-weight:900;display:flex;align-items:center;justify-content:center;padding:0 3px;}

/* STATUS PANEL */
.stat-label{font-size:10.5px;font-weight:800;color:var(--st);text-transform:uppercase;
  letter-spacing:.5px;padding:9px 12px 4px;}
.my-stat-row{display:flex;align-items:center;gap:11px;padding:9px 12px;cursor:pointer;
  border-bottom:1px solid var(--bd);transition:.15s;}
.my-stat-row:hover{background:var(--hv);}
.stat-ring{width:50px;height:50px;border-radius:50%;border:3px solid var(--g);padding:2px;flex-shrink:0;}
.stat-ring.grey{border-color:var(--st);}
.stat-ring-in{width:100%;height:100%;border-radius:50%;background:var(--g);display:flex;align-items:center;
  justify-content:center;font-weight:900;font-size:17px;color:#fff;overflow:hidden;}
.stat-ring-in img{width:100%;height:100%;object-fit:cover;border-radius:50%;}
.stat-add{position:absolute;bottom:-1px;right:-1px;width:18px;height:18px;border-radius:50%;
  background:var(--g);color:#fff;font-size:13px;line-height:18px;text-align:center;
  border:2px solid var(--pn);font-weight:900;}
.stat-ring-wrap{position:relative;}
.stat-friend-item{display:flex;align-items:center;gap:11px;padding:8px 12px;cursor:pointer;
  border-bottom:1px solid rgba(255,255,255,.03);transition:.15s;}
.stat-friend-item:hover{background:var(--hv);}

/* MAIN */
.main{flex:1;display:flex;flex-direction:column;overflow:hidden;position:relative;height:100vh;}
.no-chat{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;
  color:var(--st);gap:8px;padding:20px;}
.no-chat-ic{font-size:64px;opacity:.2;}
.no-chat h2{font-size:20px;font-weight:900;color:var(--tx);}

/* CHAT HEADER */
.chat-hdr{height:58px;background:var(--pn);display:flex;align-items:center;gap:7px;
  padding:0 8px 0 10px;border-bottom:1px solid var(--bd);flex-shrink:0;}
.back-btn{width:32px;height:32px;border-radius:50%;background:transparent;color:var(--st);
  display:none;align-items:center;justify-content:center;font-size:20px;flex-shrink:0;font-weight:900;transition:.2s;}
.back-btn:hover{background:var(--hv);color:var(--tx);}
.hdr-av{width:38px;height:38px;border-radius:50%;overflow:hidden;flex-shrink:0;cursor:pointer;}
.hdr-info{flex:1;cursor:pointer;min-width:0;}
.hdr-info h3{font-weight:900;font-size:14.5px;}
.hdr-info p{font-size:10.5px;color:var(--g);}
.hdr-btn{width:38px;height:38px;border-radius:50%;background:transparent;color:var(--st);
  display:flex;align-items:center;justify-content:center;transition:.2s;flex-shrink:0;}
.hdr-btn:hover{background:var(--hv);color:var(--tx);}

/* MESSAGES */
.msgs-area{flex:1;overflow-y:auto;padding:6px 14px 4px;display:flex;flex-direction:column;gap:1px;
  background-color:var(--dk);}
.msg-row{display:flex;margin:1px 0;align-items:flex-end;gap:4px;position:relative;}
.msg-row:hover .msg-acts{opacity:1;}
.msg-row.out{justify-content:flex-end;}
.msg-row.in{justify-content:flex-start;}
.msg-acts{opacity:0;transition:opacity .15s;display:flex;gap:3px;align-items:center;}
.msg-row.out .msg-acts{order:-1;}
.act-b{width:24px;height:24px;border-radius:50%;background:rgba(32,44,51,.92);border:1px solid var(--bd);
  color:var(--st);font-size:10px;display:flex;align-items:center;justify-content:center;transition:.15s;}
.act-b:hover{background:var(--hv);color:var(--tx);}
.bubble{max-width:65%;padding:6px 10px 4px;border-radius:11px;font-size:13.5px;line-height:1.5;
  word-break:break-word;box-shadow:0 1px 2px rgba(0,0,0,.3);}
.msg-row.out .bubble{background:var(--bo);border-bottom-right-radius:3px;}
.msg-row.in .bubble{background:var(--bi);border-bottom-left-radius:3px;}
.btime{font-size:10px;color:rgba(255,255,255,.4);text-align:right;margin-top:2px;
  display:flex;align-items:center;justify-content:flex-end;gap:2px;}
.tick{font-size:11px;}.tick.read{color:var(--bl);}
.bubble img{max-width:230px;max-height:230px;border-radius:7px;display:block;margin-bottom:3px;cursor:pointer;object-fit:cover;}
.bubble audio{width:200px;margin-bottom:3px;}
.bubble video{max-width:230px;border-radius:7px;display:block;margin-bottom:3px;}
.bubble a.flink{color:var(--bl);text-decoration:none;font-size:12.5px;display:flex;align-items:center;gap:5px;padding:3px 0;}
.date-div{text-align:center;color:var(--st);font-size:10.5px;margin:6px 0;}
.date-div span{background:rgba(17,27,33,.85);padding:2px 10px;border-radius:18px;border:1px solid var(--bd);}
.rq{background:rgba(255,255,255,.07);border-left:3px solid var(--g);border-radius:5px;
  padding:4px 7px;margin-bottom:4px;font-size:10.5px;cursor:pointer;}
.rq-n{font-weight:800;color:var(--g);font-size:9.5px;margin-bottom:1px;}
.rq-t{color:var(--st);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:200px;}

/* TYPING */
.typing-wrap{padding:2px 14px;min-height:22px;display:flex;align-items:center;flex-shrink:0;}
.tdots{display:none;align-items:center;gap:5px;}
.tdots.show{display:flex;}
.dotanim{display:flex;gap:3px;}
.dotanim span{width:5px;height:5px;background:var(--st);border-radius:50%;animation:db 1.4s infinite;}
.dotanim span:nth-child(2){animation-delay:.2s;}
.dotanim span:nth-child(3){animation-delay:.4s;}
@keyframes db{0%,60%,100%{transform:translateY(0);}30%{transform:translateY(-4px);}}
.ttext{font-size:10.5px;color:var(--st);}

/* INPUT AREA */
.inp-area{background:var(--pn);padding:5px 8px 7px;border-top:1px solid var(--bd);flex-shrink:0;display:flex;flex-direction:column;gap:4px;}
.rply-prev{display:none;background:rgba(0,168,132,.1);border-left:3px solid var(--g);border-radius:7px;
  padding:5px 8px;align-items:center;justify-content:space-between;gap:7px;}
.rply-prev.show{display:flex;}
.rp-n{color:var(--g);font-weight:800;font-size:10px;}
.rp-t{color:var(--st);font-size:11px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
.rp-x{width:20px;height:20px;border-radius:50%;background:var(--bd);color:var(--st);font-size:11px;
  display:flex;align-items:center;justify-content:center;}
.rp-x:hover{background:var(--hv);}
.inp-row{display:flex;align-items:flex-end;gap:4px;}
.side-b{width:36px;height:36px;border-radius:50%;background:transparent;color:var(--st);
  display:flex;align-items:center;justify-content:center;font-size:19px;flex-shrink:0;transition:.2s;}
.side-b:hover{background:var(--hv);color:var(--tx);}
.msg-ta{flex:1;background:var(--inp);border:1.5px solid transparent;border-radius:20px;padding:8px 13px;
  font-size:14px;color:var(--tx);resize:none;max-height:110px;min-height:40px;line-height:1.4;transition:.2s;display:block;}
.msg-ta:focus{border-color:var(--g);}
.msg-ta::placeholder{color:var(--st);}
.send-b{width:40px;height:40px;border-radius:50%;background:var(--g);color:#fff;display:flex;
  align-items:center;justify-content:center;flex-shrink:0;transition:.2s;}
.send-b:hover{background:#009070;}
.rec-b{width:40px;height:40px;border-radius:50%;background:var(--dk);border:1.5px solid var(--bd);
  color:var(--st);display:flex;align-items:center;justify-content:center;flex-shrink:0;transition:.2s;}
.rec-b.recording{background:var(--rd);border-color:var(--rd);color:#fff;animation:rp 1s infinite;}
@keyframes rp{0%,100%{transform:scale(1);}50%{transform:scale(1.1);}}
.upbar{height:3px;background:var(--bd);border-radius:3px;overflow:hidden;display:none;}
.upbar.show{display:block;}
.upfill{height:100%;background:var(--g);width:0%;transition:width .3s;border-radius:3px;}

/* EMOJI & ATT MENUS */
.emoji-pick{position:absolute;bottom:65px;right:48px;background:var(--pn);border:1px solid var(--bd);
  border-radius:14px;padding:9px;box-shadow:0 8px 28px rgba(0,0,0,.6);z-index:200;display:none;width:270px;}
.emoji-pick.open{display:block;}
.emoji-grid{display:flex;flex-wrap:wrap;gap:2px;max-height:160px;overflow-y:auto;}
.emj{font-size:20px;cursor:pointer;padding:3px;border-radius:6px;transition:.1s;line-height:1;}
.emj:hover{background:var(--hv);}
.att-menu{position:absolute;bottom:65px;left:8px;background:var(--pn);border:1px solid var(--bd);
  border-radius:14px;padding:10px;box-shadow:0 8px 28px rgba(0,0,0,.6);z-index:200;display:none;flex-wrap:wrap;gap:7px;width:210px;}
.att-menu.open{display:flex;}
.att-opt{display:flex;flex-direction:column;align-items:center;gap:4px;cursor:pointer;
  width:calc(33% - 5px);padding:4px 0;border-radius:9px;transition:.15s;}
.att-opt:hover{background:var(--hv);}
.att-ic{width:42px;height:42px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:18px;}
.att-lbl{font-size:9.5px;font-weight:700;color:var(--st);}

/* CTX MENU */
.ctx{position:fixed;background:var(--pn);border:1px solid var(--bd);border-radius:13px;
  box-shadow:0 8px 28px rgba(0,0,0,.6);z-index:600;min-width:170px;overflow:hidden;display:none;}
.ctx-it{padding:9px 14px;font-size:13.5px;font-weight:700;cursor:pointer;display:flex;
  align-items:center;gap:9px;transition:.15s;color:var(--tx);}
.ctx-it:hover{background:var(--hv);}
.ctx-it.danger{color:var(--rd);}

/* OVERLAYS */
.ov{position:fixed;inset:0;background:rgba(0,0,0,.72);z-index:400;display:none;
  align-items:center;justify-content:center;padding:12px;}
.ov.open{display:flex;}
.panel{background:var(--pn);border-radius:18px;width:400px;max-width:100%;max-height:90vh;
  overflow-y:auto;border:1px solid var(--bd);box-shadow:0 20px 60px rgba(0,0,0,.6);}
.ph{padding:14px 18px;display:flex;align-items:center;justify-content:space-between;
  border-bottom:1px solid var(--bd);position:sticky;top:0;background:var(--pn);z-index:1;}
.ph h2{font-size:16px;font-weight:900;}
.xbtn{background:var(--hv);border:none;color:var(--st);width:28px;height:28px;border-radius:50%;
  font-size:14px;display:flex;align-items:center;justify-content:center;cursor:pointer;}
.xbtn:hover{color:var(--tx);}
.pb{padding:16px 18px;}
.pavwrap{text-align:center;margin-bottom:12px;position:relative;display:inline-block;left:50%;transform:translateX(-50%);}
.pavbig{width:90px;height:90px;border-radius:50%;background:var(--g);display:flex;align-items:center;
  justify-content:center;font-size:36px;font-weight:900;color:#fff;overflow:hidden;cursor:pointer;
  border:3px solid var(--bd);transition:.2s;}
.pavbig img{width:100%;height:100%;object-fit:cover;}
.pavedit{position:absolute;bottom:1px;right:0;background:var(--g);width:26px;height:26px;
  border-radius:50%;display:flex;align-items:center;justify-content:center;cursor:pointer;
  box-shadow:0 2px 6px rgba(0,0,0,.4);font-size:11px;}
.fg{margin-bottom:10px;}
.fg label{display:block;font-size:9.5px;font-weight:800;color:var(--g);text-transform:uppercase;
  letter-spacing:.5px;margin-bottom:4px;}
.fg input,.fg textarea{width:100%;padding:8px 11px;border-radius:9px;background:var(--dk);
  border:1.5px solid var(--bd);color:var(--tx);font-size:12.5px;font-family:'Nunito',sans-serif;transition:.2s;}
.fg input:focus,.fg textarea:focus{border-color:var(--g);outline:none;}
.fg textarea{resize:none;height:62px;line-height:1.5;}
.sbtn{width:100%;padding:10px;background:var(--g);color:#fff;border:none;border-radius:11px;
  font-size:13.5px;font-weight:800;margin-top:4px;transition:.2s;cursor:pointer;}
.sbtn:hover{background:#009070;}
.lbtn{width:100%;padding:9px;background:transparent;color:var(--rd);border:1.5px solid var(--rd);
  border-radius:11px;font-size:13.5px;font-weight:800;margin-top:6px;transition:.2s;cursor:pointer;}
.lbtn:hover{background:var(--rd);color:#fff;}

/* STATUS VIEWER */
.stv{background:#000;width:100%;max-width:440px;border-radius:18px;overflow:hidden;}
.stv-prog{display:flex;gap:3px;padding:9px 11px 5px;}
.stv-seg{flex:1;height:3px;background:rgba(255,255,255,.25);border-radius:3px;overflow:hidden;}
.stv-fill{height:100%;background:#fff;width:0%;}
.stv-hd{display:flex;align-items:center;gap:9px;padding:5px 12px 8px;}
.stv-body{min-height:180px;display:flex;align-items:center;justify-content:center;padding:12px;}
.stv-text-content{font-size:21px;font-weight:800;text-align:center;color:#fff;padding:20px 12px;
  width:100%;border-radius:10px;min-height:160px;display:flex;align-items:center;justify-content:center;}
.stv-img{max-width:100%;max-height:360px;object-fit:contain;border-radius:4px;}
.stv-nav{display:flex;justify-content:space-between;padding:7px 12px 12px;gap:8px;}
.stv-nb{flex:1;padding:7px 14px;background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.2);
  border-radius:18px;color:#fff;font-size:12.5px;font-weight:700;cursor:pointer;transition:.2s;text-align:center;}
.stv-nb:hover{background:rgba(255,255,255,.2);}
.stv-nb:disabled{opacity:.3;cursor:default;}

/* SETTINGS */
.sset{border-bottom:1px solid var(--bd);padding-bottom:4px;margin-bottom:4px;}
.sset-title{font-size:10px;font-weight:800;color:var(--g);text-transform:uppercase;
  letter-spacing:.5px;padding:10px 16px 5px;}
.sset-item{display:flex;align-items:center;gap:11px;padding:10px 16px;cursor:pointer;transition:.15s;}
.sset-item:hover{background:var(--hv);}
.sset-ic{width:38px;height:38px;border-radius:50%;display:flex;align-items:center;justify-content:center;
  font-size:17px;flex-shrink:0;}
.sset-txt{flex:1;}
.sset-lbl{font-weight:800;font-size:13px;}
.sset-sub{font-size:11px;color:var(--st);margin-top:1px;}
.sset-chev{font-size:18px;color:var(--st);font-weight:900;}
.stoggle{width:44px;height:24px;border-radius:12px;background:var(--bd);position:relative;
  cursor:pointer;transition:.3s;flex-shrink:0;}
.stoggle.on{background:var(--g);}
.stoggle-k{position:absolute;top:2px;left:2px;width:20px;height:20px;border-radius:50%;
  background:#fff;transition:.3s;box-shadow:0 1px 4px rgba(0,0,0,.3);}
.stoggle.on .stoggle-k{left:22px;}

/* CAMERA */
.cam-wrap{background:#000;border-radius:10px;overflow:hidden;}
.cam-wrap video{width:100%;display:block;max-height:260px;object-fit:cover;}
.cam-ctrls{display:flex;gap:9px;justify-content:center;margin-top:9px;}
.cam-b{width:48px;height:48px;border-radius:50%;border:none;display:flex;align-items:center;
  justify-content:center;font-size:19px;cursor:pointer;transition:.2s;}

/* FORWARD */
.fw-list{display:flex;flex-direction:column;gap:5px;max-height:250px;overflow-y:auto;}
.fw-item{display:flex;align-items:center;gap:9px;padding:8px;background:var(--dk);border-radius:9px;
  cursor:pointer;border:1.5px solid var(--bd);transition:.15s;}
.fw-item:hover,.fw-item.sel{border-color:var(--g);}

/* NOTIF */
.notif-item{display:flex;gap:9px;align-items:center;padding:8px 0;border-bottom:1px solid var(--bd);cursor:pointer;}
.notif-item:last-child{border-bottom:none;}
.notif-dot{width:7px;height:7px;background:var(--g);border-radius:50%;flex-shrink:0;}

/* CALL UI */
.call-ui{position:fixed;inset:0;background:#080c10;z-index:900;display:none;flex-direction:column;
  align-items:center;justify-content:space-between;padding:14px;}
.call-ui.active{display:flex;}
.call-vid-grid{width:100%;max-width:980px;flex:1;display:flex;align-items:center;
  justify-content:center;gap:8px;padding:6px 0;}
.rem-vid{position:relative;flex:1;max-height:70vh;border-radius:16px;overflow:hidden;
  background:#0f1923;border:1px solid var(--bd);}
.rem-vid video{width:100%;height:100%;object-fit:cover;display:block;min-height:180px;}
.loc-vid{position:relative;width:155px;min-width:120px;height:210px;border-radius:14px;
  overflow:hidden;background:#111;border:2px solid var(--g);flex-shrink:0;}
.loc-vid video{width:100%;height:100%;object-fit:cover;display:block;}
.cam-off{position:absolute;inset:0;background:#0f1923;display:none;align-items:center;
  justify-content:center;flex-direction:column;gap:5px;}
.cam-off.show{display:flex;}
.audio-info{text-align:center;padding:28px 18px;flex:1;display:flex;flex-direction:column;
  align-items:center;justify-content:center;}
.call-av{width:110px;height:110px;border-radius:50%;background:var(--g);display:flex;align-items:center;
  justify-content:center;font-size:46px;font-weight:900;color:#fff;margin:0 auto 14px;overflow:hidden;
  border:4px solid rgba(0,168,132,.3);animation:cring 2.5s infinite;}
@keyframes cring{0%,100%{box-shadow:0 0 0 0 rgba(0,168,132,.4);}60%{box-shadow:0 0 0 20px rgba(0,168,132,0);}}
.call-av img{width:100%;height:100%;object-fit:cover;}
.call-name{font-size:26px;font-weight:900;color:#fff;}
.call-stat{font-size:14px;color:rgba(255,255,255,.5);margin-top:5px;}
.call-timer{font-size:19px;color:var(--g);font-weight:800;margin-top:9px;display:none;letter-spacing:1.5px;}
.call-ctrls{display:flex;gap:14px;align-items:center;justify-content:center;padding:10px 0 4px;flex-shrink:0;}
.ccbtn{width:60px;height:60px;border-radius:50%;border:none;display:flex;align-items:center;
  justify-content:center;font-size:24px;cursor:pointer;transition:.2s;flex-direction:column;}
.ccbtn:hover{transform:scale(1.08);}
.cc-end{background:#e53e3e;}
.cc-tog{background:#1e2a3a;}.cc-tog:hover{background:#2a3a52;}
.cc-on{background:var(--g)!important;}
.cc-off{background:#e53e3e!important;}
.cc-lbl{font-size:9px;font-weight:700;color:rgba(255,255,255,.5);margin-top:3px;}
.inc-call{position:fixed;bottom:20px;right:20px;background:var(--pn);border:1px solid var(--bd);
  border-radius:18px;padding:16px;z-index:950;box-shadow:0 20px 60px rgba(0,0,0,.8);
  min-width:260px;display:none;}
.inc-call.show{display:block;animation:sir .3s ease;}
@keyframes sir{from{transform:translateX(60px);opacity:0;}to{transform:none;opacity:1;}}
.inc-av{width:52px;height:52px;border-radius:50%;background:var(--g);display:flex;align-items:center;
  justify-content:center;font-size:21px;font-weight:900;color:#fff;margin:0 auto 7px;overflow:hidden;}
.inc-av img{width:100%;height:100%;object-fit:cover;}
.inc-acts{display:flex;gap:7px;margin-top:10px;}
.inc-b{flex:1;padding:9px;border:none;border-radius:9px;font-size:12.5px;font-weight:800;cursor:pointer;}
.inc-audio{background:var(--g);color:#fff;}
.inc-video{background:#1a56db;color:#fff;}
.inc-rej{background:var(--rd);color:#fff;flex:none;padding:9px 12px;}

/* AI DRAWER */
.ai-drw{position:fixed;top:0;right:0;height:100vh;width:370px;background:#13111c;
  border-left:1px solid rgba(124,58,237,.3);z-index:500;display:flex;flex-direction:column;
  transform:translateX(100%);transition:transform .3s cubic-bezier(.4,0,.2,1);
  box-shadow:-18px 0 50px rgba(0,0,0,.5);}
.ai-drw.open{transform:translateX(0);}
.ai-hdr{padding:13px 14px;background:linear-gradient(135deg,#2d1059,#1a0a38);
  display:flex;align-items:center;gap:9px;border-bottom:1px solid rgba(124,58,237,.3);flex-shrink:0;}
.ai-av-ic{width:36px;height:36px;border-radius:50%;background:linear-gradient(135deg,#7c3aed,#9b5de5);
  display:flex;align-items:center;justify-content:center;font-size:17px;flex-shrink:0;}
.ai-title{font-weight:900;font-size:15px;color:#e0d4ff;}
.ai-dot{width:8px;height:8px;border-radius:50%;background:#a8ff78;animation:aip 1.5s infinite;margin-left:3px;}
@keyframes aip{0%,100%{opacity:1;transform:scale(1);}50%{opacity:.5;transform:scale(.8);}}
.ai-xbtn{margin-left:auto;width:28px;height:28px;border-radius:50%;background:rgba(255,255,255,.08);
  color:rgba(224,212,255,.6);font-size:15px;display:flex;align-items:center;justify-content:center;cursor:pointer;transition:.2s;}
.ai-xbtn:hover{background:rgba(255,255,255,.15);color:#e0d4ff;}
.ai-msgs{flex:1;overflow-y:auto;padding:12px 12px 6px;display:flex;flex-direction:column;gap:9px;}
.ai-msg{display:flex;gap:7px;align-items:flex-start;}
.ai-msg.usr{flex-direction:row-reverse;}
.ai-mav{width:28px;height:28px;border-radius:50%;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:13px;}
.ai-msg.bot .ai-mav{background:linear-gradient(135deg,#7c3aed,#9b5de5);}
.ai-msg.usr .ai-mav{background:var(--g);}
.ai-bub{max-width:85%;padding:8px 11px;border-radius:13px;font-size:13px;line-height:1.55;word-break:break-word;}
.ai-msg.bot .ai-bub{background:rgba(124,58,237,.14);border:1px solid rgba(124,58,237,.24);color:#d4c8f8;}
.ai-msg.usr .ai-bub{background:var(--bo);color:var(--tx);border-bottom-right-radius:3px;}
.ai-think{display:flex;gap:4px;padding:9px 13px;background:rgba(124,58,237,.1);
  border:1px solid rgba(124,58,237,.2);border-radius:13px;}
.ai-think span{width:6px;height:6px;background:#9b5de5;border-radius:50%;animation:db 1.4s infinite;}
.ai-think span:nth-child(2){animation-delay:.2s;}
.ai-think span:nth-child(3){animation-delay:.4s;}
.ai-chips{display:flex;flex-wrap:wrap;gap:5px;padding:3px 12px 7px;}
.ai-chip{padding:4px 10px;background:rgba(124,58,237,.1);border:1px solid rgba(124,58,237,.22);
  border-radius:18px;font-size:11px;color:#c4b3f0;cursor:pointer;transition:.2s;}
.ai-chip:hover{background:rgba(124,58,237,.22);color:#e0d4ff;}
.ai-inp-row{padding:9px 12px 12px;border-top:1px solid rgba(124,58,237,.2);
  display:flex;gap:7px;align-items:flex-end;flex-shrink:0;}
.ai-ta{flex:1;background:rgba(124,58,237,.08);border:1.5px solid rgba(124,58,237,.28);border-radius:16px;
  padding:8px 12px;font-size:13px;color:#e0d4ff;resize:none;min-height:38px;max-height:96px;
  line-height:1.4;font-family:'Nunito',sans-serif;transition:.2s;}
.ai-ta:focus{border-color:#9b5de5;outline:none;}
.ai-ta::placeholder{color:rgba(224,212,255,.3);}
.ai-send{width:38px;height:38px;border-radius:50%;background:linear-gradient(135deg,#7c3aed,#9b5de5);
  color:#fff;border:none;display:flex;align-items:center;justify-content:center;flex-shrink:0;
  cursor:pointer;transition:.2s;}
.ai-send:hover{transform:scale(1.07);box-shadow:0 4px 14px rgba(124,58,237,.5);}
.copy2chat{display:inline-flex;align-items:center;gap:4px;margin-top:5px;padding:4px 10px;
  background:rgba(0,168,132,.1);border:1px solid rgba(0,168,132,.28);border-radius:12px;
  color:var(--g);font-size:10.5px;font-weight:700;cursor:pointer;font-family:'Nunito',sans-serif;transition:.2s;}
.copy2chat:hover{background:rgba(0,168,132,.2);}

/* TOAST */
.toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:var(--pn);
  color:var(--tx);padding:8px 18px;border-radius:11px;border-left:4px solid var(--g);z-index:9999;
  box-shadow:0 6px 28px rgba(0,0,0,.5);opacity:0;transition:opacity .3s;pointer-events:none;
  font-weight:700;white-space:nowrap;}
.toast.show{opacity:1;}
.toast.err{border-left-color:var(--rd);}

/* MOBILE */
@media(max-width:680px){
  .sb{position:fixed;left:0;top:0;z-index:100;width:100%!important;max-width:100%!important;}
  .sb.gone{transform:translateX(-100%);}
  .main{width:100%;}
  .back-btn{display:flex!important;}
  .msgs-area{padding:5px 7px 4px;}
  .bubble{max-width:80%;}
  .ai-drw{width:100%;}
}
</style>
</head>
<body>

<!-- ====== SIDEBAR ====== -->
<div class="sb" id="sb">
  <div class="sbh">
    <div class="my-av" onclick="openOv('prof-ov')" id="myav">__SIDEBAR_AV__</div>
    <span class="sbh-title">WaClone</span>
    <button class="icon-btn" onclick="openAI()" title="AI" style="background:linear-gradient(135deg,#7c3aed,#9b5de5);color:#fff;">
      <svg width="17" height="17" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2a2 2 0 012 2 2 2 0 01-1 1.73V7h1a7 7 0 017 7h1a1 1 0 010 2h-1v1a2 2 0 01-2 2H5a2 2 0 01-2-2v-1H2a1 1 0 010-2h1a7 7 0 017-7h1V5.73A2 2 0 0110 4a2 2 0 012-2zm-5 9a5 5 0 000 10h10a5 5 0 000-10H7zm2 3a1 1 0 110 2 1 1 0 010-2zm6 0a1 1 0 110 2 1 1 0 010-2z"/></svg>
    </button>
    <button class="icon-btn" onclick="openNotif()" title="Notifikasi">
      <svg width="19" height="19" viewBox="0 0 24 24" fill="currentColor"><path d="M12 22c1.1 0 2-.9 2-2h-4c0 1.1.9 2 2 2zm6-6v-5c0-3.07-1.63-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 1.5v.68C7.64 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z"/></svg>
      <span class="nbadge" id="nbadge" style="display:none">0</span>
    </button>
    <button class="icon-btn" onclick="openOv('settings-ov')" title="Pengaturan">
      <svg width="19" height="19" viewBox="0 0 24 24" fill="currentColor"><path d="M19.14 12.94c.04-.3.06-.61.06-.94 0-.32-.02-.64-.07-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.05.3-.07.63-.07.94s.02.64.07.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z"/></svg>
    </button>
  </div>

  <div class="sbtabs">
    <div class="stab active" onclick="switchTab('chats')" id="tab-chats">
      <span class="tab-icon">&#x1F4AC;</span>Chat
    </div>
    <div class="stab" onclick="switchTab('status')" id="tab-status">
      <span class="tab-icon">&#x1F7E2;</span>Status
    </div>
    <div class="stab" onclick="switchTab('contacts')" id="tab-contacts">
      <span class="tab-icon">&#x1F465;</span>Kontak
    </div>
  </div>

  <div class="search-wrap" id="srch-wrap">
    <div class="search-inner">
      <svg class="search-svg" width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M15.5 14h-.79l-.28-.27A6.47 6.47 0 0016 9.5 6.5 6.5 0 109.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/></svg>
      <input type="text" id="srch-inp" placeholder="Cari..." oninput="filterList(this.value)">
    </div>
  </div>

  <!-- CHAT TAB -->
  <div class="sb-panel active" id="panel-chats">
    <div id="chat-list"><div style="padding:26px;text-align:center;color:var(--st);font-size:13px;">Memuat...</div></div>
  </div>

  <!-- STATUS TAB -->
  <div class="sb-panel" id="panel-status">
    <div class="stat-label">Status Saya</div>
    <div class="my-stat-row" onclick="openMyStatus()">
      <div class="stat-ring-wrap">
        <div class="stat-ring" id="my-stat-ring">
          <div class="stat-ring-in" id="my-stat-av">__SIDEBAR_AV__</div>
        </div>
        <div class="stat-add">+</div>
      </div>
      <div style="flex:1;">
        <div style="font-weight:800;font-size:13.5px;">Lihat / Tambah Status Saya</div>
        <div style="font-size:11.5px;color:var(--st);margin-top:2px;" id="my-stat-hint">Ketuk untuk lihat atau buat status</div>
      </div>
    </div>
    <div class="stat-label" id="friend-stat-lbl" style="display:none;">Status Teman</div>
    <div id="friend-stat-list"></div>
    <div id="stat-empty" style="display:none;padding:28px;text-align:center;color:var(--st);font-size:12.5px;">
      Belum ada status teman
    </div>
  </div>

  <!-- CONTACTS TAB -->
  <div class="sb-panel" id="panel-contacts">
    <div id="contacts-list"><div style="padding:26px;text-align:center;color:var(--st);font-size:13px;">Memuat...</div></div>
  </div>
</div>

<!-- ====== MAIN PANEL ====== -->
<div class="main" id="main">
  <div class="no-chat" id="no-chat" style="display:flex;">
    <div class="no-chat-ic">&#x1F4AC;</div>
    <h2>WaClone</h2>
    <p>Pilih kontak untuk mulai chat</p>
    <div style="display:flex;gap:8px;margin-top:14px;flex-wrap:wrap;justify-content:center;">
      <button onclick="openAI()" style="padding:9px 18px;background:linear-gradient(135deg,#7c3aed,#9b5de5);color:#fff;border:none;border-radius:18px;font-size:13px;font-weight:800;cursor:pointer;font-family:inherit;">Buka AI</button>
      <button onclick="switchTab('status')" style="padding:9px 18px;background:var(--pn);color:var(--tx);border:1.5px solid var(--bd);border-radius:18px;font-size:13px;font-weight:800;cursor:pointer;font-family:inherit;">Lihat Status</button>
    </div>
  </div>

  <div id="chat-wrap" style="display:none;flex-direction:column;height:100%;overflow:hidden;">
    <div class="chat-hdr">
      <button class="back-btn" id="back-btn" onclick="goBack()">&#8592;</button>
      <div class="hdr-av" id="hdr-av"></div>
      <div class="hdr-info">
        <h3 id="hdr-name">&#8212;</h3>
        <p id="hdr-stat">&#8212;</p>
      </div>
      <button class="hdr-btn" onclick="openAI()" title="AI" style="color:#9b5de5;">
        <svg width="19" height="19" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2a2 2 0 012 2 2 2 0 01-1 1.73V7h1a7 7 0 017 7h1a1 1 0 010 2h-1v1a2 2 0 01-2 2H5a2 2 0 01-2-2v-1H2a1 1 0 010-2h1a7 7 0 017-7h1V5.73A2 2 0 0110 4a2 2 0 012-2zm-5 9a5 5 0 000 10h10a5 5 0 000-10H7zm2 3a1 1 0 110 2 1 1 0 010-2zm6 0a1 1 0 110 2 1 1 0 010-2z"/></svg>
      </button>
      <button class="hdr-btn" onclick="startCall('audio')" title="Telepon">
        <svg width="19" height="19" viewBox="0 0 24 24" fill="currentColor"><path d="M6.6 10.8c1.4 2.8 3.8 5.1 6.6 6.6l2.2-2.2c.3-.3.7-.4 1-.2 1.1.4 2.3.6 3.6.6.6 0 1 .4 1 1V20c0 .6-.4 1-1 1-9.4 0-17-7.6-17-17 0-.6.4-1 1-1h3.5c.6 0 1 .4 1 1 0 1.3.2 2.5.6 3.6.1.3 0 .7-.2 1L6.6 10.8z"/></svg>
      </button>
      <button class="hdr-btn" onclick="startCall('video')" title="Video Call">
        <svg width="19" height="19" viewBox="0 0 24 24" fill="currentColor"><path d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z"/></svg>
      </button>
    </div>

    <div class="msgs-area" id="msgs-area"></div>

    <div class="typing-wrap">
      <div class="tdots" id="tdots">
        <div class="dotanim"><span></span><span></span><span></span></div>
        <span class="ttext" id="ttext"></span>
      </div>
    </div>

    <div class="att-menu" id="att-menu">
      <div class="att-opt" onclick="trigFile('photo')"><div class="att-ic" style="background:#1a56db22;">&#x1F4F7;</div><span class="att-lbl">Foto/Video</span></div>
      <div class="att-opt" onclick="trigFile('doc')"><div class="att-ic" style="background:#7c3aed22;">&#x1F4C4;</div><span class="att-lbl">Dokumen</span></div>
      <div class="att-opt" onclick="openCamChat()"><div class="att-ic" style="background:#05966922;">&#x1F4F8;</div><span class="att-lbl">Kamera</span></div>
    </div>
    <input type="file" id="fp" style="display:none" accept="image/*,video/*" onchange="doUpload(this)">
    <input type="file" id="fd" style="display:none" accept=".pdf,.txt,.doc,.docx,.xls,.xlsx,.zip,.rar" onchange="doUpload(this)">

    <div class="emoji-pick" id="emoji-pick">
      <div class="emoji-grid" id="emoji-grid"></div>
    </div>

    <div class="upbar" id="upbar"><div class="upfill" id="upfill"></div></div>

    <div class="inp-area">
      <div class="rply-prev" id="rply-prev">
        <div style="flex:1;min-width:0;">
          <div class="rp-n" id="rp-n"></div>
          <div class="rp-t" id="rp-t"></div>
        </div>
        <button class="rp-x" onclick="cancelReply()">&#10005;</button>
      </div>
      <div class="inp-row">
        <button class="side-b" onclick="toggleAtt()" title="Lampiran">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M16.5 6v11.5c0 2.21-1.79 4-4 4s-4-1.79-4-4V5c0-1.38 1.12-2.5 2.5-2.5s2.5 1.12 2.5 2.5v10.5c0 .55-.45 1-1 1s-1-.45-1-1V6H10v9.5c0 1.38 1.12 2.5 2.5 2.5s2.5-1.12 2.5-2.5V5c0-2.21-1.79-4-4-4S7 2.79 7 5v12.5c0 3.04 2.46 5.5 5.5 5.5s5.5-2.46 5.5-5.5V6h-1.5z"/></svg>
        </button>
        <button class="side-b" onclick="toggleEmoji()" title="Emoji">&#x1F60A;</button>
        <textarea id="msg-inp" class="msg-ta" rows="1" placeholder="Ketik pesan..."
          onkeydown="handleKey(event)" oninput="onInp(this)"></textarea>
        <button class="rec-b" id="rec-b"
          onmousedown="startVoice()" onmouseup="stopVoice()"
          ontouchstart="startVoice(event)" ontouchend="stopVoice(event)" title="Tahan rekam">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor"><path d="M12 14c1.66 0 2.99-1.34 2.99-3L15 5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.3-3c0 3-2.54 5.1-5.3 5.1S6.7 14 6.7 11H5c0 3.41 2.72 6.23 6 6.72V21h2v-3.28c3.28-.48 6-3.3 6-6.72h-1.7z"/></svg>
        </button>
        <button class="send-b" onclick="sendMsg()">
          <svg width="19" height="19" viewBox="0 0 24 24" fill="white"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
        </button>
      </div>
    </div>
  </div>
</div>

<!-- CTX MENU -->
<div class="ctx" id="ctx">
  <div class="ctx-it" onclick="doReply()">&#8617; Balas</div>
  <div class="ctx-it" onclick="doCopy()">&#x1F4CB; Salin</div>
  <div class="ctx-it" onclick="doFwd()">&#8618; Teruskan</div>
  <div class="ctx-it" onclick="doAskAI()">&#x1F916; Tanya AI</div>
  <div class="ctx-it danger" onclick="doDel()">&#x1F5D1; Hapus</div>
</div>

<!-- AI DRAWER -->
<div class="ai-drw" id="ai-drw">
  <div class="ai-hdr">
    <div class="ai-av-ic">&#x1F916;</div>
    <div style="flex:1;">
      <div class="ai-title">WaClone AI</div>
      <div style="font-size:10.5px;color:rgba(224,212,255,.45);" id="ai-sub-txt">Siap membantu kamu</div>
    </div>
    <div class="ai-dot"></div>
    <button class="ai-xbtn" onclick="closeAI()">&#10005;</button>
  </div>
  <div class="ai-msgs" id="ai-msgs">
    <div class="ai-msg bot">
      <div class="ai-mav">&#x1F916;</div>
      <div class="ai-bub">
        Halo! Saya <b>WaClone AI</b> &#x1F44B;<br><br>
        Saya bisa membantu:<br>
        &#x2022; Menulis atau menyempurnakan pesan<br>
        &#x2022; Menjawab pertanyaan apapun<br>
        &#x2022; Menerjemahkan teks<br>
        &#x2022; Memberi saran &amp; ide kreatif<br><br>
        Ketik pertanyaan kamu di bawah!
      </div>
    </div>
  </div>
  <div class="ai-chips" id="ai-chips">
    <div class="ai-chip" onclick="sendAI('Bantu saya menulis pesan yang baik')">&#9999; Tulis pesan</div>
    <div class="ai-chip" onclick="sendAI('Buat lelucon lucu untuk teman')">&#x1F602; Lelucon</div>
    <div class="ai-chip" onclick="sendAI('Tips berkomunikasi yang baik')">&#x1F4A1; Tips</div>
    <div class="ai-chip" onclick="sendAI('Translate to English: Halo apa kabar')">&#x1F310; Terjemah</div>
  </div>
  <div class="ai-inp-row">
    <textarea class="ai-ta" id="ai-ta" rows="1" placeholder="Tanya AI apapun..."
      onkeydown="aiKey(event)" oninput="aiResize(this)"></textarea>
    <button class="ai-send" onclick="aiSendFromInput()">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="white"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
    </button>
  </div>
</div>

<!-- ====== OVERLAYS ====== -->
<div class="ov" id="prof-ov">
  <div class="panel">
    <div class="ph"><h2>&#x1F464; Profil Saya</h2><button class="xbtn" onclick="closeOv('prof-ov')">&#10005;</button></div>
    <div class="pb">
      <div class="pavwrap">
        <div class="pavbig" id="pavbig" onclick="document.getElementById('av-inp').click()">__PROFILE_AV__</div>
        <div class="pavedit" onclick="document.getElementById('av-inp').click()">&#x1F4F7;</div>
        <input type="file" id="av-inp" style="display:none" accept="image/*" onchange="uploadAv(this)">
      </div>
      <div style="font-size:18px;font-weight:900;text-align:center;" id="pname">__USERNAME__</div>
      <div style="color:var(--st);font-size:11.5px;text-align:center;margin-top:2px;">__EMAIL__</div>
      <div style="margin-top:14px;">
        <div class="fg"><label>Username</label><input id="edit-uname" value="__USERNAME__" placeholder="username baru"></div>
        <div class="fg"><label>Bio</label><textarea id="edit-bio">__BIO__</textarea></div>
      </div>
      <button class="sbtn" onclick="saveProf()">&#x1F4BE; Simpan Profil</button>
      <button class="lbtn" onclick="doLogout()">&#x1F6AA; Logout</button>
    </div>
  </div>
</div>

<div class="ov" id="notif-ov">
  <div class="panel">
    <div class="ph"><h2>&#x1F514; Notifikasi</h2><button class="xbtn" onclick="closeOv('notif-ov');markRead()">&#10005;</button></div>
    <div class="pb" id="notif-list"><div style="text-align:center;color:var(--st);padding:20px;">Tidak ada notifikasi</div></div>
  </div>
</div>

<div class="ov" id="stview-ov">
  <div class="stv" id="stv">
    <div class="stv-prog" id="stv-prog"></div>
    <div class="stv-hd">
      <div id="stv-av" style="width:32px;height:32px;border-radius:50%;overflow:hidden;background:var(--g);display:flex;align-items:center;justify-content:center;font-weight:900;color:#fff;font-size:12px;"></div>
      <div style="flex:1;">
        <div style="font-weight:800;font-size:13.5px;color:#fff;" id="stv-name"></div>
        <div style="font-size:10.5px;color:rgba(255,255,255,.45);" id="stv-time"></div>
      </div>
      <button class="xbtn" onclick="closeStv()" style="background:rgba(255,255,255,.1);color:rgba(255,255,255,.7);">&#10005;</button>
    </div>
    <div class="stv-body" id="stv-body"></div>
    <div class="stv-nav">
      <button class="stv-nb" id="stv-prev" onclick="stvPrev()">&#9664; Prev</button>
      <button class="stv-nb" id="stv-next" onclick="stvNext()">Next &#9654;</button>
    </div>
  </div>
</div>

<div class="ov" id="cstat-ov">
  <div class="panel">
    <div class="ph"><h2>&#9999; Buat Status</h2><button class="xbtn" onclick="closeOv('cstat-ov')">&#10005;</button></div>
    <div class="pb">
      <div style="display:flex;flex-direction:column;gap:7px;">
        <div style="display:flex;align-items:center;gap:11px;padding:10px;background:var(--dk);border-radius:9px;border:1.5px solid var(--bd);cursor:pointer;" onclick="showTxtStat()">
          <div style="width:40px;height:40px;border-radius:50%;background:#2563eb22;display:flex;align-items:center;justify-content:center;font-size:17px;">&#9999;</div>
          <div><div style="font-weight:800;">Teks</div><div style="font-size:11.5px;color:var(--st);">Tulis status teks</div></div>
        </div>
        <div style="display:flex;align-items:center;gap:11px;padding:10px;background:var(--dk);border-radius:9px;border:1.5px solid var(--bd);cursor:pointer;" onclick="document.getElementById('stp').click()">
          <div style="width:40px;height:40px;border-radius:50%;background:#dc262622;display:flex;align-items:center;justify-content:center;font-size:17px;">&#x1F5BC;</div>
          <div><div style="font-weight:800;">Foto</div><div style="font-size:11.5px;color:var(--st);">Upload foto</div></div>
        </div>
        <div style="display:flex;align-items:center;gap:11px;padding:10px;background:var(--dk);border-radius:9px;border:1.5px solid var(--bd);cursor:pointer;" onclick="document.getElementById('stv2').click()">
          <div style="width:40px;height:40px;border-radius:50%;background:#7c3aed22;display:flex;align-items:center;justify-content:center;font-size:17px;">&#x1F3A5;</div>
          <div><div style="font-weight:800;">Video</div><div style="font-size:11.5px;color:var(--st);">Upload video</div></div>
        </div>
      </div>
      <input type="file" id="stp" accept="image/*" style="display:none" onchange="uploadStat(this,'image')">
      <input type="file" id="stv2" accept="video/*" style="display:none" onchange="uploadStat(this,'video')">
      <div id="txt-stat-form" style="display:none;margin-top:12px;">
        <div class="fg">
          <label>Teks Status</label>
          <textarea id="stat-txt" placeholder="Tulis status..." style="height:80px;" maxlength="200"></textarea>
          <div style="font-size:10px;color:var(--st);text-align:right;margin-top:2px;"><span id="scc">0</span>/200</div>
        </div>
        <button class="sbtn" onclick="postTxtStat()">Posting Status</button>
      </div>
    </div>
  </div>
</div>

<div class="ov" id="settings-ov">
  <div class="panel" style="width:430px;max-width:95vw;">
    <div class="ph"><h2>&#9881; Pengaturan</h2><button class="xbtn" onclick="closeOv('settings-ov')">&#10005;</button></div>
    <div style="padding:0;">
      <div class="sset">
        <div class="sset-title">&#x1F464; Akun</div>
        <div class="sset-item" onclick="closeOv('settings-ov');openOv('prof-ov')">
          <div class="sset-ic" style="background:#00a88422;color:#00a884;">&#x1F464;</div>
          <div class="sset-txt"><div class="sset-lbl">Profil Saya</div><div class="sset-sub">Ubah nama, foto &amp; bio</div></div>
          <div class="sset-chev">&#8250;</div>
        </div>
        <div class="sset-item" onclick="closeOv('settings-ov');openNotif()">
          <div class="sset-ic" style="background:#1a56db22;color:#1a56db;">&#x1F514;</div>
          <div class="sset-txt"><div class="sset-lbl">Notifikasi</div><div class="sset-sub">Lihat semua pemberitahuan</div></div>
          <div class="sset-chev">&#8250;</div>
        </div>
      </div>
      <div class="sset">
        <div class="sset-title">&#x1F512; Privasi</div>
        <div class="sset-item" onclick="togSetting('read')">
          <div class="sset-ic" style="background:#05966922;color:#059669;">&#10003;&#10003;</div>
          <div class="sset-txt"><div class="sset-lbl">Tanda Baca</div><div class="sset-sub">Tampilkan centang biru</div></div>
          <div class="stoggle on" id="tog-read" onclick="event.stopPropagation();togSetting('read')"><div class="stoggle-k"></div></div>
        </div>
        <div class="sset-item" onclick="togSetting('online')">
          <div class="sset-ic" style="background:#44c56a22;color:#44c56a;">&#11044;</div>
          <div class="sset-txt"><div class="sset-lbl">Status Online</div><div class="sset-sub">Tampilkan saat online</div></div>
          <div class="stoggle on" id="tog-online" onclick="event.stopPropagation();togSetting('online')"><div class="stoggle-k"></div></div>
        </div>
      </div>
      <div class="sset">
        <div class="sset-title">&#x1F4AC; Chat</div>
        <div class="sset-item" onclick="togSetting('enter')">
          <div class="sset-ic" style="background:#7c3aed22;color:#7c3aed;">&#8629;</div>
          <div class="sset-txt"><div class="sset-lbl">Enter untuk Kirim</div><div class="sset-sub">Tekan Enter langsung kirim</div></div>
          <div class="stoggle on" id="tog-enter" onclick="event.stopPropagation();togSetting('enter')"><div class="stoggle-k"></div></div>
        </div>
        <div class="sset-item" onclick="switchTab('status');closeOv('settings-ov')">
          <div class="sset-ic" style="background:#d9770622;color:#d97706;">&#x1F7E2;</div>
          <div class="sset-txt"><div class="sset-lbl">Status Saya</div><div class="sset-sub">Lihat dan buat status</div></div>
          <div class="sset-chev">&#8250;</div>
        </div>
        <div class="sset-item" onclick="openAI();closeOv('settings-ov')">
          <div class="sset-ic" style="background:#7c3aed22;color:#9b5de5;">&#x1F916;</div>
          <div class="sset-txt"><div class="sset-lbl">WaClone AI</div><div class="sset-sub">Asisten AI pintarmu</div></div>
          <div class="sset-chev">&#8250;</div>
        </div>
      </div>
      <div class="sset" style="border-bottom:none;">
        <div class="sset-title">&#8505; Tentang</div>
        <div class="sset-item">
          <div class="sset-ic" style="background:#00a88422;color:#00a884;">&#x1F4AC;</div>
          <div class="sset-txt"><div class="sset-lbl">WaClone v2.0</div><div class="sset-sub">Simple. Fast. Private.</div></div>
        </div>
        <div class="sset-item" onclick="doLogout()">
          <div class="sset-ic" style="background:#f15c6d22;color:#f15c6d;">&#x1F6AA;</div>
          <div class="sset-txt"><div class="sset-lbl" style="color:var(--rd);">Logout</div><div class="sset-sub">Keluar dari akun</div></div>
          <div class="sset-chev" style="color:var(--rd);">&#8250;</div>
        </div>
      </div>
    </div>
  </div>
</div>

<div class="ov" id="cam-ov">
  <div class="panel" style="width:400px;">
    <div class="ph"><h2>&#x1F4F7; Kamera</h2><button class="xbtn" onclick="closeCam()">&#10005;</button></div>
    <div class="pb">
      <div class="cam-wrap"><video id="cam-vid" autoplay playsinline muted></video></div>
      <canvas id="cam-canvas" style="display:none;width:100%;border-radius:9px;margin-top:7px;"></canvas>
      <div class="cam-ctrls">
        <button class="cam-b" style="background:var(--g);" onclick="snap()">&#x1F4F8;</button>
        <button class="cam-b" style="background:#2a3942;" onclick="flipCam()">&#x1F504;</button>
        <button class="cam-b" style="background:var(--rd);" onclick="closeCam()">&#10005;</button>
      </div>
      <div id="cam-send" style="display:none;margin-top:9px;">
        <button class="sbtn" onclick="sendSnap()">Kirim Foto</button>
      </div>
    </div>
  </div>
</div>

<div class="ov" id="fw-ov">
  <div class="panel">
    <div class="ph"><h2>&#8618; Teruskan Pesan</h2><button class="xbtn" onclick="closeOv('fw-ov')">&#10005;</button></div>
    <div class="pb">
      <div class="fw-list" id="fw-list"></div>
      <button class="sbtn" id="fw-go" style="display:none;margin-top:10px;" onclick="execFwd()">Kirim</button>
    </div>
  </div>
</div>

<div class="ov" id="img-ov" onclick="closeOv('img-ov')">
  <img id="img-full" src="" alt="" style="max-width:92vw;max-height:88vh;border-radius:7px;object-fit:contain;">
</div>

<!-- CALL UI -->
<div class="call-ui" id="call-ui">
  <div class="call-vid-grid" id="call-vid-grid" style="display:none;">
    <div class="rem-vid">
      <video id="rem-vid" autoplay playsinline></video>
      <div class="cam-off" id="rem-cam-off"><div style="font-size:46px;">&#x1F464;</div><div style="color:rgba(255,255,255,.4);font-size:12px;">Kamera off</div></div>
    </div>
    <div class="loc-vid">
      <video id="loc-vid" autoplay playsinline muted></video>
      <div class="cam-off" id="loc-cam-off"><div style="font-size:24px;">&#x1F4F7;</div></div>
    </div>
  </div>
  <div class="audio-info" id="audio-info">
    <div class="call-av" id="call-av">&#x1F464;</div>
    <div class="call-name" id="call-name">&#8212;</div>
    <div class="call-stat" id="call-stat">Memanggil...</div>
    <div class="call-timer" id="call-timer">00:00</div>
  </div>
  <div class="call-ctrls">
    <div style="display:flex;flex-direction:column;align-items:center;">
      <button class="ccbtn cc-tog cc-on" id="cc-mic" onclick="togMic()">&#x1F3A4;</button>
      <span class="cc-lbl">Mic</span>
    </div>
    <div style="display:flex;flex-direction:column;align-items:center;" id="cc-cam-wrap">
      <button class="ccbtn cc-tog cc-on" id="cc-cam" onclick="togCam()">&#x1F4F7;</button>
      <span class="cc-lbl">Kamera</span>
    </div>
    <div style="display:flex;flex-direction:column;align-items:center;">
      <button class="ccbtn cc-end" onclick="endCall()">&#x1F4F5;</button>
      <span class="cc-lbl">Tutup</span>
    </div>
    <div style="display:flex;flex-direction:column;align-items:center;">
      <button class="ccbtn cc-tog cc-on" id="cc-spk" onclick="togSpk()">&#x1F50A;</button>
      <span class="cc-lbl">Speaker</span>
    </div>
  </div>
</div>

<div class="inc-call" id="inc-call">
  <div class="inc-av" id="inc-av">&#x1F464;</div>
  <div style="text-align:center;font-size:16px;font-weight:900;" id="inc-name">&#8212;</div>
  <div style="text-align:center;font-size:11.5px;color:var(--st);margin-top:3px;" id="inc-type">Panggilan Masuk</div>
  <div class="inc-acts">
    <button class="inc-b inc-audio" onclick="answerCall('audio')">&#x1F4DE; Audio</button>
    <button class="inc-b inc-video" onclick="answerCall('video')">&#x1F4F9; Video</button>
    <button class="inc-b inc-rej" onclick="rejectCall()">&#x1F4F5;</button>
  </div>
</div>

<div class="toast" id="toast-el"></div>

<!-- ====== JS ====== -->
<script>
// ========================
// STATE
// ========================
const ME={uid:"__UID__",username:"__USERNAME__"};
const STUN={iceServers:[{urls:"stun:stun.l.google.com:19302"},{urls:"stun:stun1.l.google.com:19302"}]};
const EMOJIS=["&#x1F600;","&#x1F602;","&#x1F60D;","&#x1F970;","&#x1F60E;","&#x1F914;","&#x1F62D;","&#x1F621;","&#x1F44D;","&#x1F44E;","&#x2764;","&#x1F525;","&#x2705;","&#x2B50;","&#x1F389;","&#x1F64F;","&#x1F4AA;","&#x1F634;","&#x1F923;","&#x1F60A;","&#x1F618;","&#x1F917;","&#x1F97A;","&#x1F605;","&#x1F92C;","&#x1F919;","&#x1F480;","&#x1F60A;","&#x1FAC2;","&#x1F31F;","&#x1F4AF;","&#x1F38A;","&#x1F929;","&#x1F631;","&#x1FAF6;","&#x1F973;","&#x1F924;","&#x1FAE1;","&#x1F44B;","&#x1F64C;","&#x1F440;","&#x1F3B5;","&#x1F308;","&#x1F355;","&#x2615;","&#x1F680;","&#x1F4A1;","&#x1F3AF;","&#x1F3C6;","&#x1F48E;","&#x1F338;","&#x1F98B;","&#x1F319;","&#x2600;","&#x1F30A;","&#x1F340;","&#x1F436;","&#x1F431;","&#x1F981;","&#x1F43B;","&#x1F43C;"];

let allUsers=[],curFriend=null,pollTmr=null;
let replyData=null,ctxMsg=null;
let mediaRec=null,recChunks=[],isRec=false;
let pc=null,localStream=null,curCallId=null,callType="audio";
let callTmrInt=null,callSecs=0,micMuted=false,camOff=false,spkOff=false;
let incCallInfo=null;
let camStream=null,camFace="user",camMode="chat",camBlob=null;
let stvData=null,stvIdx=0,stvTmr=null;
let fwTxt="",fwTarget=null;
let lastPing=0;
let aiHistory=[];
let settings={read:true,online:true,enter:true};
let navStack=["home"];

// ========================
// UTILS
// ========================
function toast(msg,dur=2400,err=false){
  const t=document.getElementById("toast-el");
  t.textContent=msg;t.className="toast show"+(err?" err":"");
  setTimeout(()=>t.classList.remove("show"),dur);
}
function esc(s){return String(s||"").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");}
function fmtT(ts){
  const d=new Date(ts*1000),now=new Date();
  if(d.toDateString()===now.toDateString())return d.getHours().toString().padStart(2,"0")+":"+d.getMinutes().toString().padStart(2,"0");
  const diff=Math.floor((now-d)/86400000);
  if(diff===1)return"Kemarin";
  if(diff<7)return["Min","Sen","Sel","Rab","Kam","Jum","Sab"][d.getDay()];
  return d.getDate()+"/"+(d.getMonth()+1);
}
function mkAv(u,sz=46){
  if(u&&u.avatar)return`<img src="${u.avatar}" style="width:${sz}px;height:${sz}px;border-radius:50%;object-fit:cover;" onerror="this.style.display='none'">`;
  const n=(u&&u.username)?u.username:"?";
  const pal=["#00a884","#7c3aed","#1a56db","#dc2626","#d97706","#059669","#0891b2","#be185d"];
  const bg=pal[(n.charCodeAt(0)||0)%pal.length];
  return`<div style="width:${sz}px;height:${sz}px;border-radius:50%;background:${bg};display:flex;align-items:center;justify-content:center;font-weight:900;font-size:${Math.floor(sz*.42)}px;color:#fff;flex-shrink:0;">${n[0].toUpperCase()}</div>`;
}

// ========================
// OVERLAY
// ========================
function openOv(id){document.getElementById(id).classList.add("open");navPush({type:"ov",id});}
function closeOv(id){document.getElementById(id).classList.remove("open");}
function openNotif(){openOv("notif-ov");loadNotifs();}

// ========================
// NAV STACK
// ========================
function navPush(s){
  const top=navStack[navStack.length-1];
  if(top&&typeof top==="object"&&s&&typeof s==="object"&&top.type===s.type&&top.id===s.id)return;
  navStack.push(s);
}
function goBack(){
  // 1. Close open overlays first
  const opens=[...document.querySelectorAll(".ov.open")];
  if(opens.length){opens[opens.length-1].classList.remove("open");const idx=navStack.findLastIndex(x=>x&&x.type==="ov");if(idx>=0)navStack.splice(idx,1);return;}
  // 2. Close AI drawer
  if(document.getElementById("ai-drw").classList.contains("open")){closeAI();return;}
  // 3. Go back from chat to home
  if(curFriend){
    document.getElementById("sb").classList.remove("gone");
    document.getElementById("chat-wrap").style.display="none";
    document.getElementById("no-chat").style.display="flex";
    curFriend=null;
    if(pollTmr){clearInterval(pollTmr);pollTmr=null;}
    return;
  }
}

// ========================
// TABS
// ========================
function switchTab(t){
  ["chats","status","contacts"].forEach(x=>{
    document.getElementById("tab-"+x).classList.toggle("active",x===t);
    document.getElementById("panel-"+x).classList.toggle("active",x===t);
  });
  document.getElementById("srch-wrap").style.display=(t==="status")?"none":"";
  if(t==="status")loadStatTab();
}
function closeMenus(){
  document.getElementById("att-menu").classList.remove("open");
  document.getElementById("emoji-pick").classList.remove("open");
  document.getElementById("ctx").style.display="none";
}

// ========================
// USERS & RENDER
// ========================
async function loadUsers(){
  try{const r=await fetch("/api/users");const d=await r.json();allUsers=d.users||[];renderChats();renderContacts();checkNotifBadge();}catch(e){}
}
function renderChats(){
  const el=document.getElementById("chat-list");
  const others=allUsers.filter(u=>u.uid!==ME.uid);
  if(!others.length){el.innerHTML='<div style="padding:26px;text-align:center;color:var(--st);font-size:13px;">Belum ada pengguna</div>';return;}
  el.innerHTML=others.map(u=>chatItemHtml(u)).join("");
}
function renderContacts(){
  const el=document.getElementById("contacts-list");
  const sorted=[...allUsers.filter(u=>u.uid!==ME.uid)].sort((a,b)=>a.username.localeCompare(b.username));
  if(!sorted.length){el.innerHTML='<div style="padding:26px;text-align:center;color:var(--st);">Tidak ada kontak</div>';return;}
  el.innerHTML=sorted.map(u=>chatItemHtml(u,true)).join("");
}
function chatItemHtml(u,isC=false){
  const av=mkAv(u,46);
  const ring=u.online?'<div class="online-ring"></div>':""
  const prev=esc(isC?(u.bio||"Tap untuk chat"):(u.last_msg||u.bio||"Tap untuk chat")).substring(0,38);
  const tm=u.last_time?fmtT(u.last_time):"";
  const badge=u.unread_count>0?`<div class="ubadge">${u.unread_count>99?"99+":u.unread_count}</div>`:"";
  const active=curFriend&&curFriend.uid===u.uid;
  const su=(u.username||"").replace(/\\/g,"\\\\").replace(/'/g,"\\'");
  const sa=(u.avatar||"").replace(/\\/g,"\\\\").replace(/'/g,"\\'");
  const sb=(u.bio||"").replace(/\\/g,"\\\\").replace(/'/g,"\\'");
  return`<div class="chat-item${active?" active":""}" data-uid="${u.uid}" data-name="${esc(u.username)}"
    onclick="openChat('${u.uid}','${su}','${sa}','${sb}')">
    <div class="av48">${av}${ring}</div>
    <div class="chat-info"><div class="chat-name">${esc(u.username)}</div><div class="chat-prev">${prev}</div></div>
    <div class="chat-meta"><div class="chat-time">${tm}</div>${badge}</div>
  </div>`;
}
function filterList(q){
  const lq=q.toLowerCase();
  document.querySelectorAll(".chat-item").forEach(el=>el.style.display=el.dataset.name.toLowerCase().includes(lq)?"":"none");
}

// ========================
// OPEN CHAT
// ========================
function openChat(uid,name,avatar,bio){
  curFriend={uid,name,avatar,bio};
  navPush({type:"chat",uid,name});
  document.getElementById("no-chat").style.display="none";
  document.getElementById("chat-wrap").style.display="flex";
  if(window.innerWidth<=680)document.getElementById("sb").classList.add("gone");
  document.getElementById("hdr-av").innerHTML=mkAv(curFriend,38);
  document.getElementById("hdr-name").textContent=name;
  document.getElementById("hdr-stat").textContent="Memuat...";
  document.querySelectorAll(".chat-item").forEach(e=>e.classList.toggle("active",e.dataset.uid===uid));
  cancelReply();closeMenus();
  loadMsgs();
  if(pollTmr)clearInterval(pollTmr);
  pollTmr=setInterval(()=>{loadMsgs();checkTyping();},3000);
  fetch("/api/mark_read",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({friend_uid:uid})});
  setTimeout(()=>document.getElementById("msg-inp").focus(),100);
}

// ========================
// MESSAGES
// ========================
async function loadMsgs(){
  if(!curFriend)return;
  try{
    const r=await fetch(`/api/messages?friend_uid=${curFriend.uid}`);const d=await r.json();
    renderMsgs(d.messages||[]);
    const f=allUsers.find(u=>u.uid===curFriend.uid);
    if(f){
      const s=document.getElementById("hdr-stat");
      s.textContent=f.online?"Online":(f.last_seen?`Terakhir ${fmtT(f.last_seen)}`:"Offline");
      s.style.color=f.online?"var(--g)":"var(--st)";
    }
  }catch(e){}
}
function renderMsgs(msgs){
  const area=document.getElementById("msgs-area");
  const atBot=area.scrollHeight-area.clientHeight<=area.scrollTop+130;
  if(!msgs.length){area.innerHTML='<div style="text-align:center;color:var(--st);padding:32px;font-size:12.5px;">Belum ada pesan. Mulai percakapan!</div>';return;}
  let html="",lastDt="";
  msgs.forEach(m=>{
    const d=new Date(m.time*1000);
    const ds=d.toLocaleDateString("id-ID",{day:"2-digit",month:"long",year:"numeric"});
    if(ds!==lastDt){html+=`<div class="date-div"><span>${ds}</span></div>`;lastDt=ds;}
    const isOut=m.from===ME.uid;
    const ts=d.getHours().toString().padStart(2,"0")+":"+d.getMinutes().toString().padStart(2,"0");
    let tick="";
    if(isOut){tick=m.status==="read"?'<span class="tick read">&#10003;&#10003;</span>':m.status==="delivered"?'<span class="tick">&#10003;&#10003;</span>':'<span class="tick">&#10003;</span>';}
    let rqHtml="";
    if(m.reply_to&&m.reply_to.text){
      const rn=m.reply_to.from===ME.uid?"Kamu":(curFriend?curFriend.name:"?");
      rqHtml=`<div class="rq"><div class="rq-n">${esc(rn)}</div><div class="rq-t">${esc(m.reply_to.text)}</div></div>`;
    }
    let cnt="";
    if(m.file){
      const ft=m.file_type||"";
      if(ft.startsWith("image/")||/\.(jpg|jpeg|png|gif|webp|bmp|heic)$/i.test(m.file))
        cnt+=`<img src="${m.file}" onclick="viewImg('${m.file}')" loading="lazy" alt="foto">`;
      else if(ft.startsWith("video/")||/\.(mp4|webm|mov|avi)$/i.test(m.file))
        cnt+=`<video src="${m.file}" controls style="max-width:230px;border-radius:7px;display:block;margin-bottom:2px;"></video>`;
      else if(ft.startsWith("audio/")||/\.(ogg|m4a|wav|mp3|webm)$/i.test(m.file))
        cnt+=`<audio src="${m.file}" controls></audio>`;
      else{const fn=m.file.split("/").pop().split("?")[0].substring(0,28);cnt+=`<a class="flink" href="${m.file}" target="_blank">&#x1F4C4; ${esc(fn)}</a>`;}
    }
    if(m.message)cnt+=`<span>${esc(m.message)}</span>`;
    const st=String(m.message||"").replace(/"/g,"&quot;").replace(/'/g,"&#39;");
    const acts=`<div class="msg-acts">
      <button class="act-b" onclick="setReply('${m.id}','${st}','${m.from}')" title="Balas">&#8617;</button>
      <button class="act-b" onclick="showCtx(event,'${m.id}','${st}','${m.from}')" title="Lebih">&#8943;</button>
    </div>`;
    html+=`<div class="msg-row ${isOut?"out":"in"}" data-id="${m.id}"
      oncontextmenu="showCtx(event,'${m.id}','${st}','${m.from}')"
      ontouchstart="tStart(event,'${m.id}','${st}','${m.from}')" ontouchend="tEnd()">
      ${isOut?acts:""}
      <div class="bubble">${rqHtml}${cnt}<div class="btime">${ts} ${tick}</div></div>
      ${!isOut?acts:""}
    </div>`;
  });
  area.innerHTML=html;
  if(atBot)area.scrollTop=area.scrollHeight;
}
function handleKey(e){if(settings.enter&&e.key==="Enter"&&!e.shiftKey){e.preventDefault();sendMsg();}}
function onInp(el){el.style.height="auto";el.style.height=Math.min(el.scrollHeight,110)+"px";pingTyping();}
async function sendMsg(){
  const inp=document.getElementById("msg-inp");const txt=inp.value.trim();
  if(!txt||!curFriend)return;
  inp.value="";inp.style.height="auto";
  const body={to_uid:curFriend.uid,message:txt};
  if(replyData)body.reply_to={id:replyData.id,text:replyData.text,from:replyData.from};
  cancelReply();
  try{const r=await fetch("/api/send",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});const d=await r.json();if(d.ok)loadMsgs();else toast("Gagal kirim",2500,true);}
  catch(e){toast("Gagal kirim",2500,true);}
}

// ========================
// REPLY
// ========================
function cancelReply(){replyData=null;document.getElementById("rply-prev").classList.remove("show");}
function setReply(id,txt,from){
  const t=txt.replace(/&#39;/g,"'").replace(/&quot;/g,'"');
  replyData={id,text:t,from};
  const n=from===ME.uid?"Kamu":(curFriend?curFriend.name:"?");
  document.getElementById("rp-n").textContent=n;
  document.getElementById("rp-t").textContent=t||"Media";
  document.getElementById("rply-prev").classList.add("show");
  document.getElementById("msg-inp").focus();
}

// ========================
// CTX MENU
// ========================
let ttmr=null;
function showCtx(e,id,txt,from){
  e.preventDefault();e.stopPropagation();
  ctxMsg={id,txt:txt.replace(/&#39;/g,"'").replace(/&quot;/g,'"'),from};
  const m=document.getElementById("ctx");m.style.display="block";
  const mw=m.offsetWidth||170,mh=m.offsetHeight||180;
  m.style.left=Math.min(e.clientX,window.innerWidth-mw-6)+"px";
  m.style.top=Math.min(e.clientY,window.innerHeight-mh-6)+"px";
  setTimeout(()=>document.addEventListener("click",()=>m.style.display="none",{once:true}),50);
}
function tStart(e,id,txt,from){ttmr=setTimeout(()=>{ctxMsg={id,txt:txt.replace(/&#39;/g,"'"),from};const t=e.touches[0];showCtx({clientX:t.clientX,clientY:t.clientY,preventDefault:()=>{},stopPropagation:()=>{}},id,txt,from);},600);}
function tEnd(){if(ttmr){clearTimeout(ttmr);ttmr=null;}}
function doReply(){if(!ctxMsg)return;setReply(ctxMsg.id,ctxMsg.txt,ctxMsg.from);document.getElementById("ctx").style.display="none";}
function doCopy(){if(!ctxMsg)return;navigator.clipboard.writeText(ctxMsg.txt).then(()=>toast("Disalin "));document.getElementById("ctx").style.display="none";}
function doFwd(){
  if(!ctxMsg)return;fwTxt=ctxMsg.txt;fwTarget=null;
  document.getElementById("fw-list").innerHTML=allUsers.filter(u=>u.uid!==ME.uid).map(u=>`<div class="fw-item" id="fwi-${u.uid}" onclick="selFw('${u.uid}')"><div style="width:34px;height:34px;border-radius:50%;overflow:hidden;flex-shrink:0;">${mkAv(u,34)}</div><span style="font-weight:700;">${esc(u.username)}</span></div>`).join("");
  document.getElementById("fw-go").style.display="none";
  openOv("fw-ov");document.getElementById("ctx").style.display="none";
}
function doAskAI(){if(!ctxMsg)return;openAI();setTimeout(()=>{const t=document.getElementById("ai-ta");t.value=`Bantu saya membalas: "${ctxMsg.txt}"`;aiResize(t);},300);document.getElementById("ctx").style.display="none";}
function selFw(uid){document.querySelectorAll(".fw-item").forEach(e=>e.classList.remove("sel"));document.getElementById("fwi-"+uid).classList.add("sel");fwTarget=uid;document.getElementById("fw-go").style.display="block";}
async function execFwd(){if(!fwTarget||!fwTxt)return;const r=await fetch("/api/send",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({to_uid:fwTarget,message:">> "+fwTxt})});const d=await r.json();if(d.ok){toast("Diteruskan");closeOv("fw-ov");}else toast("Gagal",2500,true);}
async function doDel(){if(!ctxMsg||!curFriend)return;document.getElementById("ctx").style.display="none";if(!confirm("Hapus pesan ini?"))return;const r=await fetch("/api/delete_message",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({message_id:ctxMsg.id,friend_uid:curFriend.uid})});const d=await r.json();if(d.ok){loadMsgs();toast("Dihapus");}else toast("Gagal hapus",2500,true);}

// ========================
// EMOJI
// ========================
function buildEmoji(){document.getElementById("emoji-grid").innerHTML=EMOJIS.map(e=>`<span class="emj" onclick="insEmoji('${e}')">${e}</span>`).join("");}
function toggleEmoji(){closeMenus();document.getElementById("emoji-pick").classList.toggle("open");}
function insEmoji(e){const inp=document.getElementById("msg-inp");const s=inp.selectionStart;inp.value=inp.value.substring(0,s)+e+inp.value.substring(inp.selectionEnd);inp.selectionStart=inp.selectionEnd=s+e.length;inp.focus();onInp(inp);document.getElementById("emoji-pick").classList.remove("open");}

// ========================
// FILE UPLOAD
// ========================
function toggleAtt(){closeMenus();document.getElementById("att-menu").classList.toggle("open");}
function trigFile(t){document.getElementById("att-menu").classList.remove("open");document.getElementById(t==="photo"?"fp":"fd").click();}
function showUp(){const b=document.getElementById("upbar"),f=document.getElementById("upfill");b.classList.add("show");f.style.width="0%";let w=0;const iv=setInterval(()=>{w+=Math.random()*8;if(w>=86)clearInterval(iv);f.style.width=Math.min(w,86)+"%";},200);return()=>{f.style.width="100%";setTimeout(()=>b.classList.remove("show"),500);clearInterval(iv);};}
async function doUpload(inp){
  if(!inp.files[0]||!curFriend)return;
  document.getElementById("att-menu").classList.remove("open");
  const done=showUp(),fd=new FormData();
  fd.append("file",inp.files[0]);fd.append("to_uid",curFriend.uid);
  if(replyData){fd.append("reply_from",replyData.from);fd.append("reply_text",replyData.text);}
  try{const r=await fetch("/api/send_file",{method:"POST",body:fd});const d=await r.json();done();if(d.ok){toast("Terkirim");cancelReply();loadMsgs();}else toast("Gagal: "+(d.msg||""),3000,true);}
  catch(e){done();toast("Gagal upload",2500,true);}
  inp.value="";
}

// ========================
// CAMERA
// ========================
function openCamChat(){document.getElementById("att-menu").classList.remove("open");camMode="chat";openCam();}
async function openCam(){
  try{camStream=await navigator.mediaDevices.getUserMedia({video:{facingMode:camFace},audio:false});document.getElementById("cam-vid").srcObject=camStream;document.getElementById("cam-canvas").style.display="none";document.getElementById("cam-send").style.display="none";camBlob=null;openOv("cam-ov");}
  catch(e){toast("Kamera tidak bisa diakses: "+e.message,3000,true);}
}
function flipCam(){camFace=camFace==="user"?"environment":"user";closeCam();setTimeout(openCam,200);}
function snap(){const v=document.getElementById("cam-vid"),c=document.getElementById("cam-canvas");c.width=v.videoWidth;c.height=v.videoHeight;c.getContext("2d").drawImage(v,0,0);c.style.display="block";c.toBlob(b=>{camBlob=b;},"image/jpeg",.92);document.getElementById("cam-send").style.display="block";}
async function sendSnap(){
  if(!camBlob){toast("Ambil foto dulu",2000,true);return;}
  closeCam();const done=showUp(),fd=new FormData();
  fd.append("file",new File([camBlob],"camera.jpg",{type:"image/jpeg"}));
  if(camMode==="status"){fd.append("type","image");const r=await fetch("/api/status/upload",{method:"POST",body:fd});const d=await r.json();done();if(d.ok){toast("Status diposting");loadStatTab();}else toast("Gagal",2500,true);}
  else{if(!curFriend){done();return;}fd.append("to_uid",curFriend.uid);const r=await fetch("/api/send_file",{method:"POST",body:fd});const d=await r.json();done();if(d.ok){toast("Foto terkirim");loadMsgs();}else toast("Gagal",2500,true);}
}
function closeCam(){if(camStream)camStream.getTracks().forEach(t=>t.stop());camStream=null;closeOv("cam-ov");}

// ========================
// VOICE
// ========================
async function startVoice(e){if(e)e.preventDefault();if(!curFriend){toast("Pilih chat dulu",2000,true);return;}
  try{const s=await navigator.mediaDevices.getUserMedia({audio:true});const mime=MediaRecorder.isTypeSupported("audio/webm")?"audio/webm":"audio/ogg";mediaRec=new MediaRecorder(s,{mimeType:mime});recChunks=[];isRec=true;
    mediaRec.ondataavailable=e=>recChunks.push(e.data);
    mediaRec.onstop=async()=>{const blob=new Blob(recChunks,{type:mime});s.getTracks().forEach(t=>t.stop());if(blob.size>500&&curFriend){const done=showUp(),fd=new FormData();fd.append("file",new File([blob],"voice.webm",{type:mime}));fd.append("to_uid",curFriend.uid);const r=await fetch("/api/send_file",{method:"POST",body:fd});const d=await r.json();done();if(d.ok){toast("Suara terkirim");loadMsgs();}else toast("Gagal",2500,true);}};
    mediaRec.start();document.getElementById("rec-b").classList.add("recording");toast("Merekam... Lepaskan untuk kirim",12000);
  }catch(e){toast("Mic tidak bisa diakses",2500,true);}
}
function stopVoice(e){if(e)e.preventDefault();if(mediaRec&&isRec){mediaRec.stop();isRec=false;document.getElementById("rec-b").classList.remove("recording");toast("Mengirim...",1500);}}
function viewImg(src){document.getElementById("img-full").src=src;openOv("img-ov");}

// ========================
// TYPING
// ========================
async function pingTyping(){const now=Date.now();if(now-lastPing<2000||!curFriend)return;lastPing=now;await fetch("/api/typing",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({to_uid:curFriend.uid})}).catch(()=>{});}
async function checkTyping(){if(!curFriend)return;try{const r=await fetch(`/api/typing_status?friend_uid=${curFriend.uid}`);const d=await r.json();const el=document.getElementById("tdots");if(d.typing){document.getElementById("ttext").textContent=curFriend.name+" sedang mengetik...";el.classList.add("show");}else el.classList.remove("show");}catch(e){}}

// ========================
// STATUS
// ========================
async function loadStatTab(){
  try{
    const r=await fetch("/api/status/list");const d=await r.json();
    const my=d.my_statuses||[],others=d.statuses||[];
    // My hint
    const hint=document.getElementById("my-stat-hint");
    if(my.length)hint.textContent=`${my.length} status \xB7 ${fmtT(my[my.length-1].time)}`;
    else hint.textContent="Ketuk untuk lihat atau buat status";
    // Update my ring border
    document.getElementById("my-stat-ring").className="stat-ring"+(my.length?"":" grey");
    // Friends
    const byU={};others.forEach(s=>{if(!byU[s.uid])byU[s.uid]=[];byU[s.uid].push(s);});
    const entries=Object.entries(byU);
    const fl=document.getElementById("friend-stat-list");
    const lbl=document.getElementById("friend-stat-lbl");
    const empty=document.getElementById("stat-empty");
    if(!entries.length){fl.innerHTML="";lbl.style.display="none";empty.style.display="";return;}
    lbl.style.display="";empty.style.display="none";
    fl.innerHTML=entries.map(([uid,sts])=>{
      const u=allUsers.find(x=>x.uid===uid)||{uid,username:"?",avatar:""};
      const lat=sts[sts.length-1];
      return`<div class="stat-friend-item" onclick="viewFriendStat('${uid}')">
        <div class="stat-ring-wrap">
          <div class="stat-ring"><div class="stat-ring-in">${mkAv(u,42)}</div></div>
        </div>
        <div style="flex:1;min-width:0;margin-left:10px;">
          <div style="font-weight:800;font-size:13.5px;">${esc(u.username)}</div>
          <div style="font-size:11px;color:var(--st);margin-top:1px;">${fmtT(lat.time)} &middot; ${sts.length} status</div>
        </div>
        ${u.online?'<div style="width:8px;height:8px;border-radius:50%;background:#44c56a;flex-shrink:0;"></div>':""}
      </div>`;
    }).join("");
  }catch(e){console.log("stat err",e);}
}
async function openMyStatus(){
  const r=await fetch("/api/status/my");const d=await r.json();
  const my=d.statuses||[];
  if(!my.length){openOv("cstat-ov");return;}
  stvData={user:{uid:ME.uid,username:ME.username,avatar:""},statuses:my};
  stvIdx=0;renderStv();openOv("stview-ov");
}
async function viewFriendStat(uid){
  const r=await fetch(`/api/status/user/${uid}`);const d=await r.json();
  if(!d.statuses||!d.statuses.length){toast("Tidak ada status",2000);return;}
  const u=allUsers.find(x=>x.uid===uid)||{uid,username:"?",avatar:""};
  stvData={user:u,statuses:d.statuses};stvIdx=0;renderStv();openOv("stview-ov");
}
function closeStv(){clearStvT();closeOv("stview-ov");}
function clearStvT(){if(stvTmr){clearInterval(stvTmr);stvTmr=null;}}
function stvPrev(){if(stvIdx>0){stvIdx--;renderStv();}}
function stvNext(){if(stvData&&stvIdx<stvData.statuses.length-1){stvIdx++;renderStv();}else closeStv();}
function renderStv(){
  if(!stvData)return;
  const{user,statuses}=stvData,s=statuses[stvIdx];
  document.getElementById("stv-av").innerHTML=mkAv(user,32);
  document.getElementById("stv-name").textContent=user.username;
  document.getElementById("stv-time").textContent=fmtT(s.time);
  document.getElementById("stv-prog").innerHTML=statuses.map((_,i)=>`<div class="stv-seg"><div class="stv-fill" id="sf-${i}" style="width:${i<stvIdx?"100":"0"}%;transition:none;"></div></div>`).join("");
  let body="";
  if(s.type==="text"){const bgs=["#005c4b","#1a56db","#7c3aed","#dc2626","#d97706"];body=`<div class="stv-text-content" style="background:${bgs[stvIdx%bgs.length]};">${esc(s.content)}</div>`;}
  else if(s.type==="image")body=`<img class="stv-img" src="${s.media_url}" alt="status">`;
  else if(s.type==="video")body=`<video src="${s.media_url}" controls autoplay playsinline style="max-width:100%;max-height:340px;border-radius:10px;display:block;"></video>`;
  document.getElementById("stv-body").innerHTML=body;
  document.getElementById("stv-prev").disabled=(stvIdx===0);
  document.getElementById("stv-next").textContent=stvIdx>=statuses.length-1?"Tutup":"Next &#9654;";
  clearStvT();
  requestAnimationFrame(()=>{const f=document.getElementById(`sf-${stvIdx}`);if(f){f.style.transition="width 5s linear";f.style.width="100%";}});
  stvTmr=setInterval(()=>{stvIdx<statuses.length-1?(stvIdx++,renderStv()):closeStv();},5000);
}
function showTxtStat(){document.getElementById("txt-stat-form").style.display="block";}
document.addEventListener("input",e=>{if(e.target.id==="stat-txt")document.getElementById("scc").textContent=e.target.value.length;});
async function postTxtStat(){
  const txt=document.getElementById("stat-txt").value.trim();
  if(!txt){toast("Tulis status dulu",2000,true);return;}
  const r=await fetch("/api/status/create",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({type:"text",content:txt})});
  const d=await r.json();
  if(d.ok){toast("Status diposting");closeOv("cstat-ov");document.getElementById("stat-txt").value="";document.getElementById("scc").textContent="0";document.getElementById("txt-stat-form").style.display="none";loadStatTab();}
  else toast("Gagal: "+(d.msg||""),3000,true);
}
async function uploadStat(inp,type){
  if(!inp.files[0])return;const done=showUp(),fd=new FormData();
  fd.append("file",inp.files[0]);fd.append("type",type);
  const r=await fetch("/api/status/upload",{method:"POST",body:fd});const d=await r.json();done();
  if(d.ok){toast("Status diposting");closeOv("cstat-ov");loadStatTab();}else toast("Gagal",3000,true);
  inp.value="";
}

// ========================
// PROFILE & LOGOUT
// ========================
async function uploadAv(inp){
  if(!inp.files[0])return;if(inp.files[0].size>10*1024*1024){toast("Max 10MB",2500,true);return;}
  const done=showUp(),fd=new FormData();fd.append("avatar",inp.files[0]);
  try{const r=await fetch("/api/upload_avatar",{method:"POST",body:fd});const d=await r.json();done();if(d.ok){const url=d.url+"?t="+Date.now();document.getElementById("pavbig").innerHTML=`<img src="${url}" style="width:100%;height:100%;object-fit:cover;">`;document.getElementById("myav").innerHTML=`<img src="${url}" style="width:38px;height:38px;border-radius:50%;object-fit:cover;">`;toast("Foto diperbarui");}else toast("Gagal: "+(d.msg||""),3000,true);}
  catch(e){done();toast("Gagal upload",2500,true);}
  inp.value="";
}
async function saveProf(){
  const u=document.getElementById("edit-uname").value.trim(),b=document.getElementById("edit-bio").value.trim();
  if(!u){toast("Username kosong",2500,true);return;}
  const fd=new FormData();fd.append("username",u);fd.append("bio",b);
  const r=await fetch("/api/update_profile",{method:"POST",body:fd});const d=await r.json();
  if(d.ok){document.getElementById("pname").textContent=u;toast("Profil disimpan");closeOv("prof-ov");setTimeout(()=>location.reload(),700);}
  else toast("Gagal: "+(d.msg||""),3000,true);
}
function doLogout(){if(confirm("Logout?"))fetch("/logout",{method:"POST"}).then(()=>location.href="/");}

// ========================
// NOTIFICATIONS
// ========================
async function checkNotifBadge(){try{const r=await fetch("/api/notifications");const d=await r.json();const n=(d.notifications||[]).filter(x=>!x.read).length;const b=document.getElementById("nbadge");b.style.display=n>0?"":"none";b.textContent=n>9?"9+":n;}catch(e){}}
async function loadNotifs(){
  const r=await fetch("/api/notifications");const d=await r.json();
  const el=document.getElementById("notif-list");const notifs=d.notifications||[];
  if(!notifs.length){el.innerHTML='<div style="text-align:center;color:var(--st);padding:20px;">Tidak ada notifikasi</div>';return;}
  el.innerHTML=notifs.slice().reverse().map(n=>{
    const u=allUsers.find(x=>x.uid===n.from);const nm=u?.username||"?";
    return`<div class="notif-item" onclick="closeOv('notif-ov');openChat('${n.from}','${(nm).replace(/'/g,"\\'")}','${u?.avatar||""}','')">
      <div style="width:40px;height:40px;border-radius:50%;overflow:hidden;flex-shrink:0;">${mkAv(u||{username:nm},40)}</div>
      <div style="flex:1;min-width:0;"><div style="font-weight:800;font-size:13.5px;">${esc(nm)}</div><div style="font-size:11.5px;color:var(--st);">${esc(n.message)}</div><div style="font-size:10.5px;color:var(--st);margin-top:1px;">${fmtT(n.time)}</div></div>
      ${!n.read?'<div class="notif-dot"></div>':""}
    </div>`;
  }).join("");
}
async function markRead(){await fetch("/api/notifications/read",{method:"POST"});checkNotifBadge();}

// ========================
// SETTINGS
// ========================
function togSetting(k){
  settings[k]=!settings[k];
  const el=document.getElementById("tog-"+k);
  if(el)el.classList.toggle("on",settings[k]);
  toast(settings[k]?(k==="read"?"Tanda baca aktif":k==="online"?"Status online aktif":"Enter kirim aktif"):(k==="read"?"Tanda baca nonaktif":k==="online"?"Status online nonaktif":"Enter kirim nonaktif"),1800);
}

// ========================
// WEBRTC CALLS
// ========================
async function startCall(type){
  if(!curFriend){toast("Pilih teman dulu");return;}
  callType=type;
  try{localStream=await navigator.mediaDevices.getUserMedia(type==="video"?{video:true,audio:true}:{audio:true});}
  catch(e){toast("Tidak bisa akses media: "+e.message,3000,true);return;}
  showCallUI(curFriend,type,"out");
  pc=new RTCPeerConnection(STUN);
  localStream.getTracks().forEach(t=>pc.addTrack(t,localStream));
  if(type==="video"){document.getElementById("loc-vid").srcObject=localStream;setVidLayout(true);}
  pc.ontrack=e=>{document.getElementById("rem-vid").srcObject=e.streams[0];document.getElementById("rem-cam-off").classList.remove("show");};
  pc.onicecandidate=e=>{if(e.candidate)sendICE({candidate:e.candidate});};
  const offer=await pc.createOffer();await pc.setLocalDescription(offer);
  const r=await fetch("/api/call/offer",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({to_uid:curFriend.uid,sdp:offer,call_type:type})});
  const d=await r.json();curCallId=d.call_id;
  pollAns();
}
async function pollAns(){
  if(!curCallId)return;
  const r=await fetch(`/api/call/status/${curCallId}`);const d=await r.json();
  if(d.status==="answered"){await pc.setRemoteDescription(new RTCSessionDescription(d.answer));document.getElementById("call-stat").textContent="Terhubung";document.getElementById("call-stat").style.color="var(--g)";startCallTmr();pollICE();}
  else if(d.status==="rejected"){toast("Panggilan ditolak",3000);endCall();}
  else if(d.status==="pending")setTimeout(pollAns,2000);
  else if(d.status==="ended")endCall();
}
async function sendICE(data){if(!curCallId)return;await fetch("/api/call/ice",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({call_id:curCallId,type:"ice",data})});}
async function pollICE(){
  if(!curCallId||!pc)return;
  const r=await fetch(`/api/call/ice/${curCallId}?uid=${ME.uid}`);const d=await r.json();
  for(const c of(d.candidates||[])){try{await pc.addIceCandidate(new RTCIceCandidate(c));}catch(e){}}
  if(curCallId)setTimeout(pollICE,2000);
}
async function answerCall(type){
  if(!incCallInfo)return;curCallId=incCallInfo.call_id;callType=type;
  document.getElementById("inc-call").classList.remove("show");
  const caller=allUsers.find(u=>u.uid===incCallInfo.from)||{username:"?",avatar:"",uid:incCallInfo.from};
  try{localStream=await navigator.mediaDevices.getUserMedia(type==="video"?{video:true,audio:true}:{audio:true});}
  catch(e){toast("Tidak bisa akses media",2500,true);return;}
  showCallUI(caller,type,"in");
  pc=new RTCPeerConnection(STUN);
  localStream.getTracks().forEach(t=>pc.addTrack(t,localStream));
  if(type==="video"){document.getElementById("loc-vid").srcObject=localStream;setVidLayout(true);}
  pc.ontrack=e=>{document.getElementById("rem-vid").srcObject=e.streams[0];document.getElementById("rem-cam-off").classList.remove("show");};
  pc.onicecandidate=e=>{if(e.candidate)sendICE({candidate:e.candidate});};
  await pc.setRemoteDescription(new RTCSessionDescription(incCallInfo.sdp));
  const ans=await pc.createAnswer();await pc.setLocalDescription(ans);
  await fetch("/api/call/answer",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({call_id:curCallId,answer:ans})});
  document.getElementById("call-stat").textContent="Terhubung";document.getElementById("call-stat").style.color="var(--g)";startCallTmr();pollICE();
}
function rejectCall(){if(incCallInfo)fetch("/api/call/reject",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({call_id:incCallInfo.call_id})});document.getElementById("inc-call").classList.remove("show");incCallInfo=null;}
function showCallUI(friend,type,dir){
  document.getElementById("call-ui").classList.add("active");
  const name=friend.name||friend.username||"?";
  document.getElementById("call-av").innerHTML=friend.avatar?`<img src="${friend.avatar}" style="width:110px;height:110px;border-radius:50%;object-fit:cover;">`:(name[0]||"?").toUpperCase();
  document.getElementById("call-name").textContent=name;
  document.getElementById("call-stat").textContent=dir==="out"?"Memanggil...":"Panggilan masuk...";
  document.getElementById("call-stat").style.color="rgba(255,255,255,.5)";
  document.getElementById("call-timer").style.display="none";
  document.getElementById("cc-cam-wrap").style.display=type==="video"?"flex":"none";
  micMuted=false;camOff=false;
  document.getElementById("cc-mic").className="ccbtn cc-tog cc-on";
  document.getElementById("cc-cam").className="ccbtn cc-tog cc-on";
}
function setVidLayout(show){document.getElementById("call-vid-grid").style.display=show?"flex":"none";document.getElementById("audio-info").style.display=show?"none":"flex";}
function endCall(){if(pc){pc.close();pc=null;}if(localStream){localStream.getTracks().forEach(t=>t.stop());localStream=null;}if(callTmrInt){clearInterval(callTmrInt);callTmrInt=null;}if(curCallId){fetch("/api/call/end",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({call_id:curCallId})});curCallId=null;}document.getElementById("call-ui").classList.remove("active");setVidLayout(false);callSecs=0;}
function startCallTmr(){callSecs=0;document.getElementById("call-timer").style.display="block";callTmrInt=setInterval(()=>{callSecs++;const m=Math.floor(callSecs/60).toString().padStart(2,"0"),s=(callSecs%60).toString().padStart(2,"0");document.getElementById("call-timer").textContent=m+":"+s;},1000);}
function togMic(){micMuted=!micMuted;if(localStream)localStream.getAudioTracks().forEach(t=>t.enabled=!micMuted);const b=document.getElementById("cc-mic");b.textContent=micMuted?"&#x1F507;":"&#x1F3A4;";b.className="ccbtn cc-tog "+(micMuted?"cc-off":"cc-on");}
function togCam(){camOff=!camOff;if(localStream)localStream.getVideoTracks().forEach(t=>t.enabled=!camOff);const b=document.getElementById("cc-cam");b.textContent=camOff?"&#x1F6AB;":"&#x1F4F7;";b.className="ccbtn cc-tog "+(camOff?"cc-off":"cc-on");document.getElementById("loc-cam-off").classList.toggle("show",camOff);}
function togSpk(){spkOff=!spkOff;const b=document.getElementById("cc-spk");b.textContent=spkOff?"&#x1F507;":"&#x1F50A;";b.className="ccbtn cc-tog "+(spkOff?"cc-off":"cc-on");toast(spkOff?"Speaker off":"Speaker on",1500);}
async function checkIncCall(){
  if(pc)return;
  try{const r=await fetch("/api/call/incoming");const d=await r.json();
    if(d.call&&(!incCallInfo||incCallInfo.call_id!==d.call.call_id)){
      incCallInfo=d.call;
      const c=allUsers.find(u=>u.uid===d.call.from)||{username:"Seseorang",avatar:"",uid:d.call.from};
      document.getElementById("inc-av").innerHTML=mkAv(c,52);
      document.getElementById("inc-name").textContent=c.username;
      document.getElementById("inc-type").textContent=d.call.call_type==="video"?"Video Call Masuk":"Panggilan Masuk";
      document.getElementById("inc-call").classList.add("show");
      setTimeout(()=>{if(incCallInfo&&incCallInfo.call_id===d.call.call_id)rejectCall();},30000);
    }
  }catch(e){}
}

// ========================
// AI ASSISTANT
// ========================
function openAI(){document.getElementById("ai-drw").classList.add("open");navPush({type:"ai"});setTimeout(()=>document.getElementById("ai-ta").focus(),300);}
function closeAI(){document.getElementById("ai-drw").classList.remove("open");}
function aiKey(e){if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();aiSendFromInput();}}
function aiResize(el){el.style.height="auto";el.style.height=Math.min(el.scrollHeight,96)+"px";}
async function aiSendFromInput(){const inp=document.getElementById("ai-ta");const t=inp.value.trim();if(!t)return;inp.value="";inp.style.height="auto";await sendAI(t);}
async function sendAI(text){
  if(!text)return;
  document.getElementById("ai-chips").style.display="none";
  const box=document.getElementById("ai-msgs");
  const ud=document.createElement("div");ud.className="ai-msg usr";
  ud.innerHTML=`<div class="ai-mav">&#x1F464;</div><div class="ai-bub">${esc(text)}</div>`;
  box.appendChild(ud);
  aiHistory.push({role:"user",content:text});
  const thk=document.createElement("div");thk.className="ai-msg bot";thk.id="ai-thk";
  thk.innerHTML=`<div class="ai-mav">&#x1F916;</div><div class="ai-think"><span></span><span></span><span></span></div>`;
  box.appendChild(thk);box.scrollTop=box.scrollHeight;
  try{
    let sys="Kamu adalah WaClone AI, asisten pintar dalam aplikasi chat WaClone. Jawab dalam Bahasa Indonesia yang natural dan ramah. Gunakan emoji sesekali. Bantu pengguna menulis pesan, menjawab pertanyaan, menerjemahkan, atau memberi saran.";
    if(curFriend)sys+=` Pengguna sedang chat dengan ${curFriend.name}.`;
    const msgs=[];
    for(const m of aiHistory.slice(-14)){if(!msgs.length||msgs[msgs.length-1].role!==m.role)msgs.push({...m});else msgs[msgs.length-1]={role:m.role,content:msgs[msgs.length-1].content+"\n"+m.content};}
    const fi=msgs.findIndex(m=>m.role==="user");
    const final=fi>=0?msgs.slice(fi):[{role:"user",content:text}];
    const res=await fetch("/api/ai/chat",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({system:sys,messages:final})});
    const rd=await res.json();thk.remove();
    let reply=rd.ok?rd.reply:"Maaf, tidak bisa menjawab sekarang. Coba lagi.";
    aiHistory.push({role:"assistant",content:reply});
    const ad=document.createElement("div");ad.className="ai-msg bot";
    const fmt=esc(reply).replace(/\*\*(.*?)\*\*/g,"<strong>$1</strong>").replace(/\*(.*?)\*/g,"<em>$1</em>").replace(/\n\n/g,"<br><br>").replace(/\n/g,"<br>");
    ad.innerHTML=`<div class="ai-mav">&#x1F916;</div><div><div class="ai-bub">${fmt}</div></div>`;
    if(curFriend&&(text.includes("balas")||text.includes("pesan")||text.includes("tulis")||text.includes("kirim"))){
      const btn=document.createElement("button");btn.className="copy2chat";btn.innerHTML="&#x1F4CB; Salin ke chat";btn.style.marginLeft="35px";
      btn.onclick=()=>{document.getElementById("msg-inp").value=reply;onInp(document.getElementById("msg-inp"));closeAI();document.getElementById("msg-inp").focus();toast("Disalin ke chat");};
      ad.querySelector("div").appendChild(btn);
    }
    box.appendChild(ad);box.scrollTop=box.scrollHeight;
  }catch(e){thk.remove();const ed=document.createElement("div");ed.className="ai-msg bot";ed.innerHTML=`<div class="ai-mav">&#x1F916;</div><div class="ai-bub" style="background:rgba(220,38,38,.1);border-color:rgba(220,38,38,.3);color:#fca5a5;">Terjadi kesalahan. Pastikan koneksi internet kamu.</div>`;box.appendChild(ed);box.scrollTop=box.scrollHeight;}
}

// ========================
// INIT
// ========================
buildEmoji();
loadUsers();
setInterval(()=>{loadUsers();checkNotifBadge();checkIncCall();fetch("/api/presence",{method:"POST"}).catch(()=>{});},5000);
document.addEventListener("click",e=>{
  if(!document.getElementById("att-menu").contains(e.target)&&!e.target.closest('[title="Lampiran"]'))document.getElementById("att-menu").classList.remove("open");
  if(!document.getElementById("emoji-pick").contains(e.target)&&!e.target.closest('[title="Emoji"]'))document.getElementById("emoji-pick").classList.remove("open");
});
function checkMob(){const m=window.innerWidth<=680;document.getElementById("back-btn").style.display=m?"flex":"none";if(!m)document.getElementById("sb").classList.remove("gone");}
checkMob();window.addEventListener("resize",checkMob);
window.addEventListener("popstate",e=>{e.preventDefault();goBack();history.pushState(null,"",location.href);});
history.pushState(null,"",location.href);
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
    if user:
        return redirect("/home")
    resp = make_response(AUTH_PAGE)
    resp.headers['Content-Type'] = 'text/html; charset=utf-8'
    return resp

@app.route("/home")
def home():
    user = get_current_user(request)
    if not user: return redirect("/")
    html = main_app_html(user)
    resp = make_response(html)
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
        resp.set_cookie("uid", fu.uid, max_age=30*24*3600, httponly=True, samesite='Lax')
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


# ============================
# AI PROXY (server-side Anthropic call)
# ============================
@app.route("/api/ai/chat", methods=["POST"])
def api_ai_chat():
    user = get_current_user(request)
    if not user: return jsonify({"ok": False, "msg": "Login dulu"})
    data = request.get_json()
    messages = data.get("messages", [])
    system = data.get("system", "Kamu adalah WaClone AI, asisten pintar. Jawab dalam Bahasa Indonesia yang ramah.")
    if not messages:
        return jsonify({"ok": False, "msg": "Pesan kosong"})
    try:
        import urllib.request, json as _json
        payload = _json.dumps({
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 1024,
            "system": system,
            "messages": messages
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "anthropic-version": "2023-06-01",
                "x-api-key": os.environ.get("ANTHROPIC_API_KEY", "")
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = _json.loads(resp.read().decode("utf-8"))
            reply = result.get("content", [{}])[0].get("text", "Maaf, tidak bisa menjawab.")
            return jsonify({"ok": True, "reply": reply})
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8")
        print("AI proxy error:", err_body, file=sys.stderr)
        return jsonify({"ok": False, "msg": "AI error: " + err_body[:200]})
    except Exception as e:
        print("AI proxy exception:", e, file=sys.stderr)
        return jsonify({"ok": False, "msg": str(e)})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)