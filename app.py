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
# AUTH PAGE - with Google OAuth
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

    <!-- LOGIN -->
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

    <!-- REGISTER -->
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
      <p class="note">Dengan mendaftar kamu menyetujui syarat & ketentuan penggunaan WaClone.</p>
    </div>
  </div>
</div>
<div class="toast" id="toast"></div>

<!-- Firebase SDK untuk Google OAuth -->
<script src="https://www.gstatic.com/firebasejs/10.12.0/firebase-app-compat.js"></script>
<script src="https://www.gstatic.com/firebasejs/10.12.0/firebase-auth-compat.js"></script>
<script>
let fbApp = null, fbAuth = null, fbInitialized = false;

async function ensureFirebase(){
  if(fbInitialized) return !!fbAuth;
  fbInitialized = true;
  try{
    const r = await fetch('/firebase_config');
    const cfg = await r.json();
    if(!cfg.apiKey){ console.warn('No Firebase apiKey'); return false; }
    if(!firebase.apps.length){
      fbApp = firebase.initializeApp(cfg);
    } else {
      fbApp = firebase.app();
    }
    fbAuth = firebase.auth();
    return true;
  }catch(e){
    console.error('Firebase init failed:', e);
    fbInitialized = false; // allow retry
    return false;
  }
}

// Pre-init on page load for faster Google login
ensureFirebase();

function sw(t){
  document.querySelectorAll('.tab').forEach(e=>e.classList.remove('active'));
  document.querySelectorAll('.pf').forEach(e=>e.classList.remove('active'));
  document.getElementById(t+'-p').classList.add('active');
  document.querySelectorAll('.tab')[t==='login'?0:1].classList.add('active');
  document.getElementById('le2').textContent='';
  document.getElementById('re2').textContent='';
}
function toast(m,d=3000){const t=document.getElementById('toast');t.textContent=m;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),d);}
function togglePw(id,el){const i=document.getElementById(id);i.type=i.type==='password'?'text':'password';el.textContent=i.type==='password'?'ðŸ‘ï¸':'ðŸ™ˆ';}
function setLoading(btn,loading){const b=document.getElementById(btn);if(loading){b.disabled=true;b.innerHTML='<span class="spin"></span>';}else{b.disabled=false;b.textContent=btn==='lbtn'?'Masuk â†’':'Daftar â†’';}}

async function doLogin(){
  const email=document.getElementById('le').value.trim(), pass=document.getElementById('lp').value;
  const err=document.getElementById('le2');
  if(!email||!pass){err.textContent='Isi semua field!';return;}
  setLoading('lbtn',true);
  const fd=new FormData();fd.append('email',email);fd.append('password',pass);
  const r=await fetch('/login',{method:'POST',body:fd});
  const d=await r.json();setLoading('lbtn',false);
  if(d.ok){toast('Login berhasil! ðŸŽ‰');setTimeout(()=>location.href='/home',700);}
  else err.textContent=d.msg||'Login gagal';
}

async function doReg(){
  const u=document.getElementById('ru').value.trim(),e=document.getElementById('re').value.trim(),p=document.getElementById('rp').value;
  const err=document.getElementById('re2');
  if(!u||!e||!p){err.textContent='Isi semua field!';return;}
  if(p.length<6){err.textContent='Password minimal 6 karakter';return;}
  if(!/^[a-zA-Z0-9_]+$/.test(u)){err.textContent='Username hanya huruf, angka, dan underscore';return;}
  setLoading('rbtn',true);
  const fd=new FormData();fd.append('username',u);fd.append('email',e);fd.append('password',p);
  const r=await fetch('/register',{method:'POST',body:fd});
  const d=await r.json();setLoading('rbtn',false);
  if(d.ok){toast('Registrasi berhasil! ðŸŽ‰');setTimeout(()=>location.href='/home',700);}
  else err.textContent=d.msg||'Registrasi gagal';
}

async function loginGoogle(){
  const errEl = document.getElementById('le2') || document.getElementById('re2');
  // Pastikan Firebase terinisialisasi dulu
  const ok = await ensureFirebase();
  if(!ok || !fbAuth){
    if(errEl) errEl.textContent = 'Google login tidak bisa dimuat, coba refresh halaman';
    return;
  }
  try{
    const provider = new firebase.auth.GoogleAuthProvider();
    provider.addScope('email');
    provider.addScope('profile');
    const result = await fbAuth.signInWithPopup(provider);
    const idToken = await result.user.getIdToken();
    // Tampilkan loading
    document.querySelectorAll('.gbtn').forEach(b=>{b.disabled=true;b.innerHTML='<span class="spin"></span> Memproses...';});
    const r = await fetch('/google_auth',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id_token:idToken})});
    const d = await r.json();
    document.querySelectorAll('.gbtn').forEach(b=>{b.disabled=false;b.innerHTML='<svg viewBox="0 0 48 48" style="width:22px;height:22px;flex-shrink:0"><path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z"/><path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z"/><path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z"/><path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.18 1.48-4.97 2.36-8.16 2.36-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z"/></svg> Lanjutkan dengan Google';});
    if(d.ok){toast('Login Google berhasil! ðŸŽ‰');setTimeout(()=>location.href='/home',700);}
    else if(errEl) errEl.textContent = d.msg||'Google login gagal';
  }catch(e){
    document.querySelectorAll('.gbtn').forEach(b=>{b.disabled=false;});
    const msg = e.code==='auth/popup-closed-by-user' ? 'Login dibatalkan' :
                e.code==='auth/popup-blocked' ? 'Popup diblokir browser, izinkan popup untuk situs ini' :
                e.code==='auth/network-request-failed' ? 'Tidak ada koneksi internet' :
                e.message || 'Google login gagal';
    if(errEl) errEl.textContent = msg;
    else toast(msg, 3000, true);
  }
}
</script>
</body>
</html>"""

# ===============================
# MAIN APP HTML - Single template, multiple unique placeholders
# ===============================
MAIN_HTML = r"""<!DOCTYPE html>
<html>
<head>
<title>WaClone</title>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Nunito:wght@400;600;700;800;900&display=swap" rel="stylesheet">
<style>
:root{
  --g:#00a884;--dk:#111b21;--pn:#202c33;--bo:#005c4b;--bi:#202c33;
  --bd:#2a3942;--tx:#e9edef;--st:#8696a0;--hv:#2a3942;--rd:#f15c6d;--bl:#53bdeb;
}
*{margin:0;padding:0;box-sizing:border-box;}
body{font-family:'Nunito',sans-serif;background:var(--dk);color:var(--tx);height:100vh;overflow:hidden;display:flex;}
::-webkit-scrollbar{width:5px;}::-webkit-scrollbar-thumb{background:var(--bd);border-radius:3px;}
input,textarea{outline:none;border:none;background:var(--pn);color:var(--tx);font-family:'Nunito',sans-serif;}
button{cursor:pointer;font-family:'Nunito',sans-serif;}

/* SIDEBAR */
.sb{width:380px;min-width:340px;background:var(--pn);display:flex;flex-direction:column;border-right:1px solid var(--bd);}
.sbh{padding:10px 16px;display:flex;align-items:center;gap:10px;height:62px;border-bottom:1px solid var(--bd);}
.av{width:42px;height:42px;border-radius:50%;object-fit:cover;background:var(--g);display:flex;align-items:center;justify-content:center;font-weight:900;font-size:18px;color:#fff;cursor:pointer;flex-shrink:0;overflow:hidden;}
.av img{width:100%;height:100%;object-fit:cover;}
.sbh h2{font-size:18px;font-weight:900;flex:1;}
.ib{width:40px;height:40px;border:none;background:transparent;color:var(--st);border-radius:50%;display:flex;align-items:center;justify-content:center;transition:.2s;position:relative;}
.ib:hover{background:var(--hv);color:var(--tx);}
.bge{position:absolute;top:4px;right:4px;background:var(--rd);color:#fff;border-radius:50%;width:17px;height:17px;font-size:10px;font-weight:900;display:flex;align-items:center;justify-content:center;}
.sbtabs{display:flex;border-bottom:1px solid var(--bd);}
.stab{flex:1;padding:13px;text-align:center;font-size:13px;font-weight:800;color:var(--st);cursor:pointer;border-bottom:2.5px solid transparent;transition:.2s;}
.stab.active{color:var(--g);border-bottom-color:var(--g);}
.srch{padding:8px 12px;}
.srch input{width:100%;padding:9px 16px 9px 40px;border-radius:10px;background:var(--dk);font-size:14px;}
.swp{position:relative;}
.swp svg{position:absolute;left:12px;top:50%;transform:translateY(-50%);color:var(--st);}
.cl{flex:1;overflow-y:auto;}
.ci{display:flex;align-items:center;gap:12px;padding:10px 16px;cursor:pointer;border-bottom:1px solid var(--bd);transition:.15s;}
.ci:hover,.ci.active{background:var(--hv);}
.cav{width:50px;height:50px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-weight:900;font-size:20px;color:#fff;flex-shrink:0;position:relative;overflow:hidden;}
.cav img{width:50px;height:50px;border-radius:50%;object-fit:cover;}
.odd{position:absolute;bottom:2px;right:2px;width:13px;height:13px;background:#44c56a;border-radius:50%;border:2.5px solid var(--pn);}
.cn{font-weight:800;font-size:15px;}
.cp{font-size:13px;color:var(--st);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px;}
.cm{display:flex;flex-direction:column;align-items:flex-end;gap:4px;}
.ct{font-size:11px;color:var(--st);}
.ub{background:var(--g);color:#fff;border-radius:50%;min-width:20px;height:20px;font-size:11px;font-weight:900;display:flex;align-items:center;justify-content:center;padding:0 4px;}

/* MAIN */
.main{flex:1;display:flex;flex-direction:column;overflow:hidden;position:relative;}
.nc{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;color:var(--st);}
.nc svg{opacity:.15;margin-bottom:20px;}
.nc h2{font-size:26px;font-weight:900;color:var(--tx);margin-bottom:6px;}

/* CHAT HEADER */
.ch{height:62px;background:var(--pn);display:flex;align-items:center;gap:12px;padding:0 12px 0 16px;border-bottom:1px solid var(--bd);flex-shrink:0;}
.chi{flex:1;cursor:pointer;}
.chi h3{font-weight:900;font-size:16px;}
.chi p{font-size:12px;color:var(--g);}
.ch-ib{width:42px;height:42px;border-radius:50%;border:none;background:transparent;color:var(--st);display:flex;align-items:center;justify-content:center;transition:.2s;flex-shrink:0;}
.ch-ib:hover{background:var(--hv);color:var(--tx);}

/* MESSAGES */
.ma{flex:1;overflow-y:auto;padding:16px 40px;display:flex;flex-direction:column;gap:2px;
  background-color:var(--dk);
  background-image:url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='%23ffffff' fill-opacity='0.015'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/svg%3E");}
.mr{display:flex;margin:2px 0;position:relative;align-items:flex-end;gap:6px;}
.mr:hover .msg-actions{opacity:1;}
.mr.out{justify-content:flex-end;}
.mr.in{justify-content:flex-start;}

/* Message action buttons (reply, etc) */
.msg-actions{opacity:0;transition:opacity .15s;display:flex;gap:4px;align-items:center;flex-shrink:0;}
.mr.out .msg-actions{order:-1;}
.msg-act-btn{width:28px;height:28px;border-radius:50%;background:var(--pn);border:1px solid var(--bd);color:var(--st);font-size:13px;display:flex;align-items:center;justify-content:center;transition:.15s;}
.msg-act-btn:hover{background:var(--hv);color:var(--tx);}

.bbl{max-width:62%;padding:8px 12px 5px;border-radius:12px;font-size:14.5px;line-height:1.5;word-break:break-word;box-shadow:0 1px 3px rgba(0,0,0,.3);position:relative;}
.mr.out .bbl{background:var(--bo);border-bottom-right-radius:3px;}
.mr.in .bbl{background:var(--bi);border-bottom-left-radius:3px;}
.bt{font-size:11px;color:rgba(255,255,255,.45);text-align:right;margin-top:3px;display:flex;align-items:center;justify-content:flex-end;gap:3px;}
.si{font-size:12px;}
.si.read{color:var(--bl);}
.bbl img{max-width:260px;border-radius:8px;display:block;margin-bottom:3px;cursor:pointer;}
.bbl audio{width:220px;margin-bottom:3px;}
.bbl video{max-width:260px;border-radius:8px;display:block;margin-bottom:3px;}
.bbl a{color:var(--bl);text-decoration:none;font-size:13px;}
.dd{text-align:center;color:var(--st);font-size:12px;margin:10px 0;}
.dd span{background:rgba(255,255,255,.08);padding:4px 12px;border-radius:20px;}

/* Reply quote in bubble */
.rq{background:rgba(255,255,255,.08);border-left:3px solid var(--g);border-radius:6px;padding:6px 8px;margin-bottom:6px;font-size:12px;cursor:pointer;}
.rq .rn{font-weight:800;color:var(--g);font-size:11px;margin-bottom:2px;}
.rq .rt{color:var(--st);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:200px;}

/* Typing indicator */
.typing-ind{display:none;align-items:center;gap:8px;padding:8px 16px 4px;}
.typing-ind.show{display:flex;}
.typing-dots{display:flex;gap:4px;align-items:center;}
.typing-dots span{width:7px;height:7px;background:var(--st);border-radius:50%;animation:tdot 1.4s infinite;}
.typing-dots span:nth-child(2){animation-delay:.2s;}
.typing-dots span:nth-child(3){animation-delay:.4s;}
@keyframes tdot{0%,60%,100%{transform:translateY(0);}30%{transform:translateY(-6px);}}
.typing-nm{font-size:12px;color:var(--st);}

/* Context menu */
.ctx{position:fixed;background:var(--pn);border:1px solid var(--bd);border-radius:14px;box-shadow:0 8px 30px rgba(0,0,0,.6);z-index:500;min-width:180px;overflow:hidden;display:none;}
.ctx-item{padding:12px 18px;font-size:14px;font-weight:700;cursor:pointer;display:flex;align-items:center;gap:10px;transition:.15s;}
.ctx-item:hover{background:var(--hv);}
.ctx-item.danger{color:var(--rd);}

/* INPUT BAR */
.ib-wrap{background:var(--pn);padding:8px 12px;display:flex;align-items:flex-end;gap:8px;border-top:1px solid var(--bd);flex-shrink:0;flex-direction:column;}
.reply-bar{width:100%;background:rgba(0,168,132,.1);border-left:3px solid var(--g);border-radius:8px;padding:8px 12px;display:flex;align-items:center;justify-content:space-between;font-size:13px;}
.reply-bar .rn{color:var(--g);font-weight:800;font-size:11px;}
.reply-bar .rt{color:var(--st);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:280px;}
.ib-row{display:flex;align-items:flex-end;gap:8px;width:100%;}
.att-btn{width:40px;height:40px;border-radius:50%;background:transparent;border:none;color:var(--st);display:flex;align-items:center;justify-content:justify-content;justify-content:center;flex-shrink:0;}
.att-btn:hover{color:var(--tx);background:var(--hv);}
.emoji-btn{width:40px;height:40px;border-radius:50%;background:transparent;border:none;color:var(--st);font-size:20px;display:flex;align-items:center;justify-content:center;flex-shrink:0;}
.emoji-btn:hover{color:var(--tx);background:var(--hv);}
.mi{flex:1;padding:11px 16px;border-radius:24px;font-size:15px;background:var(--dk);border:1.5px solid var(--bd);color:var(--tx);transition:.2s;max-height:120px;resize:none;line-height:1.4;}
.mi:focus{border-color:var(--g);}
.send-btn{width:46px;height:46px;border-radius:50%;background:var(--g);border:none;display:flex;align-items:center;justify-content:center;transition:.2s;flex-shrink:0;}
.send-btn:hover{background:#009070;transform:scale(1.05);}
.rec-btn{width:46px;height:46px;border-radius:50%;background:var(--dk);border:1.5px solid var(--bd);display:flex;align-items:center;justify-content:center;flex-shrink:0;color:var(--st);}
.rec-btn.recording{background:var(--rd);border-color:var(--rd);color:#fff;animation:pulse 1s infinite;}
@keyframes pulse{0%,100%{transform:scale(1);}50%{transform:scale(1.08);}}

/* Emoji picker */
.emoji-picker{position:absolute;bottom:80px;right:60px;background:var(--pn);border:1px solid var(--bd);border-radius:16px;padding:12px;box-shadow:0 8px 30px rgba(0,0,0,.5);z-index:200;display:none;width:280px;}
.emoji-picker.open{display:block;}
.emoji-grid{display:flex;flex-wrap:wrap;gap:4px;}
.emoji-item{font-size:22px;cursor:pointer;padding:4px;border-radius:8px;transition:.15s;line-height:1;}
.emoji-item:hover{background:var(--hv);}

/* Attachment menu */
.att-menu{position:absolute;bottom:80px;left:12px;background:var(--pn);border:1px solid var(--bd);border-radius:16px;padding:12px;box-shadow:0 8px 30px rgba(0,0,0,.5);z-index:200;display:none;flex-wrap:wrap;gap:10px;width:220px;}
.att-menu.open{display:flex;}
.att-opt{display:flex;flex-direction:column;align-items:center;gap:6px;cursor:pointer;width:calc(33% - 8px);}
.att-ic{width:48px;height:48px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:22px;}
.att-lbl{font-size:11px;font-weight:700;color:var(--st);}

/* OVERLAYS / PANELS */
.ov{position:fixed;inset:0;background:rgba(0,0,0,.65);z-index:300;display:none;align-items:center;justify-content:center;}
.ov.open{display:flex;}
.pb{background:var(--pn);border-radius:20px;width:400px;max-height:85vh;overflow-y:auto;border:1px solid var(--bd);box-shadow:0 20px 60px rgba(0,0,0,.6);}
.ph{padding:20px 24px 0;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;background:var(--pn);z-index:1;padding-bottom:10px;border-bottom:1px solid var(--bd);}
.ph h2{font-size:20px;font-weight:900;}
.xb{background:var(--hv);border:none;color:var(--st);width:32px;height:32px;border-radius:50%;font-size:18px;display:flex;align-items:center;justify-content:center;}
.xb:hover{color:var(--tx);}
.pbd{padding:20px 24px;}

/* Profile */
.pav-w{text-align:center;margin-bottom:20px;position:relative;display:inline-block;left:50%;transform:translateX(-50%);}
.pav-big{width:110px;height:110px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-size:44px;font-weight:900;color:#fff;overflow:hidden;cursor:pointer;border:3px solid var(--bd);transition:.2s;}
.pav-big:hover{border-color:var(--g);}
.pav-big img{width:100%;height:100%;object-fit:cover;}
.pav-edit{position:absolute;bottom:4px;right:0;background:var(--g);width:32px;height:32px;border-radius:50%;display:flex;align-items:center;justify-content:center;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.4);font-size:14px;}
.pnm{font-size:22px;font-weight:900;text-align:center;}
.pem{color:var(--st);font-size:14px;text-align:center;margin-top:4px;}
.ef{margin-bottom:14px;}
.ef label{font-size:11px;font-weight:800;color:var(--g);text-transform:uppercase;letter-spacing:.6px;display:block;margin-bottom:6px;}
.ef input,.ef textarea{width:100%;padding:10px 14px;border-radius:10px;background:var(--dk);border:1.5px solid var(--bd);color:var(--tx);font-size:14px;font-family:'Nunito',sans-serif;}
.ef textarea{resize:none;height:80px;line-height:1.5;}
.ef input:focus,.ef textarea:focus{border-color:var(--g);}
.sbtn{width:100%;padding:13px;background:var(--g);color:#fff;border:none;border-radius:12px;font-size:15px;font-weight:800;margin-top:8px;transition:.2s;}
.sbtn:hover{background:#009070;}
.lbtn2{width:100%;padding:12px;background:transparent;color:var(--rd);border:1.5px solid var(--rd);border-radius:12px;font-size:15px;font-weight:800;margin-top:10px;transition:.2s;}
.lbtn2:hover{background:var(--rd);color:#fff;}

/* Notifications */
.ni{display:flex;gap:12px;align-items:center;padding:12px 0;border-bottom:1px solid var(--bd);cursor:pointer;}
.ni:last-child{border-bottom:none;}
.nav2{width:44px;height:44px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-weight:900;font-size:18px;color:#fff;flex-shrink:0;overflow:hidden;}
.nav2 img{width:44px;height:44px;object-fit:cover;}
.nd{flex:1;}
.nn{font-weight:800;font-size:14px;}
.nm{font-size:13px;color:var(--st);margin-top:2px;}
.nt{font-size:11px;color:var(--st);}
.ndot{width:10px;height:10px;background:var(--g);border-radius:50%;flex-shrink:0;}

/* Status */
.st-my{background:var(--dk);border-radius:14px;padding:16px;border:2px dashed var(--bd);cursor:pointer;text-align:center;margin-bottom:16px;transition:.2s;}
.st-my:hover{border-color:var(--g);}
.st-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;}
.st-card{background:var(--dk);border-radius:14px;padding:14px;border:1px solid var(--bd);cursor:pointer;position:relative;overflow:hidden;transition:.2s;}
.st-card:hover{border-color:var(--g);transform:translateY(-1px);}
.st-av{width:48px;height:48px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-weight:900;font-size:20px;color:#fff;margin-bottom:10px;border:3px solid var(--g);overflow:hidden;}
.st-av img{width:48px;height:48px;object-fit:cover;}
.st-nm{font-weight:800;font-size:13px;}
.st-tm{font-size:11px;color:var(--st);}
.st-oi{position:absolute;top:10px;right:10px;width:10px;height:10px;background:#44c56a;border-radius:50%;}
.st-thumb{width:100%;height:70px;border-radius:8px;object-fit:cover;margin-bottom:8px;background:var(--bd);}

/* Create Status */
.cst-opts{display:flex;flex-direction:column;gap:10px;}
.cst-opt{display:flex;align-items:center;gap:14px;padding:14px;background:var(--dk);border-radius:12px;border:1.5px solid var(--bd);cursor:pointer;transition:.2s;}
.cst-opt:hover{border-color:var(--g);background:#1a2328;}
.cst-ic{width:48px;height:48px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:22px;flex-shrink:0;}
.cst-lbl{font-weight:800;font-size:15px;}
.cst-sub{font-size:12px;color:var(--st);}
.char-count{font-size:11px;color:var(--st);text-align:right;margin-top:4px;}

/* Status viewer */
.stv{background:#000;width:100%;max-width:480px;border-radius:20px;overflow:hidden;position:relative;}
.stv-bar{display:flex;gap:4px;padding:12px 12px 8px;}
.stv-seg{flex:1;height:3px;background:rgba(255,255,255,.3);border-radius:3px;overflow:hidden;}
.stv-fill{height:100%;background:#fff;width:0%;transition:width linear;}
.stv-head{display:flex;align-items:center;gap:10px;padding:8px 16px;}
.stv-av{width:36px;height:36px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-weight:900;color:#fff;font-size:15px;overflow:hidden;}
.stv-av img{width:100%;height:100%;object-fit:cover;}
.stv-nm{font-weight:800;font-size:14px;}
.stv-tm{font-size:11px;color:rgba(255,255,255,.6);}
.stv-cnt{min-height:220px;display:flex;align-items:center;justify-content:center;padding:20px;}
.stv-txt{font-size:24px;font-weight:800;text-align:center;color:#fff;padding:20px;text-shadow:0 2px 8px rgba(0,0,0,.5);}
.stv-img{max-width:100%;max-height:420px;object-fit:contain;border-radius:4px;}

/* Camera */
.cam-wrap{position:relative;background:#000;border-radius:16px;overflow:hidden;}
.cam-wrap video{width:100%;border-radius:16px;display:block;max-height:300px;object-fit:cover;}
.cam-controls{display:flex;gap:12px;justify-content:center;margin-top:16px;}
.cam-btn{width:56px;height:56px;border-radius:50%;border:none;display:flex;align-items:center;justify-content:center;font-size:22px;cursor:pointer;transition:.2s;}
.cam-snap{background:var(--g);}
.cam-snap:hover{background:#009070;}
.cam-cancel{background:var(--rd);}

/* Call UI */
.call-ui{position:fixed;inset:0;background:rgba(0,0,0,.94);z-index:900;display:none;flex-direction:column;align-items:center;justify-content:center;gap:20px;}
.call-ui.active{display:flex;}
.call-vids{display:flex;gap:12px;align-items:center;justify-content:center;width:100%;max-width:900px;}
.call-vids video{border-radius:16px;background:#1a1a2e;}
#remoteVid{width:70%;max-height:70vh;object-fit:cover;}
#localVid{width:28%;max-height:40vh;object-fit:cover;border:2px solid var(--g);}
.call-audio-ui{text-align:center;}
.call-av{width:120px;height:120px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-size:50px;font-weight:900;color:#fff;margin:0 auto 16px;overflow:hidden;}
.call-av img{width:100%;height:100%;object-fit:cover;}
.call-nm{font-size:28px;font-weight:900;color:#fff;}
.call-st{font-size:16px;color:rgba(255,255,255,.6);margin-top:6px;}
.call-timer{font-size:18px;color:var(--g);font-weight:800;margin-top:10px;}
.call-actions{display:flex;gap:20px;margin-top:24px;}
.call-act{width:64px;height:64px;border-radius:50%;border:none;display:flex;align-items:center;justify-content:center;font-size:24px;cursor:pointer;transition:.2s;}
.call-end{background:var(--rd);}
.call-end:hover{background:#d94455;transform:scale(1.08);}
.call-tog{background:#2a2a3e;}
.call-tog:hover{background:#3a3a5e;}
.call-tog.active{background:var(--g);}
.inc-call{position:fixed;bottom:30px;right:30px;background:var(--pn);border:1px solid var(--bd);border-radius:20px;padding:20px;z-index:950;box-shadow:0 20px 60px rgba(0,0,0,.6);min-width:280px;display:none;animation:slideIn .3s ease;}
.inc-call.show{display:block;}
@keyframes slideIn{from{transform:translateX(100%);opacity:0;}to{transform:none;opacity:1;}}
.inc-av{width:60px;height:60px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-size:24px;font-weight:900;color:#fff;margin:0 auto 10px;overflow:hidden;}
.inc-av img{width:100%;height:100%;object-fit:cover;}
.inc-nm{font-size:18px;font-weight:900;text-align:center;margin-bottom:4px;}
.inc-st{font-size:13px;color:var(--st);text-align:center;margin-bottom:16px;}
.inc-acts{display:flex;gap:10px;}
.inc-ans{flex:1;padding:12px;background:var(--g);color:#fff;border:none;border-radius:12px;font-size:15px;font-weight:800;transition:.2s;}
.inc-ans:hover{background:#009070;}
.inc-dec{flex:1;padding:12px;background:var(--rd);color:#fff;border:none;border-radius:12px;font-size:15px;font-weight:800;}

/* Forward modal */
.fw-list{display:flex;flex-direction:column;gap:8px;max-height:300px;overflow-y:auto;}
.fw-item{display:flex;align-items:center;gap:12px;padding:10px 14px;background:var(--dk);border-radius:12px;cursor:pointer;border:1.5px solid var(--bd);transition:.15s;}
.fw-item:hover,.fw-item.sel{border-color:var(--g);}
.fw-av{width:40px;height:40px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-weight:900;font-size:16px;color:#fff;flex-shrink:0;overflow:hidden;}
.fw-av img{width:100%;height:100%;object-fit:cover;}

/* Media viewer */
.img-pv{max-width:90vw;max-height:90vh;border-radius:8px;object-fit:contain;}

/* Toast */
.toast{position:fixed;bottom:30px;left:50%;transform:translateX(-50%);background:var(--pn);color:var(--tx);padding:12px 24px;border-radius:12px;border-left:4px solid var(--g);z-index:9999;box-shadow:0 8px 32px rgba(0,0,0,.5);opacity:0;transition:opacity .3s;pointer-events:none;font-weight:700;white-space:nowrap;}
.toast.show{opacity:1;}
.toast.err{border-left-color:var(--rd);}

/* Upload progress */
.upload-bar{display:none;width:100%;height:3px;background:var(--bd);border-radius:3px;overflow:hidden;}
.upload-bar.show{display:block;}
.upload-prog{height:100%;background:var(--g);width:0%;transition:width .3s;border-radius:3px;}

/* Responsive mobile */
@media(max-width:700px){
  .sb{width:100%;position:absolute;z-index:10;height:100vh;display:var(--sb-display,flex);}
  .main{position:absolute;width:100%;z-index:10;height:100vh;display:var(--main-display,none);}
  body{--sb-display:flex;--main-display:none;}
  body.chat-open{--sb-display:none;--main-display:flex;}
  .back-btn{display:flex!important;}
}
.back-btn{display:none;width:40px;height:40px;border-radius:50%;border:none;background:transparent;color:var(--st);align-items:center;justify-content:center;font-size:20px;}
</style>
</head>
<body>

<!-- SIDEBAR -->
<div class="sb">
  <div class="sbh">
    <div class="av" onclick="openPanel('prof-ov')" id="my-av">__SIDEBAR_AV__</div>
    <h2>WaClone</h2>
    <button class="ib" onclick="openPanel('stat-ov');setTimeout(loadStatuses,100)" title="Status">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 8v4l3 3"/></svg>
    </button>
    <button class="ib" onclick="openNotif()" title="Notifikasi">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M12 22c1.1 0 2-.9 2-2h-4c0 1.1.9 2 2 2zm6-6v-5c0-3.07-1.63-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 1.5v.68C7.64 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z"/></svg>
      <span class="bge" id="nb" style="display:none">0</span>
    </button>
  </div>
  <div class="sbtabs">
    <div class="stab active" onclick="swTab('chats')" id="tab-chats">ðŸ’¬ Chat</div>
    <div class="stab" onclick="swTab('contacts')" id="tab-contacts">ðŸ‘¥ Kontak</div>
  </div>
  <div class="srch"><div class="swp">
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M15.5 14h-.79l-.28-.27A6.471 6.471 0 0016 9.5 6.5 6.5 0 109.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/></svg>
    <input type="text" id="search-input" placeholder="Cari pengguna..." oninput="filterContacts(this.value)">
  </div></div>
  <div class="cl" id="contact-list"><div style="padding:20px;text-align:center;color:var(--st);">Memuat...</div></div>
</div>

<!-- MAIN -->
<div class="main" id="main">
  <div class="nc" id="no-chat">
    <svg width="100" height="100" viewBox="0 0 24 24" fill="currentColor"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/></svg>
    <h2>WaClone</h2>
    <p>Pilih kontak untuk mulai chat</p>
  </div>
  <div id="chat-area" style="display:none;flex-direction:column;height:100%;position:relative;">
    <div class="ch" id="chat-hdr"></div>
    <div class="ma" id="msg-area" oncontextmenu="return false;"></div>
    <div class="typing-ind" id="typing-ind">
      <div class="typing-dots"><span></span><span></span><span></span></div>
      <span class="typing-nm" id="typing-nm"></span>
    </div>
    <!-- Attachment Menu -->
    <div class="att-menu" id="att-menu">
      <div class="att-opt" onclick="triggerFile('photo')">
        <div class="att-ic" style="background:#1a56db22;">ðŸ“·</div><span class="att-lbl">Foto/Video</span>
      </div>
      <div class="att-opt" onclick="triggerFile('doc')">
        <div class="att-ic" style="background:#7c3aed22;">ðŸ“„</div><span class="att-lbl">Dokumen</span>
      </div>
      <div class="att-opt" onclick="openCameraForChat()">
        <div class="att-ic" style="background:#05966922;">ðŸ“¸</div><span class="att-lbl">Kamera</span>
      </div>
    </div>
    <!-- Emoji Picker -->
    <div class="emoji-picker" id="emoji-picker">
      <div class="emoji-grid" id="emoji-grid"></div>
    </div>
    <!-- Upload Progress -->
    <div class="upload-bar" id="upload-bar"><div class="upload-prog" id="upload-prog"></div></div>
    <!-- Input Bar -->
    <div class="ib-wrap" id="input-wrap">
      <div class="reply-bar" id="reply-bar" style="display:none;">
        <div><div class="rn" id="reply-name"></div><div class="rt" id="reply-text"></div></div>
        <button class="ib" onclick="cancelReply()" style="width:28px;height:28px;font-size:14px;">âœ•</button>
      </div>
      <div class="ib-row">
        <button class="att-btn" onclick="toggleAttMenu()" title="Lampiran">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M16.5 6v11.5c0 2.21-1.79 4-4 4s-4-1.79-4-4V5c0-1.38 1.12-2.5 2.5-2.5s2.5 1.12 2.5 2.5v10.5c0 .55-.45 1-1 1s-1-.45-1-1V6H10v9.5c0 1.38 1.12 2.5 2.5 2.5s2.5-1.12 2.5-2.5V5c0-2.21-1.79-4-4-4S7 2.79 7 5v12.5c0 3.04 2.46 5.5 5.5 5.5s5.5-2.46 5.5-5.5V6h-1.5z"/></svg>
        </button>
        <input type="file" id="file-photo" style="display:none" accept="image/*,video/*" onchange="handleFileUpload(this)">
        <input type="file" id="file-doc" style="display:none" accept=".pdf,.txt,.doc,.docx,.xls,.xlsx,.zip,.rar" onchange="handleFileUpload(this)">
        <button class="emoji-btn" onclick="toggleEmoji()" title="Emoji">ðŸ˜Š</button>
        <textarea class="mi" id="msg-input" rows="1" placeholder="Ketik pesan..." onkeydown="handleKey(event)" oninput="autoResize(this);sendTyping();"></textarea>
        <button class="rec-btn" id="rec-btn" onmousedown="startRecording()" onmouseup="stopRecording()" ontouchstart="startRecording(event)" ontouchend="stopRecording()" title="Tahan untuk rekam suara">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor"><path d="M12 14c1.66 0 2.99-1.34 2.99-3L15 5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm5.3-3c0 3-2.54 5.1-5.3 5.1S6.7 14 6.7 11H5c0 3.41 2.72 6.23 6 6.72V21h2v-3.28c3.28-.48 6-3.3 6-6.72h-1.7z"/></svg>
        </button>
        <button class="send-btn" onclick="sendMsg()">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="white"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
        </button>
      </div>
    </div>
  </div>
</div>

<!-- Context Menu -->
<div class="ctx" id="ctx-menu">
  <div class="ctx-item" onclick="ctxReply()">â†©ï¸ Balas</div>
  <div class="ctx-item" onclick="ctxCopy()">ðŸ“‹ Salin</div>
  <div class="ctx-item" onclick="ctxForward()">â†ªï¸ Teruskan</div>
  <div class="ctx-item danger" onclick="ctxDelete()">ðŸ—‘ï¸ Hapus</div>
</div>

<!-- PROFILE PANEL -->
<div class="ov" id="prof-ov">
  <div class="pb">
    <div class="ph"><h2>ðŸ‘¤ Profil Saya</h2><button class="xb" onclick="closePanel('prof-ov')">âœ•</button></div>
    <div class="pbd">
      <div class="pav-w">
        <div class="pav-big" id="pav-big" onclick="document.getElementById('avatar-file').click()" title="Ganti foto">__PROFILE_AV__</div>
        <div class="pav-edit" onclick="document.getElementById('avatar-file').click()">ðŸ“·</div>
        <input type="file" id="avatar-file" style="display:none" accept="image/*,image/heic,image/heif" onchange="uploadAvatar(this)">
      </div>
      <div class="pnm" id="prof-name">__USERNAME__</div>
      <div class="pem">__EMAIL__</div>
      <div style="margin-top:20px;">
        <div class="ef"><label>Username</label><input id="edit-u" value="__USERNAME__" placeholder="username baru"></div>
        <div class="ef"><label>Bio / Status</label><textarea id="edit-b">__BIO__</textarea></div>
      </div>
      <button class="sbtn" onclick="saveProfile()">ðŸ’¾ Simpan Profil</button>
      <button class="lbtn2" onclick="doLogout()">ðŸšª Logout</button>
    </div>
  </div>
</div>

<!-- NOTIFICATIONS PANEL -->
<div class="ov" id="notif-ov">
  <div class="pb">
    <div class="ph"><h2>ðŸ”” Notifikasi</h2><button class="xb" onclick="closePanel('notif-ov');markNotifsRead()">âœ•</button></div>
    <div class="pbd" id="notif-list"><div style="text-align:center;color:var(--st);padding:20px;">Tidak ada notifikasi</div></div>
  </div>
</div>

<!-- STATUS PANEL -->
<div class="ov" id="stat-ov">
  <div class="pb">
    <div class="ph"><h2>ðŸ“Š Status</h2><button class="xb" onclick="closePanel('stat-ov')">âœ•</button></div>
    <div class="pbd">
      <div class="st-my" onclick="openCreateStatus()">
        <div style="font-size:28px;margin-bottom:6px;">âž•</div>
        <div style="font-weight:800;">Buat Status</div>
        <div style="font-size:12px;color:var(--st);">Foto, video, atau teks</div>
      </div>
      <div id="status-list"><div style="text-align:center;color:var(--st);">Memuat status...</div></div>
    </div>
  </div>
</div>

<!-- CREATE STATUS PANEL -->
<div class="ov" id="cstat-ov">
  <div class="pb">
    <div class="ph"><h2>âœï¸ Buat Status</h2><button class="xb" onclick="closePanel('cstat-ov')">âœ•</button></div>
    <div class="pbd">
      <div class="cst-opts">
        <div class="cst-opt" onclick="openTextStatus()">
          <div class="cst-ic" style="background:#2563eb22;">âœï¸</div>
          <div><div class="cst-lbl">Teks</div><div class="cst-sub">Buat status teks</div></div>
        </div>
        <div class="cst-opt" onclick="document.getElementById('stat-photo').click()">
          <div class="cst-ic" style="background:#dc262622;">ðŸ–¼ï¸</div>
          <div><div class="cst-lbl">Foto</div><div class="cst-sub">Upload foto sebagai status</div></div>
        </div>
        <div class="cst-opt" onclick="document.getElementById('stat-video').click()">
          <div class="cst-ic" style="background:#7c3aed22;">ðŸŽ¥</div>
          <div><div class="cst-lbl">Video</div><div class="cst-sub">Upload video sebagai status</div></div>
        </div>
        <div class="cst-opt" onclick="openCameraStatus()">
          <div class="cst-ic" style="background:#05966922;">ðŸ“¸</div>
          <div><div class="cst-lbl">Kamera</div><div class="cst-sub">Foto langsung dari kamera</div></div>
        </div>
      </div>
      <input type="file" id="stat-photo" accept="image/*,image/heic,image/heif" style="display:none" onchange="uploadStatus(this,'image')">
      <input type="file" id="stat-video" accept="video/*" style="display:none" onchange="uploadStatus(this,'video')">
      <div id="text-status-form" style="display:none;margin-top:20px;">
        <div class="ef">
          <label>Teks Status</label>
          <textarea id="stat-txt" placeholder="Tulis status kamu..." style="height:100px;" oninput="document.getElementById('char-cnt').textContent=this.value.length+'/200';" maxlength="200"></textarea>
          <div class="char-count" id="char-cnt">0/200</div>
        </div>
        <button class="sbtn" onclick="postTextStatus()">ðŸ“¤ Posting Status</button>
      </div>
    </div>
  </div>
</div>

<!-- STATUS VIEWER -->
<div class="ov" id="stview-ov" onclick="closePanel('stview-ov')">
  <div class="stv" onclick="event.stopPropagation()">
    <div class="stv-bar" id="stv-bar"></div>
    <div class="stv-head">
      <div class="stv-av" id="stv-av"></div>
      <div>
        <div class="stv-nm" id="stv-nm"></div>
        <div class="stv-tm" id="stv-tm"></div>
      </div>
      <button class="xb" onclick="closePanel('stview-ov');clearStatusTimer()" style="margin-left:auto;">âœ•</button>
    </div>
    <div class="stv-cnt" id="stv-cnt"></div>
  </div>
</div>

<!-- CAMERA PANEL -->
<div class="ov" id="cam-ov">
  <div class="pb" style="width:440px;">
    <div class="ph"><h2>ðŸ“· Kamera</h2><button class="xb" onclick="closeCamera()">âœ•</button></div>
    <div class="pbd">
      <div class="cam-wrap"><video id="cam-vid" autoplay playsinline muted></video></div>
      <canvas id="cam-canvas" style="display:none;width:100%;border-radius:12px;margin-top:10px;"></canvas>
      <div class="cam-controls">
        <button class="cam-btn cam-snap" onclick="snapPhoto()">ðŸ“¸</button>
        <button class="cam-btn" style="background:#2a3942;" onclick="switchCamera()">ðŸ”„</button>
        <button class="cam-btn cam-cancel" onclick="closeCamera()">âœ•</button>
      </div>
      <div id="cam-preview" style="display:none;margin-top:12px;">
        <button class="sbtn" onclick="sendCameraPhoto()">ðŸ“¤ Kirim Foto</button>
      </div>
    </div>
  </div>
</div>

<!-- FORWARD PANEL -->
<div class="ov" id="fw-ov">
  <div class="pb">
    <div class="ph"><h2>â†ªï¸ Teruskan Pesan</h2><button class="xb" onclick="closePanel('fw-ov')">âœ•</button></div>
    <div class="pbd">
      <div class="fw-list" id="fw-list"></div>
      <button class="sbtn" id="fw-send" style="margin-top:16px;display:none;" onclick="doForward()">ðŸ“¤ Kirim</button>
    </div>
  </div>
</div>

<!-- IMAGE FULLSCREEN -->
<div class="ov" id="img-ov" onclick="closePanel('img-ov')">
  <img class="img-pv" id="img-full" src="" alt="preview">
</div>

<!-- CALL UI -->
<div class="call-ui" id="call-ui">
  <div id="call-video-wrap" style="display:none;width:100%;max-width:900px;">
    <div class="call-vids">
      <video id="remoteVid" autoplay playsinline></video>
      <video id="localVid" autoplay playsinline muted></video>
    </div>
  </div>
  <div class="call-audio-ui" id="call-audio-wrap">
    <div class="call-av" id="call-av"></div>
    <div class="call-nm" id="call-nm"></div>
    <div class="call-st" id="call-st">Memanggil...</div>
    <div class="call-timer" id="call-timer" style="display:none;">00:00</div>
  </div>
  <div class="call-actions">
    <button class="call-act call-tog" id="btn-mute" onclick="toggleMute()" title="Mute">ðŸŽ¤</button>
    <button class="call-act call-end" onclick="endCall()" title="Akhiri">ðŸ“µ</button>
    <button class="call-act call-tog" id="btn-cam" onclick="toggleCamera()" title="Kamera" style="display:none;">ðŸ“·</button>
    <button class="call-act call-tog" id="btn-spk" onclick="toggleSpeaker()" title="Speaker">ðŸ”Š</button>
  </div>
</div>

<!-- INCOMING CALL -->
<div class="inc-call" id="inc-call">
  <div class="inc-av" id="inc-av"></div>
  <div class="inc-nm" id="inc-nm"></div>
  <div class="inc-st" id="inc-type"></div>
  <div class="inc-acts">
    <button class="inc-ans" onclick="answerCall()">ðŸ“ž Angkat</button>
    <button class="inc-dec" onclick="rejectCall()">ðŸ“µ Tolak</button>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
// ===== CONSTANTS =====
const ME = {uid:"__UID__", username:"__USERNAME__"};
const STUN = {iceServers:[{urls:"stun:stun.l.google.com:19302"},{urls:"stun:stun1.l.google.com:19302"}]};
const EMOJIS = ['ðŸ˜€','ðŸ˜‚','ðŸ˜','ðŸ¥°','ðŸ˜Ž','ðŸ¤”','ðŸ˜­','ðŸ˜¡','ðŸ‘','ðŸ‘Ž','â¤ï¸','ðŸ”¥','âœ…','â­','ðŸŽ‰','ðŸ™','ðŸ‘','ðŸ’ª','ðŸ˜´','ðŸ¤£','ðŸ˜Š','ðŸ˜˜','ðŸ¤—','ðŸ¥º','ðŸ˜…','ðŸ˜¬','ðŸ¤™','ðŸ’€','ðŸ‘‹','ðŸ«‚','ðŸŒŸ','ðŸ’¯','ðŸŽŠ','ðŸ¤©','ðŸ˜±','ðŸ¤¯','ðŸ«¡','ðŸ¥³','ðŸ˜¤','ðŸ«¶'];

// ===== STATE =====
let allUsers=[], currentFriend=null, pollTimer=null, replyTo=null;
let ctxMsg=null, mediaRec=null, recChunks=[], isRecording=false;
let pc=null, localStream=null, currentCallId=null, callType='audio';
let callTimer=null, callSeconds=0, isMuted=false, isCamOff=false;
let incCallData=null, camStream=null, camFacing='user', camMode='chat';
let statusViewData=null, statusViewIdx=0, statusTimer=null;
let forwardText='', forwardSelectedUid=null;
let typingTimer=null, lastTypingTime=0;

// ===== TOAST =====
function toast(m,d=2500,err=false){
  const t=document.getElementById('toast');
  t.textContent=m;
  t.classList.toggle('err',err);
  t.classList.add('show');
  setTimeout(()=>t.classList.remove('show'),d);
}

// ===== PANELS =====
function openPanel(id){document.getElementById(id).classList.add('open');}
function closePanel(id){document.getElementById(id).classList.remove('open');}
function openNotif(){openPanel('notif-ov');loadNotifications();}

// ===== TABS =====
function swTab(t){
  document.querySelectorAll('.stab').forEach(e=>e.classList.remove('active'));
  document.getElementById('tab-'+t).classList.add('active');
  renderContacts();
}

// ===== TIME FORMAT =====
function fmtTime(ts){
  const d=new Date(ts*1000), now=new Date();
  if(d.toDateString()===now.toDateString()) return d.getHours().toString().padStart(2,'0')+':'+d.getMinutes().toString().padStart(2,'0');
  const diff=Math.floor((now-d)/86400000);
  if(diff===1)return 'Kemarin';
  if(diff<7)return ['Min','Sen','Sel','Rab','Kam','Jum','Sab'][d.getDay()];
  return d.getDate()+'/'+(d.getMonth()+1);
}

// ===== EMOJI PICKER =====
function buildEmojiPicker(){
  const g=document.getElementById('emoji-grid');
  g.innerHTML=EMOJIS.map(e=>`<span class="emoji-item" onclick="insertEmoji('${e}')">${e}</span>`).join('');
}
function toggleEmoji(){
  document.getElementById('att-menu').classList.remove('open');
  const p=document.getElementById('emoji-picker');
  p.classList.toggle('open');
}
function insertEmoji(e){
  const inp=document.getElementById('msg-input');
  const s=inp.selectionStart, end=inp.selectionEnd;
  inp.value=inp.value.substring(0,s)+e+inp.value.substring(end);
  inp.selectionStart=inp.selectionEnd=s+e.length;
  inp.focus();autoResize(inp);
}

// ===== LOAD USERS =====
async function loadUsers(){
  try{
    const r=await fetch('/api/users');
    const d=await r.json();
    allUsers=d.users||[];
    renderContacts();
    checkNotifications();
  }catch(e){}
}

function filterContacts(q){
  document.querySelectorAll('.ci').forEach(el=>{
    el.style.display=el.dataset.name.toLowerCase().includes(q.toLowerCase())?'':'none';
  });
}

function makeAvHtml(u,size=50){
  if(u.avatar) return `<img src="${u.avatar}" style="width:${size}px;height:${size}px;border-radius:50%;object-fit:cover;">`;
  const bg=['#00a884','#7c3aed','#1a56db','#dc2626','#d97706','#059669'][u.username.charCodeAt(0)%6];
  return `<div style="width:${size}px;height:${size}px;border-radius:50%;background:${bg};display:flex;align-items:center;justify-content:center;font-weight:900;font-size:${Math.floor(size*.4)}px;color:#fff;">${u.username[0].toUpperCase()}</div>`;
}

function renderContacts(){
  const list=document.getElementById('contact-list');
  const others=allUsers.filter(u=>u.uid!==ME.uid);
  if(!others.length){list.innerHTML='<div style="padding:30px;text-align:center;color:var(--st);font-size:14px;">Belum ada pengguna lain</div>';return;}
  list.innerHTML=others.map(u=>{
    const av=makeAvHtml(u,50);
    const od=u.online?'<div class="odd"></div>':'';
    const prev=u.last_msg||(u.bio||'Tap untuk chat').substring(0,40);
    const tm=u.last_time?fmtTime(u.last_time):'';
    const ub=u.unread_count>0?`<div class="ub">${u.unread_count}</div>`:'';
    const isActive=currentFriend&&currentFriend.uid===u.uid;
    return `<div class="ci${isActive?' active':''}" data-uid="${u.uid}" data-name="${u.username}" onclick="openChat('${u.uid}','${u.username.replace(/'/g,"\\'")}','${u.avatar||''}','${(u.bio||'').replace(/'/g,"\\'")}')">
      <div class="cav">${av}${od}</div>
      <div style="flex:1;min-width:0;"><div class="cn">${u.username}</div><div class="cp">${prev}</div></div>
      <div class="cm"><div class="ct">${tm}</div>${ub}</div>
    </div>`;
  }).join('');
}

// ===== OPEN CHAT =====
function openChat(friendUid,friendName,friendAvatar,friendBio){
  currentFriend={uid:friendUid,name:friendName,avatar:friendAvatar,bio:friendBio};
  document.getElementById('no-chat').style.display='none';
  const ca=document.getElementById('chat-area');ca.style.display='flex';
  document.body.classList.add('chat-open');
  const u={uid:friendUid,username:friendName,avatar:friendAvatar};
  const av=makeAvHtml(u,42);
  document.getElementById('chat-hdr').innerHTML=`
    <button class="back-btn" onclick="closeChatMobile()">â†</button>
    <div style="flex-shrink:0;">${av}</div>
    <div class="chi" onclick="">
      <h3>${friendName}</h3>
      <p id="f-status">Memuat...</p>
    </div>
    <button class="ch-ib" onclick="startCall('audio')" title="Telepon">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M6.6 10.8c1.4 2.8 3.8 5.1 6.6 6.6l2.2-2.2c.3-.3.7-.4 1-.2 1.1.4 2.3.6 3.6.6.6 0 1 .4 1 1V20c0 .6-.4 1-1 1-9.4 0-17-7.6-17-17 0-.6.4-1 1-1h3.5c.6 0 1 .4 1 1 0 1.3.2 2.5.6 3.6.1.3 0 .7-.2 1L6.6 10.8z"/></svg>
    </button>
    <button class="ch-ib" onclick="startCall('video')" title="Video Call">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z"/></svg>
    </button>
  `;
  document.querySelectorAll('.ci').forEach(e=>e.classList.toggle('active',e.dataset.uid===friendUid));
  cancelReply();closeAllMenus();
  loadMessages();
  if(pollTimer)clearInterval(pollTimer);
  pollTimer=setInterval(()=>{loadMessages();checkTyping();},3000);
  fetch('/api/mark_read',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({friend_uid:friendUid})});
}

function closeChatMobile(){
  document.body.classList.remove('chat-open');
  currentFriend=null;
  if(pollTimer){clearInterval(pollTimer);pollTimer=null;}
}

// ===== LOAD MESSAGES =====
async function loadMessages(){
  if(!currentFriend)return;
  try{
    const r=await fetch(`/api/messages?friend_uid=${currentFriend.uid}`);
    const d=await r.json();
    renderMessages(d.messages||[]);
    const f=allUsers.find(u=>u.uid===currentFriend.uid);
    if(f){const el=document.getElementById('f-status');if(el)el.textContent=f.online?'ðŸŸ¢ Online':(f.last_seen?`Terakhir ${fmtTime(f.last_seen)}`:'âš« Offline');}
  }catch(e){}
}

function renderMessages(msgs){
  const area=document.getElementById('msg-area');
  const atBottom=area.scrollHeight-area.clientHeight<=area.scrollTop+80;
  let html='', lastDate='';
  msgs.forEach(m=>{
    const d=new Date(m.time*1000);
    const ds=d.toLocaleDateString('id-ID',{day:'2-digit',month:'long',year:'numeric'});
    if(ds!==lastDate){html+=`<div class="dd"><span>${ds}</span></div>`;lastDate=ds;}
    const isOut=m.from===ME.uid;
    const ts=d.getHours().toString().padStart(2,'0')+':'+d.getMinutes().toString().padStart(2,'0');
    let si='';
    if(isOut){if(m.status==='read')si='<span class="si read">âœ“âœ“</span>';else if(m.status==='delivered')si='<span class="si">âœ“âœ“</span>';else si='<span class="si">âœ“</span>';}
    let rqHtml='';
    if(m.reply_to&&m.reply_to.text){
      const rSender=m.reply_to.from===ME.uid?'Kamu':(currentFriend?currentFriend.name:'?');
      rqHtml=`<div class="rq"><div class="rn">${rSender}</div><div class="rt">${escHtml(m.reply_to.text)}</div></div>`;
    }
    let content='';
    if(m.file){
      const ft=m.file_type||'';
      if(ft.startsWith('image/')||/\.(jpg|jpeg|png|gif|webp|bmp|heic|heif)$/i.test(m.file))
        content+=`<img src="${m.file}" onclick="prevImg('${m.file}')" alt="foto" loading="lazy" style="max-width:240px;">`;
      else if(ft.startsWith('video/')||/\.(mp4|webm|mov|avi|mkv)$/i.test(m.file))
        content+=`<video src="${m.file}" controls style="max-width:240px;border-radius:8px;display:block;margin-bottom:3px;"></video>`;
      else if(ft.startsWith('audio/')||/\.(ogg|m4a|wav|mp3|webm)$/i.test(m.file))
        content+=`<audio src="${m.file}" controls style="width:220px;margin-bottom:3px;"></audio>`;
      else
        content+=`<a href="${m.file}" target="_blank" style="display:flex;align-items:center;gap:6px;"><span style="font-size:20px;">ðŸ“„</span>${m.file.split('/').pop().substring(0,30)}</a><br>`;
    }
    if(m.message) content+=`<span>${escHtml(m.message)}</span>`;
    const txt=(m.message||'').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
    // Action buttons
    const actions=`<div class="msg-actions">
      <button class="msg-act-btn" onclick='ctxMsgSet("${m.id}","${txt}","${m.from}");ctxReply()' title="Balas">â†©</button>
      <button class="msg-act-btn" onclick='ctxMsgSet("${m.id}","${txt}","${m.from}");ctxMore(event)' title="Lainnya">â‹¯</button>
    </div>`;
    html+=`<div class="mr ${isOut?'out':'in'}" data-id="${m.id}" data-txt="${txt}" data-from="${m.from}" oncontextmenu="showCtx(event,'${m.id}','${txt}','${m.from}')" ontouchstart="handleTouchStart(event,'${m.id}','${txt}','${m.from}')" ontouchend="handleTouchEnd()">
      ${isOut?actions:''}
      <div class="bbl">${rqHtml}${content}<div class="bt">${ts} ${si}</div></div>
      ${!isOut?actions:''}
    </div>`;
  });
  if(!html) html='<div style="text-align:center;color:var(--st);padding:40px;font-size:14px;">Belum ada pesan. Mulai percakapan! ðŸ‘‹</div>';
  area.innerHTML=html;
  if(atBottom) area.scrollTop=area.scrollHeight;
}

function escHtml(s){return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

// ===== CONTEXT MENU =====
let touchTimer=null;
function ctxMsgSet(id,txt,from){ctxMsg={id,txt:txt.replace(/&#39;/g,"'").replace(/&quot;/g,'"'),from};}
function showCtx(e,id,txt,from){
  e.preventDefault();e.stopPropagation();
  ctxMsg={id,txt:txt.replace(/&#39;/g,"'").replace(/&quot;/g,'"'),from};
  positionCtx(e.clientX,e.clientY);
}
function ctxMore(e){
  e.stopPropagation();
  positionCtx(e.clientX,e.clientY);
}
function positionCtx(x,y){
  const menu=document.getElementById('ctx-menu');
  menu.style.display='block';
  const mw=menu.offsetWidth||180, mh=menu.offsetHeight||160;
  menu.style.left=Math.min(x,window.innerWidth-mw-10)+'px';
  menu.style.top=Math.min(y,window.innerHeight-mh-10)+'px';
  setTimeout(()=>document.addEventListener('click',closeCtx,{once:true}),10);
}
function handleTouchStart(e,id,txt,from){touchTimer=setTimeout(()=>{ctxMsg={id,txt:txt.replace(/&#39;/g,"'"),from};positionCtx(e.touches[0].clientX,e.touches[0].clientY);},600);}
function handleTouchEnd(){if(touchTimer){clearTimeout(touchTimer);touchTimer=null;}}
function closeCtx(){document.getElementById('ctx-menu').style.display='none';}
function ctxCopy(){if(ctxMsg){navigator.clipboard.writeText(ctxMsg.txt).then(()=>toast('Pesan disalin ðŸ“‹'));closeCtx();}}
function ctxReply(){
  if(!ctxMsg)return;
  replyTo={id:ctxMsg.id,text:ctxMsg.txt,from:ctxMsg.from||''};
  document.getElementById('reply-name').textContent=ctxMsg.from===ME.uid?'Kamu':(currentFriend?currentFriend.name:'?');
  document.getElementById('reply-text').textContent=ctxMsg.txt||'Media';
  document.getElementById('reply-bar').style.display='flex';
  document.getElementById('msg-input').focus();
  closeCtx();
}
function ctxForward(){
  if(!ctxMsg)return;
  forwardText=ctxMsg.txt;
  forwardSelectedUid=null;
  const list=document.getElementById('fw-list');
  const others=allUsers.filter(u=>u.uid!==ME.uid);
  list.innerHTML=others.map(u=>`<div class="fw-item" id="fw-${u.uid}" onclick="selectForward('${u.uid}')">
    <div class="fw-av">${makeAvHtml(u,40)}</div>
    <span style="font-weight:700;">${u.username}</span>
  </div>`).join('');
  document.getElementById('fw-send').style.display='none';
  openPanel('fw-ov');closeCtx();
}
function selectForward(uid){
  document.querySelectorAll('.fw-item').forEach(e=>e.classList.remove('sel'));
  document.getElementById('fw-'+uid).classList.add('sel');
  forwardSelectedUid=uid;
  document.getElementById('fw-send').style.display='block';
}
async function doForward(){
  if(!forwardSelectedUid||!forwardText)return;
  const r=await fetch('/api/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({to_uid:forwardSelectedUid,message:'â†ªï¸ '+forwardText})});
  const d=await r.json();
  if(d.ok){toast('Pesan diteruskan â†ªï¸');closePanel('fw-ov');}
  else toast('Gagal meneruskan pesan',2500,true);
}
async function ctxDelete(){
  if(!ctxMsg||!currentFriend)return;closeCtx();
  if(!confirm('Hapus pesan ini?'))return;
  const r=await fetch('/api/delete_message',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message_id:ctxMsg.id,friend_uid:currentFriend.uid})});
  const d=await r.json();
  if(d.ok){loadMessages();toast('Pesan dihapus ðŸ—‘ï¸');}
  else toast('Gagal hapus: '+(d.msg||''),2500,true);
}
function cancelReply(){replyTo=null;document.getElementById('reply-bar').style.display='none';}
function closeAllMenus(){
  document.getElementById('att-menu').classList.remove('open');
  document.getElementById('emoji-picker').classList.remove('open');
  document.getElementById('ctx-menu').style.display='none';
}

// ===== SEND MESSAGE =====
function handleKey(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();sendMsg();}}
function autoResize(t){t.style.height='auto';t.style.height=Math.min(t.scrollHeight,120)+'px';}
async function sendMsg(){
  const input=document.getElementById('msg-input');
  const text=input.value.trim();
  if(!text||!currentFriend)return;
  input.value='';input.style.height='auto';
  const body={to_uid:currentFriend.uid,message:text};
  if(replyTo)body.reply_to={id:replyTo.id,text:replyTo.text,from:replyTo.from};
  const r=await fetch('/api/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const d=await r.json();
  if(d.ok){cancelReply();loadMessages();}
  else toast('Gagal kirim ðŸ˜•',2500,true);
}

// ===== TYPING INDICATOR =====
async function sendTyping(){
  const now=Date.now();
  if(now-lastTypingTime<2000)return;
  lastTypingTime=now;
  if(!currentFriend)return;
  await fetch('/api/typing',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({to_uid:currentFriend.uid})});
}
async function checkTyping(){
  if(!currentFriend)return;
  try{
    const r=await fetch(`/api/typing_status?friend_uid=${currentFriend.uid}`);
    const d=await r.json();
    const ind=document.getElementById('typing-ind');
    const nm=document.getElementById('typing-nm');
    if(d.typing){
      nm.textContent=currentFriend.name+' sedang mengetik...';
      ind.classList.add('show');
    }else ind.classList.remove('show');
  }catch(e){}
}

// ===== ATTACHMENT MENU =====
function toggleAttMenu(){closeAllMenus();document.getElementById('att-menu').classList.toggle('open');}
function triggerFile(t){
  document.getElementById('att-menu').classList.remove('open');
  document.getElementById(t==='photo'?'file-photo':'file-doc').click();
}

function showUploadProgress(){
  const bar=document.getElementById('upload-bar');
  const prog=document.getElementById('upload-prog');
  bar.classList.add('show');prog.style.width='0%';
  let w=0;const iv=setInterval(()=>{w+=Math.random()*15;if(w>=90){clearInterval(iv);}prog.style.width=Math.min(w,90)+'%';},200);
  return ()=>{prog.style.width='100%';setTimeout(()=>bar.classList.remove('show'),500);clearInterval(iv);};
}

async function handleFileUpload(input){
  if(!input.files[0]||!currentFriend)return;
  document.getElementById('att-menu').classList.remove('open');
  const done=showUploadProgress();
  const fd=new FormData();
  fd.append('file',input.files[0]);
  fd.append('to_uid',currentFriend.uid);
  if(replyTo){fd.append('reply_from',replyTo.from);fd.append('reply_text',replyTo.text);}
  try{
    const r=await fetch('/api/send_file',{method:'POST',body:fd});
    const d=await r.json();done();
    if(d.ok){toast('Terkirim! ðŸ“Ž');cancelReply();loadMessages();}
    else toast('Gagal upload: '+(d.msg||''),3000,true);
  }catch(e){done();toast('Gagal upload ðŸ˜•',2500,true);}
  input.value='';
}

// ===== CAMERA =====
let camPhotoBlob=null;
function openCameraForChat(){document.getElementById('att-menu').classList.remove('open');camMode='chat';openCamera();}
async function openCamera(){
  try{
    camStream=await navigator.mediaDevices.getUserMedia({video:{facingMode:camFacing},audio:false});
    document.getElementById('cam-vid').srcObject=camStream;
    document.getElementById('cam-canvas').style.display='none';
    document.getElementById('cam-preview').style.display='none';
    camPhotoBlob=null;openPanel('cam-ov');
  }catch(e){toast('Kamera tidak dapat diakses: '+e.message,3000,true);}
}
function switchCamera(){camFacing=camFacing==='user'?'environment':'user';closeCamera();setTimeout(openCamera,300);}
function snapPhoto(){
  const vid=document.getElementById('cam-vid');
  const canvas=document.getElementById('cam-canvas');
  canvas.width=vid.videoWidth;canvas.height=vid.videoHeight;
  canvas.getContext('2d').drawImage(vid,0,0);
  canvas.style.display='block';
  canvas.toBlob(blob=>{camPhotoBlob=blob;},'image/jpeg',0.92);
  document.getElementById('cam-preview').style.display='block';
}
async function sendCameraPhoto(){
  if(!camPhotoBlob){toast('Ambil foto dulu!',2000,true);return;}
  if(camMode==='status'){
    closeCamera();
    const done=showUploadProgress();
    const fd=new FormData();fd.append('file',new File([camPhotoBlob],'camera.jpg',{type:'image/jpeg'}));fd.append('type','image');
    const r=await fetch('/api/status/upload',{method:'POST',body:fd});
    const d=await r.json();done();
    if(d.ok)toast('Status diposting! âœ…');else toast('Gagal upload status',2500,true);
    return;
  }
  if(!currentFriend){toast('Pilih chat dulu!',2000,true);return;}
  closeCamera();
  const done=showUploadProgress();
  const fd=new FormData();fd.append('file',new File([camPhotoBlob],'camera.jpg',{type:'image/jpeg'}));fd.append('to_uid',currentFriend.uid);
  const r=await fetch('/api/send_file',{method:'POST',body:fd});
  const d=await r.json();done();
  if(d.ok){toast('Foto terkirim! ðŸ“¸');loadMessages();}else toast('Gagal kirim foto',2500,true);
}
function closeCamera(){if(camStream)camStream.getTracks().forEach(t=>t.stop());camStream=null;closePanel('cam-ov');}

// ===== VOICE RECORDING =====
async function startRecording(e){
  if(e)e.preventDefault();
  if(!currentFriend){toast('Pilih chat dulu!',2000,true);return;}
  try{
    const stream=await navigator.mediaDevices.getUserMedia({audio:true});
    const mime=MediaRecorder.isTypeSupported('audio/webm')?'audio/webm':'audio/ogg';
    mediaRec=new MediaRecorder(stream,{mimeType:mime});
    recChunks=[];isRecording=true;
    mediaRec.ondataavailable=e=>recChunks.push(e.data);
    mediaRec.onstop=async()=>{
      const blob=new Blob(recChunks,{type:mime});
      stream.getTracks().forEach(t=>t.stop());
      if(blob.size>500){
        const done=showUploadProgress();
        const fd=new FormData();
        fd.append('file',new File([blob],'voice.webm',{type:mime}));
        fd.append('to_uid',currentFriend.uid);
        const r=await fetch('/api/send_file',{method:'POST',body:fd});
        const d=await r.json();done();
        if(d.ok){toast('Pesan suara terkirim ðŸŽ™ï¸');loadMessages();}
        else toast('Gagal kirim suara',2500,true);
      }
    };
    mediaRec.start();
    document.getElementById('rec-btn').classList.add('recording');
    toast('Merekam... Lepaskan untuk kirim ðŸŽ™ï¸',10000);
  }catch(e){toast('Mikrofon tidak dapat diakses',2500,true);}
}
function stopRecording(e){
  if(e)e.preventDefault();
  if(mediaRec&&isRecording){mediaRec.stop();isRecording=false;document.getElementById('rec-btn').classList.remove('recording');toast('Mengirim suara...',1500);}
}

// ===== IMAGE PREVIEW =====
function prevImg(src){document.getElementById('img-full').src=src;openPanel('img-ov');}

// ===== PROFILE =====
async function uploadAvatar(input){
  if(!input.files[0])return;
  const file=input.files[0];
  if(file.size>10*1024*1024){toast('Ukuran foto max 10MB',2500,true);return;}
  const done=showUploadProgress();
  const fd=new FormData();fd.append('avatar',file);
  try{
    const r=await fetch('/api/upload_avatar',{method:'POST',body:fd});
    const d=await r.json();done();
    if(d.ok){
      const url=d.url+'?t='+Date.now();
      document.getElementById('pav-big').innerHTML=`<img src="${url}" style="width:110px;height:110px;object-fit:cover;border-radius:50%;">`;
      document.getElementById('my-av').innerHTML=`<img src="${url}" style="width:42px;height:42px;border-radius:50%;object-fit:cover;">`;
      toast('Foto profil diperbarui âœ…');
    }else{toast('Gagal upload: '+(d.msg||'Server error'),3000,true);}
  }catch(e){done();toast('Gagal upload foto',2500,true);}
  input.value='';
}

async function saveProfile(){
  const u=document.getElementById('edit-u').value.trim();
  const b=document.getElementById('edit-b').value.trim();
  if(!u){toast('Username tidak boleh kosong',2500,true);return;}
  const fd=new FormData();fd.append('username',u);fd.append('bio',b);
  const r=await fetch('/api/update_profile',{method:'POST',body:fd});
  const d=await r.json();
  if(d.ok){
    document.getElementById('prof-name').textContent=u;
    toast('Profil disimpan âœ…');
    closePanel('prof-ov');
    setTimeout(()=>location.reload(),800);
  }else toast('Gagal simpan: '+(d.msg||''),3000,true);
}
function doLogout(){if(confirm('Yakin mau logout?'))fetch('/logout',{method:'POST'}).then(()=>location.href='/');}

// ===== NOTIFICATIONS =====
async function checkNotifications(){
  try{
    const r=await fetch('/api/notifications');const d=await r.json();
    const cnt=(d.notifications||[]).filter(n=>!n.read).length;
    const b=document.getElementById('nb');b.style.display=cnt>0?'':'none';b.textContent=cnt>9?'9+':cnt;
  }catch(e){}
}
async function loadNotifications(){
  const r=await fetch('/api/notifications');const d=await r.json();
  const list=document.getElementById('notif-list');
  const notifs=d.notifications||[];
  if(!notifs.length){list.innerHTML='<div style="text-align:center;color:var(--st);padding:20px;">Tidak ada notifikasi ðŸŽ‰</div>';return;}
  list.innerHTML=notifs.slice().reverse().map(n=>{
    const s=allUsers.find(u=>u.uid===n.from);const nm=s?.username||'Pengguna';
    const av=s?makeAvHtml(s,44):`<div style="width:44px;height:44px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-weight:900;font-size:18px;color:#fff;">${nm[0].toUpperCase()}</div>`;
    return `<div class="ni" onclick="closePanel('notif-ov');openChat('${n.from}','${nm}','${s?.avatar||''}','')">
      <div class="nav2">${av}</div>
      <div class="nd"><div class="nn">${nm}</div><div class="nm">${n.message}</div><div class="nt">${fmtTime(n.time)}</div></div>
      ${!n.read?'<div class="ndot"></div>':''}
    </div>`;
  }).join('');
}
async function markNotifsRead(){await fetch('/api/notifications/read',{method:'POST'});checkNotifications();}

// ===== STATUS =====
async function loadStatuses(){
  try{
    const r=await fetch('/api/status/list');const d=await r.json();
    const list=document.getElementById('status-list');
    const stats=d.statuses||[];
    // Tampilkan status milik sendiri juga
    const myStats=d.my_statuses||[];
    let html='';
    if(myStats.length>0){
      const latest=myStats[myStats.length-1];
      const thumb=latest.type==='image'&&latest.media_url?`<img class="st-thumb" src="${latest.media_url}" alt="status">`:'';
      html+=`<div style="margin-bottom:12px;">
        <div style="font-size:11px;font-weight:800;color:var(--st);text-transform:uppercase;letter-spacing:.6px;margin-bottom:8px;">Status Saya</div>
        <div class="st-card" onclick="viewMyStatus()" style="border-color:var(--g);">
          ${thumb}
          <div class="st-av">${makeAvHtml({uid:ME.uid,username:ME.username,avatar:''},48)}</div>
          <div class="st-nm">${ME.username}</div>
          <div class="st-tm">${fmtTime(latest.time)} Â· ${myStats.length} status</div>
        </div>
      </div>`;
    }
    if(!stats.length&&!myStats.length){
      list.innerHTML='<div style="text-align:center;color:var(--st);padding:20px;">Belum ada status ðŸ“­</div>';return;
    }
    if(stats.length>0){
      const byUser={};
      stats.forEach(s=>{if(!byUser[s.uid])byUser[s.uid]=[];byUser[s.uid].push(s);});
      html+=`<div style="font-size:11px;font-weight:800;color:var(--st);text-transform:uppercase;letter-spacing:.6px;margin-bottom:8px;">Terbaru</div>`;
      html+=`<div class="st-grid">${Object.entries(byUser).map(([uid,sts])=>{
        const u=allUsers.find(x=>x.uid===uid)||{uid,username:'?',avatar:''};
        const latest=sts[sts.length-1];
        const thumb=latest.type==='image'&&latest.media_url?`<img class="st-thumb" src="${latest.media_url}" alt="status">`:'';
        return `<div class="st-card" onclick="viewStatus('${uid}')">
          ${u.online?'<div class="st-oi"></div>':''}
          ${thumb}
          <div class="st-av">${makeAvHtml(u,48)}</div>
          <div class="st-nm">${u.username}</div>
          <div class="st-tm">${fmtTime(latest.time)} Â· ${sts.length} status</div>
        </div>`;
      }).join('')}</div>`;
    }
    list.innerHTML=html;
  }catch(e){console.error('loadStatuses error:',e);}
}
async function viewMyStatus(){
  const r=await fetch('/api/status/my');const d=await r.json();
  const sts=d.statuses||[];if(!sts.length)return;
  const u={uid:ME.uid,username:ME.username,avatar:''};
  statusViewData={uid:ME.uid,user:u,statuses:sts};statusViewIdx=0;
  renderStatusView();openPanel('stview-ov');
}

function openCreateStatus(){closePanel('stat-ov');document.getElementById('text-status-form').style.display='none';openPanel('cstat-ov');}
function openTextStatus(){document.getElementById('text-status-form').style.display='block';}

async function postTextStatus(){
  const txt=document.getElementById('stat-txt').value.trim();
  if(!txt){toast('Tulis status dulu!',2000,true);return;}
  const btn=document.querySelector('#text-status-form .sbtn');
  if(btn){btn.disabled=true;btn.textContent='Memposting...';}
  const r=await fetch('/api/status/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:'text',content:txt})});
  const d=await r.json();
  if(btn){btn.disabled=false;btn.textContent='ðŸ“¤ Posting Status';}
  if(d.ok){
    toast('Status diposting! âœ…');
    closePanel('cstat-ov');
    document.getElementById('stat-txt').value='';
    document.getElementById('char-cnt').textContent='0/200';
    document.getElementById('text-status-form').style.display='none';
    // Buka kembali status panel dan refresh
    openPanel('stat-ov');
    loadStatuses();
  }else toast('Gagal posting status: '+(d.msg||''),3000,true);
}

async function uploadStatus(input,type){
  if(!input.files[0])return;
  const file=input.files[0];
  if(file.size>50*1024*1024){toast('File terlalu besar (max 50MB)',2500,true);return;}
  const done=showUploadProgress();
  const fd=new FormData();fd.append('file',file);fd.append('type',type);
  try{
    const r=await fetch('/api/status/upload',{method:'POST',body:fd});
    const d=await r.json();done();
    if(d.ok){
      toast('Status diposting! âœ…');
      closePanel('cstat-ov');
      // Buka kembali status panel dan refresh
      openPanel('stat-ov');
      loadStatuses();
    }else toast('Gagal upload status: '+(d.msg||''),3000,true);
  }catch(e){done();toast('Gagal upload',2500,true);}
  input.value='';
}

function openCameraStatus(){closePanel('cstat-ov');camMode='status';openCamera();}

async function viewStatus(uid){
  const r=await fetch(`/api/status/user/${uid}`);const d=await r.json();
  const sts=d.statuses||[];if(!sts.length)return;
  const u=allUsers.find(x=>x.uid===uid)||{username:'?',avatar:'',uid};
  statusViewData={uid,user:u,statuses:sts};statusViewIdx=0;
  renderStatusView();openPanel('stview-ov');
}
function clearStatusTimer(){if(statusTimer){clearInterval(statusTimer);statusTimer=null;}}
function renderStatusView(){
  const {user,statuses}=statusViewData;const s=statuses[statusViewIdx];
  const av=makeAvHtml(user,36);
  document.getElementById('stv-av').innerHTML=av;
  document.getElementById('stv-nm').textContent=user.username;
  document.getElementById('stv-tm').textContent=fmtTime(s.time);
  document.getElementById('stv-bar').innerHTML=statuses.map((_,i)=>`<div class="stv-seg"><div class="stv-fill" id="stv-fill-${i}" style="width:${i<statusViewIdx?100:0}%"></div></div>`).join('');
  let cnt='';
  if(s.type==='text'){
    const colors=['#005c4b','#1a56db','#7c3aed','#dc2626','#d97706'];
    const bg=colors[statusViewIdx%colors.length];
    cnt=`<div class="stv-txt" style="background:${bg};width:100%;padding:40px 20px;">${escHtml(s.content)}</div>`;
  }else if(s.type==='image')cnt=`<img class="stv-img" src="${s.media_url}" alt="status">`;
  else if(s.type==='video')cnt=`<video src="${s.media_url}" controls autoplay style="max-width:100%;max-height:420px;border-radius:12px;"></video>`;
  document.getElementById('stv-cnt').innerHTML=cnt;
  clearStatusTimer();
  const fill=document.getElementById(`stv-fill-${statusViewIdx}`);
  if(fill){fill.style.transition='';fill.style.width='0%';requestAnimationFrame(()=>{fill.style.transition='width 5s linear';fill.style.width='100%';});}
  statusTimer=setInterval(()=>{statusViewIdx++;if(statusViewIdx>=statuses.length){clearStatusTimer();closePanel('stview-ov');}else renderStatusView();},5000);
}

// ===== CALLS (WebRTC) =====
async function startCall(type){
  if(!currentFriend){toast('Pilih teman dulu');return;}
  callType=type;
  try{
    const constraints=type==='video'?{video:true,audio:true}:{audio:true};
    localStream=await navigator.mediaDevices.getUserMedia(constraints);
  }catch(e){toast('Tidak bisa akses '+(type==='video'?'kamera/':'')+'mikrofon: '+e.message,3000,true);return;}
  showCallUI(currentFriend,type,'outgoing');
  pc=new RTCPeerConnection(STUN);
  localStream.getTracks().forEach(t=>pc.addTrack(t,localStream));
  if(type==='video'){document.getElementById('localVid').srcObject=localStream;}
  pc.ontrack=e=>{document.getElementById('remoteVid').srcObject=e.streams[0];};
  pc.onicecandidate=e=>{if(e.candidate)sendSignal('ice',{candidate:e.candidate});};
  const offer=await pc.createOffer();
  await pc.setLocalDescription(offer);
  const r=await fetch('/api/call/offer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({to_uid:currentFriend.uid,sdp:offer,call_type:type})});
  const d=await r.json();
  currentCallId=d.call_id;
  pollAnswer();
}
async function pollAnswer(){
  if(!currentCallId)return;
  const r=await fetch(`/api/call/status/${currentCallId}`);
  const d=await r.json();
  if(d.status==='answered'){
    await pc.setRemoteDescription(new RTCSessionDescription(d.answer));
    document.getElementById('call-st').textContent='Terhubung âœ…';
    startCallTimer();
    if(callType==='video'){document.getElementById('call-video-wrap').style.display='block';document.getElementById('call-audio-wrap').style.display='none';document.getElementById('btn-cam').style.display='';}
    pollIce();
  }else if(d.status==='rejected'){toast('Panggilan ditolak ðŸ“µ',3000);endCall();}
  else if(d.status==='pending'){setTimeout(pollAnswer,2000);}
  else if(d.status==='ended'){endCall();}
}
async function sendSignal(type,data){if(!currentCallId)return;await fetch('/api/call/ice',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({call_id:currentCallId,type,data})});}
async function pollIce(){
  if(!currentCallId||!pc)return;
  const r=await fetch(`/api/call/ice/${currentCallId}?uid=${ME.uid}`);
  const d=await r.json();
  for(const c of(d.candidates||[])){try{await pc.addIceCandidate(new RTCIceCandidate(c));}catch(e){}}
  if(currentCallId)setTimeout(pollIce,2000);
}
async function answerCall(){
  if(!incCallData)return;
  currentCallId=incCallData.call_id;callType=incCallData.call_type||'audio';
  document.getElementById('inc-call').classList.remove('show');
  const caller=allUsers.find(u=>u.uid===incCallData.from)||{username:'?',avatar:'',uid:incCallData.from};
  try{
    const constraints=callType==='video'?{video:true,audio:true}:{audio:true};
    localStream=await navigator.mediaDevices.getUserMedia(constraints);
  }catch(e){toast('Tidak bisa akses media',2500,true);return;}
  showCallUI(caller,callType,'incoming');
  pc=new RTCPeerConnection(STUN);
  localStream.getTracks().forEach(t=>pc.addTrack(t,localStream));
  if(callType==='video'){document.getElementById('localVid').srcObject=localStream;document.getElementById('call-video-wrap').style.display='block';document.getElementById('call-audio-wrap').style.display='none';document.getElementById('btn-cam').style.display='';}
  pc.ontrack=e=>{document.getElementById('remoteVid').srcObject=e.streams[0];};
  pc.onicecandidate=e=>{if(e.candidate)sendSignal('ice',{candidate:e.candidate});};
  await pc.setRemoteDescription(new RTCSessionDescription(incCallData.sdp));
  const answer=await pc.createAnswer();
  await pc.setLocalDescription(answer);
  await fetch('/api/call/answer',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({call_id:currentCallId,answer})});
  document.getElementById('call-st').textContent='Terhubung âœ…';
  startCallTimer();pollIce();
}
function rejectCall(){
  if(incCallData){fetch('/api/call/reject',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({call_id:incCallData.call_id})});}
  document.getElementById('inc-call').classList.remove('show');incCallData=null;
}
function showCallUI(friend,type,dir){
  const ui=document.getElementById('call-ui');ui.classList.add('active');
  const av=friend.avatar?`<img src="${friend.avatar}" style="width:120px;height:120px;border-radius:50%;object-fit:cover;">`:`${(friend.username||friend.name||'?')[0].toUpperCase()}`;
  document.getElementById('call-av').innerHTML=av;
  document.getElementById('call-nm').textContent=friend.username||friend.name||'?';
  document.getElementById('call-st').textContent=dir==='outgoing'?'Memanggil...':'Panggilan masuk...';
  document.getElementById('call-timer').style.display='none';
  document.getElementById('call-audio-wrap').style.display='block';
  document.getElementById('call-video-wrap').style.display='none';
  document.getElementById('btn-cam').style.display='none';
}
function endCall(){
  if(pc){pc.close();pc=null;}
  if(localStream)localStream.getTracks().forEach(t=>t.stop());
  localStream=null;
  if(callTimer){clearInterval(callTimer);callTimer=null;}
  if(currentCallId){fetch('/api/call/end',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({call_id:currentCallId})});currentCallId=null;}
  document.getElementById('call-ui').classList.remove('active');
  callSeconds=0;isMuted=false;isCamOff=false;
}
function startCallTimer(){
  callSeconds=0;document.getElementById('call-timer').style.display='';
  callTimer=setInterval(()=>{callSeconds++;const m=Math.floor(callSeconds/60).toString().padStart(2,'0'),s=(callSeconds%60).toString().padStart(2,'0');document.getElementById('call-timer').textContent=m+':'+s;},1000);
}
function toggleMute(){
  isMuted=!isMuted;
  if(localStream)localStream.getAudioTracks().forEach(t=>t.enabled=!isMuted);
  document.getElementById('btn-mute').classList.toggle('active',!isMuted);
  document.getElementById('btn-mute').textContent=isMuted?'ðŸ”‡':'ðŸŽ¤';
}
function toggleCamera(){
  isCamOff=!isCamOff;
  if(localStream)localStream.getVideoTracks().forEach(t=>t.enabled=!isCamOff);
  document.getElementById('btn-cam').classList.toggle('active',!isCamOff);
  document.getElementById('btn-cam').textContent=isCamOff?'ðŸš«ðŸ“·':'ðŸ“·';
}
function toggleSpeaker(){toast('Speaker diaktifkan ðŸ”Š (tergantung perangkat)');}
async function checkIncomingCall(){
  if(pc)return;
  try{
    const r=await fetch('/api/call/incoming');
    const d=await r.json();
    if(d.call&&(!incCallData||incCallData.call_id!==d.call.call_id)){
      incCallData=d.call;
      const caller=allUsers.find(u=>u.uid===d.call.from)||{username:'Seseorang',avatar:'',uid:d.call.from};
      const av=caller.avatar?`<img src="${caller.avatar}" style="width:60px;height:60px;border-radius:50%;object-fit:cover;">`:`${caller.username[0].toUpperCase()}`;
      document.getElementById('inc-av').innerHTML=av;
      document.getElementById('inc-nm').textContent=caller.username;
      document.getElementById('inc-type').textContent=d.call.call_type==='video'?'ðŸ“¹ Video Call Masuk':'ðŸ“ž Panggilan Masuk';
      document.getElementById('inc-call').classList.add('show');
      setTimeout(()=>{if(incCallData&&incCallData.call_id===d.call.call_id)rejectCall();},30000);
    }
  }catch(e){}
}

// ===== INIT =====
buildEmojiPicker();
loadUsers();
async function updatePresence(){try{await fetch('/api/presence',{method:'POST'});}catch(e){}}
updatePresence();
setInterval(()=>{loadUsers();checkNotifications();updatePresence();checkIncomingCall();},5000);
document.addEventListener('click',e=>{
  if(!document.getElementById('att-menu').contains(e.target)&&!e.target.closest('.att-btn'))document.getElementById('att-menu').classList.remove('open');
  if(!document.getElementById('emoji-picker').contains(e.target)&&!e.target.closest('.emoji-btn'))document.getElementById('emoji-picker').classList.remove('open');
});
</script>
</body>
</html>"""

def main_app_html(u):
    import json
    uid      = u.get("uid","")
    username = u.get("username","User")
    email    = u.get("email","")
    avatar   = u.get("avatar","")
    bio      = u.get("bio","Hey there! I am using WaClone.")
    initial  = username[0].upper() if username else "U"

    # Safe JS values using json.dumps (handles quotes, special chars, etc)
    uid_js      = json.dumps(uid)
    username_js = json.dumps(username)

    # HTML-safe values
    username_html = username.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;')
    email_html    = email.replace('&','&amp;').replace('<','&lt;').replace('"','&quot;')
    bio_html      = bio.replace('&','&amp;').replace('<','&lt;').replace('"','&quot;')

    # Sidebar avatar HTML
    if avatar:
        sidebar_av = f'<img src="{avatar}" style="width:42px;height:42px;border-radius:50%;object-fit:cover;">'
    else:
        sidebar_av = f'<span style="font-size:18px;font-weight:900;">{initial}</span>'

    # Profile panel big avatar HTML
    if avatar:
        profile_av = f'<img src="{avatar}" style="width:110px;height:110px;object-fit:cover;border-radius:50%;">'
    else:
        profile_av = f'<span style="font-size:44px;font-weight:900;">{initial}</span>'

    html = MAIN_HTML
    # Use json.dumps for JS string injection (safe against XSS/syntax errors)
    html = html.replace('"__UID__"',      uid_js)
    html = html.replace('"__USERNAME__"', username_js)
    # HTML safe replacements
    html = html.replace("__USERNAME__",  username_html)
    html = html.replace("__EMAIL__",     email_html)
    html = html.replace("__BIO__",       bio_html)
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

# ===== Firebase Web Config (for Google OAuth) =====
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

# ===== Google OAuth =====
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
        # Clean username
        name = ''.join(c for c in name if c.isalnum() or c in '_- ')[:20].strip().replace(' ','_') or "User"
        photo = decoded.get("picture","")

        doc = db.collection("users").document(uid).get()
        if not doc.exists:
            # Check if username is taken, add suffix if needed
            base_name = name
            suffix = 0
            while db.collection("users").where("username","==",name).get():
                suffix += 1
                name = f"{base_name}{suffix}"
            db.collection("users").document(uid).set({
                "uid":uid, "username":name, "email":email,
                "avatar":photo, "bio":"Hey there! I am using WaClone.",
                "online":True, "last_seen":int(time.time()),
                "created_at":int(time.time()), "auth_provider":"google",
                "password":""
            })
        else:
            upd = {"online":True,"last_seen":int(time.time())}
            if photo and not doc.to_dict().get("avatar"):
                upd["avatar"] = photo
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
        except auth.UserNotFoundError:
            pass
        fu = auth.create_user(email=email, password=password)
        db.collection("users").document(fu.uid).set({
            "uid":fu.uid, "username":username, "email":email,
            "password":generate_password_hash(password),
            "bio":"Hey there! I am using WaClone.", "avatar":"",
            "online":True, "last_seen":int(time.time()),
            "created_at":int(time.time()), "auth_provider":"email"
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

# ===== API USERS =====
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
                "uid":u.get("uid"), "username":u.get("username",""),
                "bio":u.get("bio",""), "avatar":u.get("avatar",""),
                "online":u.get("online",False), "last_seen":u.get("last_seen",0),
                "unread_count":unread, "last_msg":last_msg, "last_time":last_time
            })
        users.sort(key=lambda x: x.get("last_time",0), reverse=True)
        return jsonify({"users":users})
    except Exception as e:
        return jsonify({"users":[],"error":str(e)})

# ===== API MESSAGES =====
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
    if not f.filename: return jsonify({"ok":False,"msg":"Nama file tidak valid"})
    # Allow any image type for avatar
    allowed_img = {'png','jpg','jpeg','gif','webp','bmp','heic','heif'}
    ext = f.filename.rsplit('.',1)[-1].lower() if '.' in f.filename else ''
    if ext not in allowed_img:
        return jsonify({"ok":False,"msg":f"Format gambar tidak didukung ({ext}). Gunakan JPG, PNG, atau WEBP"})
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

# ===== TYPING =====
@app.route("/api/typing", methods=["POST"])
def api_typing():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    data = request.get_json()
    to_uid = data.get("to_uid")
    if not to_uid: return jsonify({"ok":False})
    try:
        db.collection("typing").document(f"{user['uid']}_{to_uid}").set({
            "from":user["uid"], "to":to_uid, "time":int(time.time())
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

# ===== NOTIFICATIONS =====
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

# ===== STATUS =====
@app.route("/api/status/create", methods=["POST"])
def api_status_create():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    data = request.get_json()
    try:
        db.collection("statuses").add({
            "uid":user["uid"], "type":data.get("type","text"),
            "content":data.get("content","")[:200], "media_url":None,
            "time":int(time.time()), "viewers":[]
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
            "uid":user["uid"], "type":stype, "content":"", "media_url":url,
            "time":int(time.time()), "viewers":[]
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
        return jsonify({"statuses": others, "my_statuses": my_own})
    except Exception as e:
        print("status_list error:", e, file=sys.stderr)
        return jsonify({"statuses":[],"my_statuses":[]})

@app.route("/api/status/my")
def api_status_my():
    user = get_current_user(request)
    if not user: return jsonify({"statuses":[]})
    try:
        cutoff = int(time.time()) - 86400
        docs = db.collection("statuses").where("uid","==",user["uid"]).where("time",">=",cutoff).order_by("time").stream()
        return jsonify({"statuses":[{**d.to_dict(),"id":d.id} for d in docs]})
    except Exception as e:
        return jsonify({"statuses":[]})

@app.route("/api/status/user/<uid>")
def api_status_user(uid):
    user = get_current_user(request)
    if not user: return jsonify({"statuses":[]})
    try:
        cutoff = int(time.time()) - 86400
        docs = db.collection("statuses").where("uid","==",uid).where("time",">=",cutoff).order_by("time").stream()
        result = [{**d.to_dict(),"id":d.id} for d in docs]
        # Mark as viewed
        for s in result:
            if user["uid"] not in s.get("viewers",[]):
                db.collection("statuses").document(s["id"]).update({"viewers":firestore.ArrayUnion([user["uid"]])})
        return jsonify({"statuses":result})
    except: return jsonify({"statuses":[]})

# ===== CALLS =====
@app.route("/api/call/offer", methods=["POST"])
def api_call_offer():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    data = request.get_json()
    call_id = str(uuid.uuid4())
    try:
        db.collection("calls").document(call_id).set({
            "from":user["uid"], "to":data["to_uid"],
            "sdp":data["sdp"], "status":"pending",
            "call_type":data.get("call_type","audio"),
            "time":int(time.time()), "ice_caller":[], "ice_callee":[]
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

# ===== RUN =====
if __name__ == "__main__":
    port = int(os.environ.get("PORT",5000))
    app.run(host="0.0.0.0", port=port, debug=False)