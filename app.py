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
        firebase_admin.initialize_app(cred, {'storageBucket': 'data-base-d7fda.appspot.com'})
    db = firestore.client()
    bucket = storage.bucket()
    print(f"Firebase connected: {cred_path}", file=sys.stderr)
except Exception as e:
    print("Firebase ERROR:", e, file=sys.stderr)

ALLOWED_EXTENSIONS = {'png','jpg','jpeg','gif','txt','pdf','mp4','webm','ogg','m4a','wav','mp3'}

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
    name = f"{folder}/{int(time.time())}_{uuid.uuid4().hex[:8]}_{file_obj.filename}"
    blob = bucket.blob(name)
    blob.upload_from_file(file_obj.stream, content_type=file_obj.content_type)
    blob.make_public()
    return blob.public_url, file_obj.content_type

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
            "reply_to": reply_to
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
        msgs = db.collection("chats").document(chat_id).collection("messages").order_by("time").limit(150).stream()
        result = []
        for m in msgs:
            d = m.to_dict(); d["id"] = m.id
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
body{font-family:'Nunito',sans-serif;background:var(--dk);color:var(--tx);display:flex;align-items:center;justify-content:center;min-height:100vh;}
input{outline:none;border:none;font-family:'Nunito',sans-serif;}
button{cursor:pointer;font-family:'Nunito',sans-serif;}
.wrap{width:100%;max-width:420px;padding:20px;}
.logo{text-align:center;margin-bottom:36px;}
.logo svg{width:80px;height:80px;filter:drop-shadow(0 8px 24px rgba(0,168,132,.4));}
.logo h1{font-size:30px;font-weight:900;color:var(--g);margin-top:10px;letter-spacing:-1px;}
.logo p{color:var(--st);font-size:14px;margin-top:4px;}
.card{background:var(--pn);border-radius:20px;padding:32px;border:1px solid var(--bd);box-shadow:0 20px 60px rgba(0,0,0,.4);}
.tabs{display:flex;gap:4px;background:var(--dk);border-radius:12px;padding:4px;margin-bottom:28px;}
.tab{flex:1;padding:11px;text-align:center;border-radius:9px;font-weight:800;font-size:14px;color:var(--st);cursor:pointer;transition:.2s;}
.tab.active{background:var(--g);color:#fff;box-shadow:0 4px 12px rgba(0,168,132,.4);}
.fg{margin-bottom:16px;}
.fg label{display:block;font-size:11px;font-weight:800;color:var(--st);margin-bottom:6px;text-transform:uppercase;letter-spacing:.8px;}
.fg input{width:100%;padding:13px 16px;border-radius:12px;font-size:15px;background:var(--dk);border:1.5px solid var(--bd);color:var(--tx);transition:.2s;}
.fg input:focus{border-color:var(--g);background:#1a2328;}
.btn{width:100%;padding:14px;background:var(--g);color:#fff;border:none;border-radius:12px;font-size:16px;font-weight:800;transition:.2s;margin-top:8px;}
.btn:hover{background:#009070;transform:translateY(-1px);box-shadow:0 8px 20px rgba(0,168,132,.35);}
.pf{display:none;}.pf.active{display:block;}
.err{color:var(--rd);font-size:13px;margin-top:8px;text-align:center;min-height:18px;}
.toast{position:fixed;bottom:30px;left:50%;transform:translateX(-50%);background:var(--pn);color:var(--tx);padding:12px 24px;border-radius:12px;border-left:4px solid var(--g);z-index:9999;box-shadow:0 8px 32px rgba(0,0,0,.5);opacity:0;transition:opacity .3s;pointer-events:none;font-weight:700;}
.toast.show{opacity:1;}
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
      <div class="fg"><label>Email</label><input id="le" type="email" placeholder="nama@email.com"></div>
      <div class="fg"><label>Password</label><input id="lp" type="password" placeholder="â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢"></div>
      <div class="err" id="le2"></div>
      <button class="btn" onclick="doLogin()">Masuk â†’</button>
    </div>
    <div id="register-p" class="pf">
      <div class="fg"><label>Username</label><input id="ru" placeholder="username kamu"></div>
      <div class="fg"><label>Email</label><input id="re" type="email" placeholder="nama@email.com"></div>
      <div class="fg"><label>Password</label><input id="rp" type="password" placeholder="min. 6 karakter"></div>
      <div class="err" id="re2"></div>
      <button class="btn" onclick="doReg()">Daftar â†’</button>
    </div>
  </div>
</div>
<div class="toast" id="toast"></div>
<script>
function sw(t){
  document.querySelectorAll('.tab').forEach(e=>e.classList.remove('active'));
  document.querySelectorAll('.pf').forEach(e=>e.classList.remove('active'));
  document.getElementById(t+'-p').classList.add('active');
  document.querySelectorAll('.tab')[t==='login'?0:1].classList.add('active');
}
function toast(m,d=3000){const t=document.getElementById('toast');t.textContent=m;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),d);}
async function doLogin(){
  const email=document.getElementById('le').value, pass=document.getElementById('lp').value, err=document.getElementById('le2');
  if(!email||!pass){err.textContent='Isi semua field!';return;}
  const fd=new FormData();fd.append('email',email);fd.append('password',pass);
  const r=await fetch('/login',{method:'POST',body:fd});
  const d=await r.json();
  if(d.ok){toast('Login berhasil! ðŸŽ‰');setTimeout(()=>location.href='/home',700);}
  else err.textContent=d.msg||'Login gagal';
}
async function doReg(){
  const u=document.getElementById('ru').value,e=document.getElementById('re').value,p=document.getElementById('rp').value,err=document.getElementById('re2');
  if(!u||!e||!p){err.textContent='Isi semua field!';return;}
  const fd=new FormData();fd.append('username',u);fd.append('email',e);fd.append('password',p);
  const r=await fetch('/register',{method:'POST',body:fd});
  const d=await r.json();
  if(d.ok){toast('Registrasi berhasil! ðŸŽ‰');setTimeout(()=>location.href='/home',700);}
  else err.textContent=d.msg||'Registrasi gagal';
}
</script>
</body>
</html>"""

# ===============================
# MAIN APP HTML TEMPLATE
# Use __PLACEHOLDER__ instead of f-string to avoid {{ }} issues
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
.sb{width:380px;min-width:380px;background:var(--pn);display:flex;flex-direction:column;border-right:1px solid var(--bd);}
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
.nc svg{opacity:.2;margin-bottom:20px;}
.nc h2{font-size:26px;font-weight:900;color:var(--tx);margin-bottom:6px;}
/* CHAT */
.ch{height:62px;background:var(--pn);display:flex;align-items:center;gap:12px;padding:0 16px;border-bottom:1px solid var(--bd);flex-shrink:0;}
.chi{flex:1;}
.chi h3{font-weight:900;font-size:16px;}
.chi p{font-size:12px;color:var(--g);}
.ma{flex:1;overflow-y:auto;padding:16px 50px;display:flex;flex-direction:column;gap:3px;
  background-color:var(--dk);
  background-image:url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='%23ffffff' fill-opacity='0.015'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/svg%3E");}
.mr{display:flex;margin:2px 0;position:relative;}
.mr.out{justify-content:flex-end;}
.mr.in{justify-content:flex-start;}
.bbl{max-width:65%;padding:8px 12px 5px;border-radius:12px;font-size:14.5px;line-height:1.5;word-break:break-word;box-shadow:0 1px 3px rgba(0,0,0,.3);position:relative;}
.mr.out .bbl{background:var(--bo);border-bottom-right-radius:3px;}
.mr.in .bbl{background:var(--bi);border-bottom-left-radius:3px;}
.bt{font-size:11px;color:rgba(255,255,255,.45);text-align:right;margin-top:3px;display:flex;align-items:center;justify-content:flex-end;gap:3px;}
.si{font-size:12px;}
.si.read{color:var(--bl);}
.bbl img{max-width:240px;border-radius:8px;display:block;margin-bottom:3px;cursor:pointer;}
.bbl audio{width:220px;margin-bottom:3px;}
.bbl video{max-width:240px;border-radius:8px;display:block;margin-bottom:3px;}
.bbl a{color:var(--bl);text-decoration:none;font-size:13px;}
.dd{text-align:center;color:var(--st);font-size:12px;margin:10px 0;}
.dd span{background:rgba(255,255,255,.08);padding:4px 12px;border-radius:20px;}
/* Reply quote */
.rq{background:rgba(255,255,255,.08);border-left:3px solid var(--g);border-radius:6px;padding:6px 8px;margin-bottom:6px;font-size:12px;}
.rq .rn{font-weight:800;color:var(--g);font-size:11px;margin-bottom:2px;}
.rq .rt{color:var(--st);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}
/* Context menu */
.ctx{position:fixed;background:var(--pn);border:1px solid var(--bd);border-radius:12px;box-shadow:0 8px 30px rgba(0,0,0,.5);z-index:500;min-width:160px;overflow:hidden;display:none;}
.ctx-item{padding:11px 18px;font-size:14px;font-weight:700;cursor:pointer;display:flex;align-items:center;gap:10px;transition:.15s;}
.ctx-item:hover{background:var(--hv);}
/* INPUT BAR */
.ib-wrap{background:var(--pn);padding:8px 12px;display:flex;align-items:flex-end;gap:8px;border-top:1px solid var(--bd);flex-shrink:0;flex-direction:column;}
.reply-bar{width:100%;background:rgba(255,255,255,.05);border-left:3px solid var(--g);border-radius:8px;padding:8px 12px;display:flex;align-items:center;justify-content:space-between;font-size:13px;}
.reply-bar .rn{color:var(--g);font-weight:800;font-size:11px;}
.reply-bar .rt{color:var(--st);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:280px;}
.ib-row{display:flex;align-items:flex-end;gap:8px;width:100%;}
.att-btn{width:40px;height:40px;border-radius:50%;background:transparent;border:none;color:var(--st);display:flex;align-items:center;justify-content:center;flex-shrink:0;}
.att-btn:hover{color:var(--tx);background:var(--hv);}
.mi{flex:1;padding:11px 18px;border-radius:24px;font-size:15px;background:var(--dk);border:1.5px solid var(--bd);color:var(--tx);transition:.2s;max-height:120px;resize:none;line-height:1.4;}
.mi:focus{border-color:var(--g);}
.send-btn{width:46px;height:46px;border-radius:50%;background:var(--g);border:none;display:flex;align-items:center;justify-content:center;transition:.2s;flex-shrink:0;}
.send-btn:hover{background:#009070;transform:scale(1.05);}
.rec-btn{width:46px;height:46px;border-radius:50%;background:var(--dk);border:1.5px solid var(--bd);display:flex;align-items:center;justify-content:center;flex-shrink:0;color:var(--st);}
.rec-btn.recording{background:var(--rd);border-color:var(--rd);color:#fff;animation:pulse 1s infinite;}
@keyframes pulse{0%,100%{transform:scale(1);}50%{transform:scale(1.08);}}
/* Attachment menu */
.att-menu{position:absolute;bottom:80px;left:12px;background:var(--pn);border:1px solid var(--bd);border-radius:16px;padding:12px;box-shadow:0 8px 30px rgba(0,0,0,.5);z-index:200;display:none;flex-wrap:wrap;gap:10px;width:220px;}
.att-menu.open{display:flex;}
.att-opt{display:flex;flex-direction:column;align-items:center;gap:6px;cursor:pointer;width:calc(33% - 8px);}
.att-ic{width:48px;height:48px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:22px;}
.att-lbl{font-size:11px;font-weight:700;color:var(--st);}
/* OVERLAYS / PANELS */
.ov{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:300;display:none;align-items:center;justify-content:center;}
.ov.open{display:flex;}
.pb{background:var(--pn);border-radius:20px;width:400px;max-height:85vh;overflow-y:auto;border:1px solid var(--bd);box-shadow:0 20px 60px rgba(0,0,0,.6);}
.ph{padding:20px 24px 0;display:flex;align-items:center;justify-content:space-between;}
.ph h2{font-size:20px;font-weight:900;}
.xb{background:var(--hv);border:none;color:var(--st);width:32px;height:32px;border-radius:50%;font-size:18px;display:flex;align-items:center;justify-content:center;}
.xb:hover{color:var(--tx);}
.pbd{padding:20px 24px;}
/* Profile */
.pav-w{text-align:center;margin-bottom:20px;position:relative;display:inline-block;left:50%;transform:translateX(-50%);}
.pav-big{width:110px;height:110px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-size:44px;font-weight:900;color:#fff;overflow:hidden;cursor:pointer;border:3px solid var(--bd);}
.pav-big img{width:110px;height:110px;object-fit:cover;}
.pav-edit{position:absolute;bottom:4px;right:0;background:var(--g);width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.4);}
.pnm{font-size:22px;font-weight:900;text-align:center;}
.pem{color:var(--st);font-size:14px;text-align:center;margin-top:4px;}
.ef{margin-bottom:14px;}
.ef label{font-size:11px;font-weight:800;color:var(--g);text-transform:uppercase;letter-spacing:.6px;display:block;margin-bottom:6px;}
.ef input,.ef textarea{width:100%;padding:10px 14px;border-radius:10px;background:var(--dk);border:1.5px solid var(--bd);color:var(--tx);font-size:14px;font-family:'Nunito',sans-serif;}
.ef textarea{resize:none;height:80px;line-height:1.5;}
.ef input:focus,.ef textarea:focus{border-color:var(--g);}
.sbtn{width:100%;padding:13px;background:var(--g);color:#fff;border:none;border-radius:12px;font-size:15px;font-weight:800;margin-top:8px;}
.sbtn:hover{background:#009070;}
.lbtn{width:100%;padding:12px;background:transparent;color:var(--rd);border:1.5px solid var(--rd);border-radius:12px;font-size:15px;font-weight:800;margin-top:10px;}
.lbtn:hover{background:var(--rd);color:#fff;}
/* Notifications */
.ni{display:flex;gap:12px;align-items:center;padding:12px 0;border-bottom:1px solid var(--bd);cursor:pointer;}
.ni:last-child{border-bottom:none;}
.nav{width:44px;height:44px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-weight:900;font-size:18px;color:#fff;flex-shrink:0;}
.nd{flex:1;}
.nn{font-weight:800;font-size:14px;}
.nm{font-size:13px;color:var(--st);margin-top:2px;}
.nt{font-size:11px;color:var(--st);}
.ndot{width:10px;height:10px;background:var(--g);border-radius:50%;flex-shrink:0;}
/* Status */
.st-my{background:var(--dk);border-radius:14px;padding:16px;border:2px dashed var(--bd);cursor:pointer;text-align:center;margin-bottom:16px;transition:.2s;}
.st-my:hover{border-color:var(--g);}
.st-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;}
.st-card{background:var(--dk);border-radius:14px;padding:16px;border:1px solid var(--bd);cursor:pointer;position:relative;overflow:hidden;transition:.2s;}
.st-card:hover{border-color:var(--g);}
.st-av{width:48px;height:48px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-weight:900;font-size:20px;color:#fff;margin-bottom:10px;border:3px solid var(--g);overflow:hidden;}
.st-av img{width:48px;height:48px;object-fit:cover;}
.st-nm{font-weight:800;font-size:13px;}
.st-tm{font-size:11px;color:var(--st);}
.st-oi{position:absolute;top:10px;right:10px;width:10px;height:10px;background:#44c56a;border-radius:50%;}
/* Create Status */
.cst-opts{display:flex;flex-direction:column;gap:10px;}
.cst-opt{display:flex;align-items:center;gap:14px;padding:14px;background:var(--dk);border-radius:12px;border:1.5px solid var(--bd);cursor:pointer;transition:.2s;}
.cst-opt:hover{border-color:var(--g);}
.cst-ic{width:48px;height:48px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:22px;flex-shrink:0;}
.cst-lbl{font-weight:800;font-size:15px;}
.cst-sub{font-size:12px;color:var(--st);}
/* Status viewer */
.stv{background:#000;width:100%;max-width:500px;border-radius:20px;overflow:hidden;position:relative;}
.stv-bar{display:flex;gap:4px;padding:12px 12px 8px;}
.stv-seg{flex:1;height:3px;background:rgba(255,255,255,.3);border-radius:3px;overflow:hidden;}
.stv-fill{height:100%;background:#fff;width:0%;transition:width linear;}
.stv-head{display:flex;align-items:center;gap:10px;padding:8px 16px;}
.stv-av{width:36px;height:36px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-weight:900;color:#fff;font-size:15px;overflow:hidden;}
.stv-av img{width:36px;height:36px;object-fit:cover;}
.stv-nm{font-weight:800;font-size:14px;}
.stv-tm{font-size:11px;color:rgba(255,255,255,.6);}
.stv-cnt{min-height:200px;display:flex;align-items:center;justify-content:center;padding:20px;}
.stv-txt{font-size:24px;font-weight:800;text-align:center;color:#fff;}
.stv-img{max-width:100%;max-height:400px;object-fit:contain;}
/* Camera */
.cam-wrap{position:relative;background:#000;border-radius:16px;overflow:hidden;}
.cam-wrap video{width:100%;border-radius:16px;display:block;}
.cam-controls{display:flex;gap:12px;justify-content:center;margin-top:16px;}
.cam-btn{width:56px;height:56px;border-radius:50%;border:none;display:flex;align-items:center;justify-content:center;font-size:22px;cursor:pointer;transition:.2s;}
.cam-snap{background:var(--g);}
.cam-snap:hover{background:#009070;}
.cam-cancel{background:var(--rd);}
.cam-cancel:hover{background:#d94455;}
/* Call */
.call-ui{position:fixed;inset:0;background:rgba(0,0,0,.92);z-index:900;display:none;flex-direction:column;align-items:center;justify-content:center;gap:20px;}
.call-ui.active{display:flex;}
.call-vids{display:flex;gap:12px;align-items:center;justify-content:center;width:100%;max-width:900px;}
.call-vids video{border-radius:16px;background:#1a1a2e;}
#remoteVid{width:70%;max-height:70vh;object-fit:cover;}
#localVid{width:28%;max-height:40vh;object-fit:cover;border:2px solid var(--g);}
.call-audio-ui{text-align:center;}
.call-av{width:120px;height:120px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-size:50px;font-weight:900;color:#fff;margin:0 auto 16px;overflow:hidden;}
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
/* Incoming call */
.inc-call{position:fixed;bottom:30px;right:30px;background:var(--pn);border:1px solid var(--bd);border-radius:20px;padding:20px;z-index:950;box-shadow:0 20px 60px rgba(0,0,0,.6);min-width:280px;display:none;}
.inc-call.show{display:block;}
.inc-nm{font-size:18px;font-weight:900;margin-bottom:4px;}
.inc-st{font-size:13px;color:var(--st);margin-bottom:16px;}
.inc-acts{display:flex;gap:10px;}
.inc-ans{flex:1;padding:12px;background:var(--g);color:#fff;border:none;border-radius:12px;font-size:15px;font-weight:800;}
.inc-dec{flex:1;padding:12px;background:var(--rd);color:#fff;border:none;border-radius:12px;font-size:15px;font-weight:800;}
/* Image/video preview */
.img-pv{max-width:90vw;max-height:90vh;border-radius:16px;object-fit:contain;}
/* Toast */
.toast{position:fixed;bottom:30px;left:50%;transform:translateX(-50%);background:var(--pn);color:var(--tx);padding:12px 24px;border-radius:12px;border-left:4px solid var(--g);z-index:9999;box-shadow:0 8px 32px rgba(0,0,0,.5);opacity:0;transition:opacity .3s;pointer-events:none;font-weight:700;}
.toast.show{opacity:1;}
</style>
</head>
<body>

<!-- SIDEBAR -->
<div class="sb">
  <div class="sbh">
    <div class="av" onclick="openPanel('prof-ov')" id="my-av">__AVHTML__</div>
    <h2>WaClone</h2>
    <button class="ib" onclick="openPanel('stat-ov')" title="Status">
      <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" stroke-width="2"/><path d="M12 8v4l3 3"/></svg>
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
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M15.5 14h-.79l-.28-.27A6.471 6.471 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/></svg>
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
    <!-- Input Bar -->
    <div class="ib-wrap" id="input-wrap">
      <div class="reply-bar" id="reply-bar" style="display:none;">
        <div><div class="rn" id="reply-name"></div><div class="rt" id="reply-text"></div></div>
        <button class="ib" onclick="cancelReply()" style="width:28px;height:28px;">âœ•</button>
      </div>
      <div class="ib-row">
        <button class="att-btn" onclick="toggleAttMenu()" title="Lampiran">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M16.5 6v11.5c0 2.21-1.79 4-4 4s-4-1.79-4-4V5c0-1.38 1.12-2.5 2.5-2.5s2.5 1.12 2.5 2.5v10.5c0 .55-.45 1-1 1s-1-.45-1-1V6H10v9.5c0 1.38 1.12 2.5 2.5 2.5s2.5-1.12 2.5-2.5V5c0-2.21-1.79-4-4-4S7 2.79 7 5v12.5c0 3.04 2.46 5.5 5.5 5.5s5.5-2.46 5.5-5.5V6h-1.5z"/></svg>
        </button>
        <input type="file" id="file-photo" style="display:none" accept="image/*,video/*" onchange="handleFileUpload(this,'media')">
        <input type="file" id="file-doc" style="display:none" accept=".pdf,.txt,.doc,.docx,.xls,.xlsx,.zip" onchange="handleFileUpload(this,'doc')">
        <textarea class="mi" id="msg-input" rows="1" placeholder="Ketik pesan..." onkeydown="handleKey(event)" oninput="autoResize(this)"></textarea>
        <button class="rec-btn" id="rec-btn" onmousedown="startRecording()" onmouseup="stopRecording()" ontouchstart="startRecording()" ontouchend="stopRecording()" title="Tahan untuk rekam suara">
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
</div>

<!-- PROFILE PANEL -->
<div class="ov" id="prof-ov">
  <div class="pb">
    <div class="ph"><h2>Profil Saya</h2><button class="xb" onclick="closePanel('prof-ov')">âœ•</button></div>
    <div class="pbd">
      <div class="pav-w">
        <div class="pav-big" id="pav-big" onclick="document.getElementById('avatar-file').click()">__INITIAL__</div>
        <div class="pav-edit" onclick="document.getElementById('avatar-file').click()">ðŸ“·</div>
        <input type="file" id="avatar-file" style="display:none" accept="image/*" onchange="uploadAvatar(this)">
      </div>
      <div class="pnm">__USERNAME__</div>
      <div class="pem">__EMAIL__</div>
      <div style="margin-top:20px;">
        <div class="ef"><label>Username</label><input id="edit-u" value="__USERNAME__"></div>
        <div class="ef"><label>Bio / Status</label><textarea id="edit-b">__BIO__</textarea></div>
      </div>
      <button class="sbtn" onclick="saveProfile()">ðŸ’¾ Simpan</button>
      <button class="lbtn" onclick="doLogout()">ðŸšª Logout</button>
    </div>
  </div>
</div>

<!-- NOTIFICATIONS PANEL -->
<div class="ov" id="notif-ov">
  <div class="pb">
    <div class="ph"><h2>Notifikasi</h2><button class="xb" onclick="closePanel('notif-ov');markNotifsRead()">âœ•</button></div>
    <div class="pbd" id="notif-list"><div style="text-align:center;color:var(--st);padding:20px;">Tidak ada notifikasi</div></div>
  </div>
</div>

<!-- STATUS PANEL -->
<div class="ov" id="stat-ov">
  <div class="pb">
    <div class="ph"><h2>Status</h2><button class="xb" onclick="closePanel('stat-ov')">âœ•</button></div>
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
    <div class="ph"><h2>Buat Status</h2><button class="xb" onclick="closePanel('cstat-ov')">âœ•</button></div>
    <div class="pbd">
      <div class="cst-opts">
        <div class="cst-opt" onclick="openTextStatus()">
          <div class="cst-ic" style="background:#2563eb33;">âœï¸</div>
          <div><div class="cst-lbl">Teks</div><div class="cst-sub">Buat status teks</div></div>
        </div>
        <div class="cst-opt" onclick="document.getElementById('stat-photo').click()">
          <div class="cst-ic" style="background:#dc262633;">ðŸ–¼ï¸</div>
          <div><div class="cst-lbl">Foto</div><div class="cst-sub">Upload foto sebagai status</div></div>
        </div>
        <div class="cst-opt" onclick="document.getElementById('stat-video').click()">
          <div class="cst-ic" style="background:#7c3aed33;">ðŸŽ¥</div>
          <div><div class="cst-lbl">Video</div><div class="cst-sub">Upload video sebagai status</div></div>
        </div>
        <div class="cst-opt" onclick="openCameraStatus()">
          <div class="cst-ic" style="background:#05966933;">ðŸ“¸</div>
          <div><div class="cst-lbl">Kamera</div><div class="cst-sub">Foto langsung dari kamera</div></div>
        </div>
      </div>
      <input type="file" id="stat-photo" accept="image/*" style="display:none" onchange="uploadStatus(this,'image')">
      <input type="file" id="stat-video" accept="video/*" style="display:none" onchange="uploadStatus(this,'video')">
      <div id="text-status-form" style="display:none;margin-top:16px;">
        <div class="ef"><label>Teks Status</label><textarea id="stat-txt" placeholder="Tulis status kamu..." style="height:100px;"></textarea></div>
        <button class="sbtn" onclick="postTextStatus()">ðŸ“¤ Posting Status</button>
      </div>
    </div>
  </div>
</div>

<!-- STATUS VIEWER -->
<div class="ov" id="stview-ov">
  <div class="stv" id="stv-box">
    <div class="stv-bar" id="stv-bar"></div>
    <div class="stv-head">
      <div class="stv-av" id="stv-av"></div>
      <div>
        <div class="stv-nm" id="stv-nm"></div>
        <div class="stv-tm" id="stv-tm"></div>
      </div>
      <button class="xb" onclick="closePanel('stview-ov')" style="margin-left:auto;">âœ•</button>
    </div>
    <div class="stv-cnt" id="stv-cnt"></div>
  </div>
</div>

<!-- CAMERA PANEL -->
<div class="ov" id="cam-ov">
  <div class="pb" style="width:440px;">
    <div class="ph"><h2>Kamera</h2><button class="xb" onclick="closeCamera()">âœ•</button></div>
    <div class="pbd">
      <div class="cam-wrap"><video id="cam-vid" autoplay playsinline muted></video></div>
      <canvas id="cam-canvas" style="display:none;width:100%;border-radius:12px;margin-top:10px;"></canvas>
      <div class="cam-controls">
        <button class="cam-btn cam-snap" onclick="snapPhoto()" title="Foto">ðŸ“¸</button>
        <button class="cam-btn" style="background:#2a3942;" onclick="switchCamera()" title="Balik kamera">ðŸ”„</button>
        <button class="cam-btn cam-cancel" onclick="closeCamera()" title="Batal">âœ•</button>
      </div>
      <div id="cam-preview" style="display:none;margin-top:12px;">
        <button class="sbtn" onclick="sendCameraPhoto()">ðŸ“¤ Kirim Foto</button>
      </div>
    </div>
  </div>
</div>

<!-- IMAGE FULLSCREEN PREVIEW -->
<div class="ov" id="img-ov" onclick="closePanel('img-ov')">
  <img class="img-pv" id="img-full" src="">
</div>

<!-- CALL UI -->
<div class="call-ui" id="call-ui">
  <div id="call-video-wrap" style="display:none;width:100%;">
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

// ===== STATE =====
let allUsers=[], currentFriend=null, pollTimer=null, replyTo=null;
let ctxMsg=null, mediaRec=null, recChunks=[], isRecording=false;
let pc=null, localStream=null, currentCallId=null, callType='audio';
let callTimer=null, callSeconds=0, isMuted=false, isCamOff=false;
let incCallData=null, camStream=null, camFacing='user', camMode='chat';
let statusViewData=null, statusViewIdx=0, statusTimer=null;

// ===== TOAST =====
function toast(m,d=2500){const t=document.getElementById('toast');t.textContent=m;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),d);}

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

// ===== LOAD USERS =====
async function loadUsers(){
  const r=await fetch('/api/users');
  const d=await r.json();
  allUsers=d.users||[];
  renderContacts();
  checkNotifications();
}

function filterContacts(q){
  document.querySelectorAll('.ci').forEach(el=>{
    el.style.display=el.dataset.name.toLowerCase().includes(q.toLowerCase())?'':'none';
  });
}

function renderContacts(){
  const list=document.getElementById('contact-list');
  const others=allUsers.filter(u=>u.uid!==ME.uid);
  if(!others.length){list.innerHTML='<div style="padding:20px;text-align:center;color:var(--st);">Belum ada pengguna lain</div>';return;}
  list.innerHTML=others.map(u=>{
    const av=u.avatar?`<img src="${u.avatar}" style="width:50px;height:50px;border-radius:50%;object-fit:cover;">`:`<span style="width:50px;height:50px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-weight:900;font-size:20px;color:#fff;">${u.username[0].toUpperCase()}</span>`;
    const od=u.online?'<div class="odd"></div>':'';
    const prev=u.last_msg||(u.bio||'Tap untuk chat').substring(0,40);
    const tm=u.last_time?fmtTime(u.last_time):'';
    const ub=u.unread_count>0?`<div class="ub">${u.unread_count}</div>`:'';
    return `<div class="ci" data-uid="${u.uid}" data-name="${u.username}" onclick="openChat('${u.uid}','${u.username}','${u.avatar||''}','${u.bio||''}')">
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
  const av=friendAvatar?`<img src="${friendAvatar}" style="width:42px;height:42px;border-radius:50%;object-fit:cover;">`:`<div style="width:42px;height:42px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-weight:900;font-size:18px;color:#fff;">${friendName[0].toUpperCase()}</div>`;
  document.getElementById('chat-hdr').innerHTML=`
    ${av}
    <div class="chi"><h3>${friendName}</h3><p id="f-status">Memuat...</p></div>
    <button class="ib" onclick="startCall('audio')" title="Telepon"><svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M6.6 10.8c1.4 2.8 3.8 5.1 6.6 6.6l2.2-2.2c.3-.3.7-.4 1-.2 1.1.4 2.3.6 3.6.6.6 0 1 .4 1 1V20c0 .6-.4 1-1 1-9.4 0-17-7.6-17-17 0-.6.4-1 1-1h3.5c.6 0 1 .4 1 1 0 1.3.2 2.5.6 3.6.1.3 0 .7-.2 1L6.6 10.8z"/></svg></button>
    <button class="ib" onclick="startCall('video')" title="Video Call"><svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M17 10.5V7c0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1v10c0 .55.45 1 1 1h12c.55 0 1-.45 1-1v-3.5l4 4v-11l-4 4z"/></svg></button>
  `;
  document.querySelectorAll('.ci').forEach(e=>e.classList.toggle('active',e.dataset.uid===friendUid));
  cancelReply();
  loadMessages();
  if(pollTimer)clearInterval(pollTimer);
  pollTimer=setInterval(loadMessages,3000);
  fetch('/api/mark_read',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({friend_uid:friendUid})});
}

// ===== LOAD MESSAGES =====
async function loadMessages(){
  if(!currentFriend)return;
  const r=await fetch(`/api/messages?friend_uid=${currentFriend.uid}`);
  const d=await r.json();
  renderMessages(d.messages||[]);
  const f=allUsers.find(u=>u.uid===currentFriend.uid);
  if(f){const el=document.getElementById('f-status');if(el)el.textContent=f.online?'ðŸŸ¢ Online':(f.last_seen?`Terakhir ${fmtTime(f.last_seen)}`:'âš« Offline');}
}

function renderMessages(msgs){
  const area=document.getElementById('msg-area');
  const atBottom=area.scrollHeight-area.clientHeight<=area.scrollTop+60;
  let html='', lastDate='';
  msgs.forEach((m,i)=>{
    const d=new Date(m.time*1000);
    const ds=d.toLocaleDateString('id-ID',{day:'2-digit',month:'long',year:'numeric'});
    if(ds!==lastDate){html+=`<div class="dd"><span>${ds}</span></div>`;lastDate=ds;}
    const isOut=m.from===ME.uid;
    const ts=d.getHours().toString().padStart(2,'0')+':'+d.getMinutes().toString().padStart(2,'0');
    let si='';
    if(isOut){if(m.status==='read')si='<span class="si read">âœ“âœ“</span>';else if(m.status==='delivered')si='<span class="si">âœ“âœ“</span>';else si='<span class="si">âœ“</span>';}
    let rqHtml='';
    if(m.reply_to&&m.reply_to.text){
      const rSender=m.reply_to.from===ME.uid?'Kamu':currentFriend.name;
      rqHtml=`<div class="rq"><div class="rn">${rSender}</div><div class="rt">${m.reply_to.text}</div></div>`;
    }
    let content='';
    if(m.file){
      const ft=m.file_type||'';
      if(ft.startsWith('image/')||/\.(jpg|jpeg|png|gif|webp)$/i.test(m.file))
        content+=`<img src="${m.file}" onclick="prevImg('${m.file}')" alt="foto" loading="lazy">`;
      else if(ft.startsWith('video/')||/\.(mp4|webm|mov)$/i.test(m.file))
        content+=`<video src="${m.file}" controls style="max-width:240px;border-radius:8px;margin-bottom:3px;"></video>`;
      else if(ft.startsWith('audio/')||/\.(ogg|m4a|wav|mp3|webm)$/i.test(m.file))
        content+=`<audio src="${m.file}" controls></audio>`;
      else
        content+=`<a href="${m.file}" target="_blank">ðŸ“„ ${m.file.split('/').pop().substring(0,30)}</a><br>`;
    }
    if(m.message) content+=`<span>${m.message}</span>`;
    html+=`<div class="mr ${isOut?'out':'in'}" data-id="${m.id}" data-txt="${(m.message||'').replace(/"/g,'&quot;')}" data-from="${m.from}" oncontextmenu="showCtx(event,'${m.id}','${(m.message||'').replace(/'/g,'\\\'')}')" ontouchstart="handleTouchStart(event,'${m.id}','${(m.message||'').replace(/'/g,'\\\'')}')" ontouchend="handleTouchEnd()">
      <div class="bbl">${rqHtml}${content}<div class="bt">${ts} ${si}</div></div>
    </div>`;
  });
  if(!html) html='<div style="text-align:center;color:var(--st);padding:40px;font-size:14px;">Belum ada pesan. Mulai percakapan! ðŸ‘‹</div>';
  area.innerHTML=html;
  if(atBottom) area.scrollTop=area.scrollHeight;
}

// ===== CONTEXT MENU =====
let touchTimer=null;
function showCtx(e,id,txt){
  e.preventDefault();e.stopPropagation();
  ctxMsg={id,txt};
  const menu=document.getElementById('ctx-menu');
  menu.style.display='block';menu.style.left=e.clientX+'px';menu.style.top=e.clientY+'px';
  setTimeout(()=>document.addEventListener('click',closeCtx,{once:true}),10);
}
function handleTouchStart(e,id,txt){touchTimer=setTimeout(()=>showCtxTouch(e.touches[0],id,txt),600);}
function handleTouchEnd(){if(touchTimer){clearTimeout(touchTimer);touchTimer=null;}}
function showCtxTouch(t,id,txt){ctxMsg={id,txt};const menu=document.getElementById('ctx-menu');menu.style.display='block';menu.style.left=t.clientX+'px';menu.style.top=t.clientY+'px';setTimeout(()=>document.addEventListener('click',closeCtx,{once:true}),10);}
function closeCtx(){document.getElementById('ctx-menu').style.display='none';}
function ctxCopy(){if(ctxMsg){navigator.clipboard.writeText(ctxMsg.txt).then(()=>toast('Pesan disalin ðŸ“‹'));closeCtx();}}
function ctxReply(){
  if(!ctxMsg)return;
  replyTo={id:ctxMsg.id,text:ctxMsg.txt,from:currentFriend?currentFriend.uid:''};
  document.getElementById('reply-name').textContent=currentFriend?currentFriend.name:'';
  document.getElementById('reply-text').textContent=ctxMsg.txt||'Media';
  document.getElementById('reply-bar').style.display='flex';
  document.getElementById('msg-input').focus();
  closeCtx();
}
function cancelReply(){replyTo=null;document.getElementById('reply-bar').style.display='none';}

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
  if(d.ok){cancelReply();loadMessages();}else toast('Gagal kirim ðŸ˜•');
}

// ===== ATTACHMENT MENU =====
function toggleAttMenu(){const m=document.getElementById('att-menu');m.classList.toggle('open');}
function triggerFile(t){
  document.getElementById('att-menu').classList.remove('open');
  document.getElementById(t==='photo'?'file-photo':'file-doc').click();
}
async function handleFileUpload(input,cat){
  if(!input.files[0]||!currentFriend)return;
  document.getElementById('att-menu').classList.remove('open');
  toast('Mengupload... â³');
  const fd=new FormData();fd.append('file',input.files[0]);fd.append('to_uid',currentFriend.uid);
  if(replyTo){fd.append('reply_from',replyTo.from);fd.append('reply_text',replyTo.text);}
  const r=await fetch('/api/send_file',{method:'POST',body:fd});
  const d=await r.json();
  if(d.ok){toast('Terkirim! ðŸ“Ž');cancelReply();loadMessages();}else toast('Gagal upload ðŸ˜•');
  input.value='';
}

// ===== CAMERA FOR CHAT =====
let camPhotoBlob=null;
function openCameraForChat(){document.getElementById('att-menu').classList.remove('open');camMode='chat';openCamera();}
async function openCamera(){
  try{
    camStream=await navigator.mediaDevices.getUserMedia({video:{facingMode:camFacing},audio:false});
    document.getElementById('cam-vid').srcObject=camStream;
    document.getElementById('cam-canvas').style.display='none';
    document.getElementById('cam-preview').style.display='none';
    camPhotoBlob=null;
    openPanel('cam-ov');
  }catch(e){toast('Tidak bisa akses kamera: '+e.message);}
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
  if(!camPhotoBlob||!currentFriend){toast('Tidak ada foto');return;}
  const fd=new FormData();
  fd.append('file',new File([camPhotoBlob],'camera.jpg',{type:'image/jpeg'}));
  fd.append('to_uid',currentFriend.uid);
  closeCamera();toast('Mengirim foto... â³');
  const r=await fetch('/api/send_file',{method:'POST',body:fd});
  const d=await r.json();
  if(d.ok){toast('Foto terkirim! ðŸ“¸');loadMessages();}else toast('Gagal kirim foto');
}
function closeCamera(){
  if(camStream)camStream.getTracks().forEach(t=>t.stop());
  camStream=null;closePanel('cam-ov');
}

// ===== VOICE RECORDING =====
async function startRecording(){
  if(!currentFriend)return;
  try{
    const stream=await navigator.mediaDevices.getUserMedia({audio:true});
    mediaRec=new MediaRecorder(stream);recChunks=[];isRecording=true;
    mediaRec.ondataavailable=e=>recChunks.push(e.data);
    mediaRec.onstop=async()=>{
      const blob=new Blob(recChunks,{type:'audio/webm'});
      stream.getTracks().forEach(t=>t.stop());
      if(blob.size>1000){
        const fd=new FormData();
        fd.append('file',new File([blob],'voice.webm',{type:'audio/webm'}));
        fd.append('to_uid',currentFriend.uid);
        const r=await fetch('/api/send_file',{method:'POST',body:fd});
        const d=await r.json();
        if(d.ok){toast('Pesan suara terkirim ðŸŽ™ï¸');loadMessages();}
      }
    };
    mediaRec.start();
    document.getElementById('rec-btn').classList.add('recording');
    toast('Merekam... Lepaskan untuk kirim ðŸŽ™ï¸',10000);
  }catch(e){toast('Tidak bisa akses mikrofon');}
}
function stopRecording(){
  if(mediaRec&&isRecording){mediaRec.stop();isRecording=false;document.getElementById('rec-btn').classList.remove('recording');toast('Mengirim suara...',1500);}
}

// ===== IMAGE PREVIEW =====
function prevImg(src){document.getElementById('img-full').src=src;openPanel('img-ov');}

// ===== PROFILE =====
async function uploadAvatar(input){
  if(!input.files[0])return;
  toast('Mengupload foto... â³');
  const fd=new FormData();fd.append('avatar',input.files[0]);
  const r=await fetch('/api/upload_avatar',{method:'POST',body:fd});
  const d=await r.json();
  if(d.ok){
    const el=document.getElementById('pav-big');
    el.innerHTML=`<img src="${d.url}" style="width:110px;height:110px;object-fit:cover;">`;
    document.getElementById('my-av').innerHTML=`<img src="${d.url}" style="width:42px;height:42px;border-radius:50%;object-fit:cover;">`;
    toast('Foto profil diperbarui âœ…');
  }else toast('Gagal upload foto');
}
async function saveProfile(){
  const fd=new FormData();
  fd.append('username',document.getElementById('edit-u').value);
  fd.append('bio',document.getElementById('edit-b').value);
  const r=await fetch('/api/update_profile',{method:'POST',body:fd});
  const d=await r.json();
  if(d.ok){toast('Profil disimpan âœ…');closePanel('prof-ov');setTimeout(()=>location.reload(),800);}
  else toast('Gagal simpan: '+(d.msg||''));
}
function doLogout(){fetch('/logout',{method:'POST'}).then(()=>location.href='/');}

// ===== NOTIFICATIONS =====
async function checkNotifications(){
  const r=await fetch('/api/notifications');const d=await r.json();
  const cnt=(d.notifications||[]).filter(n=>!n.read).length;
  const b=document.getElementById('nb');b.style.display=cnt>0?'':'none';b.textContent=cnt;
}
async function loadNotifications(){
  const r=await fetch('/api/notifications');const d=await r.json();
  const list=document.getElementById('notif-list');
  const notifs=d.notifications||[];
  if(!notifs.length){list.innerHTML='<div style="text-align:center;color:var(--st);padding:20px;">Tidak ada notifikasi ðŸŽ‰</div>';return;}
  list.innerHTML=notifs.slice().reverse().map(n=>{
    const s=allUsers.find(u=>u.uid===n.from);const nm=s?.username||'Pengguna';
    return `<div class="ni" onclick="closePanel('notif-ov');openChat('${n.from}','${nm}','${s?.avatar||''}','')">
      <div class="nav">${nm[0].toUpperCase()}</div>
      <div class="nd"><div class="nn">${nm}</div><div class="nm">${n.message}</div><div class="nt">${fmtTime(n.time)}</div></div>
      ${!n.read?'<div class="ndot"></div>':''}
    </div>`;
  }).join('');
}
async function markNotifsRead(){await fetch('/api/notifications/read',{method:'POST'});checkNotifications();}

// ===== STATUS =====
async function loadStatuses(){
  const r=await fetch('/api/status/list');const d=await r.json();
  const list=document.getElementById('status-list');
  const stats=d.statuses||[];
  if(!stats.length){list.innerHTML='<div style="text-align:center;color:var(--st);padding:20px;">Tidak ada status</div>';return;}
  // Group by user
  const byUser={};
  stats.forEach(s=>{const uid=s.uid;if(!byUser[uid])byUser[uid]=[];byUser[uid].push(s);});
  list.innerHTML=`<div class="st-grid">${Object.entries(byUser).map(([uid,sts])=>{
    const u=allUsers.find(x=>x.uid===uid)||{username:'?',avatar:''};
    const av=u.avatar?`<img src="${u.avatar}">`:`${u.username[0].toUpperCase()}`;
    const latest=sts[sts.length-1];
    return `<div class="st-card" onclick="viewStatus('${uid}')">
      ${u.online?'<div class="st-oi"></div>':''}
      <div class="st-av">${av}</div>
      <div class="st-nm">${u.username}</div>
      <div class="st-tm">${fmtTime(latest.time)} Â· ${sts.length} status</div>
    </div>`;
  }).join('')}</div>`;
}
function openCreateStatus(){closePanel('stat-ov');openPanel('cstat-ov');}
function openTextStatus(){document.getElementById('text-status-form').style.display='block';}
async function postTextStatus(){
  const txt=document.getElementById('stat-txt').value.trim();
  if(!txt)return;
  const r=await fetch('/api/status/create',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({type:'text',content:txt})});
  const d=await r.json();
  if(d.ok){toast('Status diposting! âœ…');closePanel('cstat-ov');document.getElementById('stat-txt').value='';}
  else toast('Gagal posting status');
}
async function uploadStatus(input,type){
  if(!input.files[0])return;
  toast('Mengupload... â³');
  const fd=new FormData();fd.append('file',input.files[0]);fd.append('type',type);
  const r=await fetch('/api/status/upload',{method:'POST',body:fd});
  const d=await r.json();
  if(d.ok){toast('Status diposting! âœ…');closePanel('cstat-ov');}else toast('Gagal upload status');
  input.value='';
}
function openCameraStatus(){closePanel('cstat-ov');camMode='status';openCamera();}
async function viewStatus(uid){
  const r=await fetch(`/api/status/user/${uid}`);const d=await r.json();
  const sts=d.statuses||[];if(!sts.length)return;
  const u=allUsers.find(x=>x.uid===uid)||{username:'?',avatar:''};
  statusViewData={uid,user:u,statuses:sts};statusViewIdx=0;
  renderStatusView();openPanel('stview-ov');
}
function renderStatusView(){
  const {user,statuses}=statusViewData;const s=statuses[statusViewIdx];
  const av=user.avatar?`<img src="${user.avatar}">`:`${user.username[0].toUpperCase()}`;
  document.getElementById('stv-av').innerHTML=av;
  document.getElementById('stv-nm').textContent=user.username;
  document.getElementById('stv-tm').textContent=fmtTime(s.time);
  document.getElementById('stv-bar').innerHTML=statuses.map((_,i)=>`<div class="stv-seg"><div class="stv-fill" id="stv-fill-${i}" style="width:${i<statusViewIdx?100:0}%"></div></div>`).join('');
  let cnt='';
  if(s.type==='text')cnt=`<div class="stv-txt">${s.content}</div>`;
  else if(s.type==='image')cnt=`<img class="stv-img" src="${s.media_url}" alt="status">`;
  else if(s.type==='video')cnt=`<video src="${s.media_url}" controls autoplay style="max-width:100%;max-height:400px;border-radius:12px;"></video>`;
  document.getElementById('stv-cnt').innerHTML=cnt;
  if(statusTimer)clearInterval(statusTimer);
  let pct=0;
  const fill=document.getElementById(`stv-fill-${statusViewIdx}`);
  if(fill){fill.style.transition='';fill.style.width='0%';requestAnimationFrame(()=>{fill.style.transition='width 5s linear';fill.style.width='100%';});}
  statusTimer=setInterval(()=>{statusViewIdx++;if(statusViewIdx>=statuses.length){clearInterval(statusTimer);closePanel('stview-ov');}else renderStatusView();},5000);
}

// ===== CALLS (WebRTC) =====
async function startCall(type){
  if(!currentFriend){toast('Pilih teman dulu');return;}
  callType=type;
  try{
    const constraints=type==='video'?{video:true,audio:true}:{audio:true};
    localStream=await navigator.mediaDevices.getUserMedia(constraints);
  }catch(e){toast('Tidak bisa akses '+( type==='video'?'kamera/':'')+'mikrofon');return;}
  showCallUI(currentFriend,type,'outgoing');
  pc=new RTCPeerConnection(STUN);
  localStream.getTracks().forEach(t=>pc.addTrack(t,localStream));
  if(type==='video'){const lv=document.getElementById('localVid');lv.srcObject=localStream;}
  pc.ontrack=e=>{const rv=document.getElementById('remoteVid');rv.srcObject=e.streams[0];};
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
    document.getElementById('call-st').textContent='Terhubung';
    startCallTimer();
    if(callType==='video'){document.getElementById('call-video-wrap').style.display='block';document.getElementById('call-audio-wrap').style.display='none';document.getElementById('btn-cam').style.display='';}
    pollIce();
  }else if(d.status==='rejected'){toast('Panggilan ditolak');endCall();}
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
  const caller=allUsers.find(u=>u.uid===incCallData.from)||{username:'?',avatar:''};
  try{
    const constraints=callType==='video'?{video:true,audio:true}:{audio:true};
    localStream=await navigator.mediaDevices.getUserMedia(constraints);
  }catch(e){toast('Tidak bisa akses media');return;}
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
  document.getElementById('call-st').textContent='Terhubung';
  startCallTimer();pollIce();
}
function rejectCall(){
  if(incCallData){fetch('/api/call/reject',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({call_id:incCallData.call_id})});}
  document.getElementById('inc-call').classList.remove('show');incCallData=null;
}
function showCallUI(friend,type,dir){
  const ui=document.getElementById('call-ui');ui.classList.add('active');
  const av=friend.avatar?`<img src="${friend.avatar}" style="width:120px;height:120px;border-radius:50%;object-fit:cover;">`:`${friend.username?friend.username[0].toUpperCase():'?'}`;
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
  callSeconds=0;
  document.getElementById('call-timer').style.display='';
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
}
function toggleSpeaker(){toast('Speaker: fitur bergantung perangkat ðŸ“¢');}
async function checkIncomingCall(){
  if(pc)return;
  const r=await fetch('/api/call/incoming');
  const d=await r.json();
  if(d.call){
    incCallData=d.call;
    const caller=allUsers.find(u=>u.uid===d.call.from)||{username:'Seseorang',avatar:''};
    document.getElementById('inc-nm').textContent=caller.username;
    document.getElementById('inc-type').textContent=d.call.call_type==='video'?'ðŸ“¹ Video Call Masuk':'ðŸ“ž Panggilan Masuk';
    document.getElementById('inc-call').classList.add('show');
    setTimeout(()=>{if(incCallData&&incCallData.call_id===d.call.call_id)rejectCall();},30000);
  }
}

// ===== INIT & POLLING =====
async function updatePresence(){await fetch('/api/presence',{method:'POST'});}
loadUsers();updatePresence();
setInterval(()=>{loadUsers();checkNotifications();updatePresence();checkIncomingCall();},6000);
document.getElementById('stat-ov').addEventListener('transitionend',loadStatuses);
document.querySelector('[onclick="openPanel(\'stat-ov\')"]').addEventListener('click',()=>setTimeout(loadStatuses,100));
document.addEventListener('click',e=>{if(!document.getElementById('att-menu').contains(e.target)&&!e.target.closest('.att-btn'))document.getElementById('att-menu').classList.remove('open');});
</script>
</body>
</html>"""

def main_app_html(u):
    uid      = u.get("uid","")
    username = u.get("username","User")
    email    = u.get("email","")
    avatar   = u.get("avatar","")
    bio      = u.get("bio","Hey there! I am using WaClone.")
    initial  = username[0].upper() if username else "U"
    if avatar:
        av_html = f'<img src="{avatar}" style="width:42px;height:42px;border-radius:50%;object-fit:cover;">'
    else:
        av_html = f'<div style="width:42px;height:42px;border-radius:50%;background:var(--g);display:flex;align-items:center;justify-content:center;font-weight:900;font-size:18px;color:#fff;">{initial}</div>'
    if avatar:
        pav_html = f'<img src="{avatar}" style="width:110px;height:110px;object-fit:cover;">'
    else:
        pav_html = initial

    html = MAIN_HTML
    html = html.replace("__UID__", uid)
    html = html.replace("__USERNAME__", username)
    html = html.replace("__EMAIL__", email)
    html = html.replace("__BIO__", bio.replace('"','&quot;').replace('<','&lt;'))
    html = html.replace("__INITIAL__", initial)
    html = html.replace("__AVHTML__", av_html)
    # Profile panel avatar
    html = html.replace('<div class="pav-big" id="pav-big" onclick="document.getElementById(\'avatar-file\').click()">__INITIAL__</div>',
                        f'<div class="pav-big" id="pav-big" onclick="document.getElementById(\'avatar-file\').click()">{pav_html}</div>')
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

@app.route("/register", methods=["POST"])
def register():
    username = request.form.get("username","").strip()
    email    = request.form.get("email","").strip()
    password = request.form.get("password","")
    if not username or not email or not password:
        return jsonify({"ok":False,"msg":"Semua field harus diisi"})
    if len(password) < 6:
        return jsonify({"ok":False,"msg":"Password minimal 6 karakter"})
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
            "uid":fu.uid,"username":username,"email":email,
            "password":generate_password_hash(password),
            "bio":"Hey there! I am using WaClone.","avatar":"",
            "online":True,"last_seen":int(time.time()),"created_at":int(time.time())
        })
        resp = make_response(jsonify({"ok":True}))
        resp.set_cookie("uid", fu.uid, max_age=7*24*3600, httponly=True)
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
        if check_password_hash(u.get("password",""), password):
            uid = u.get("uid")
            db.collection("users").document(uid).update({"online":True,"last_seen":int(time.time())})
            resp = make_response(jsonify({"ok":True}))
            resp.set_cookie("uid", uid, max_age=7*24*3600, httponly=True)
            return resp
        return jsonify({"ok":False,"msg":"Password salah"})
    except Exception as e:
        print("Login error:", e, file=sys.stderr)
        return jsonify({"ok":False,"msg":"Login gagal"})

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
            unread = 0
            last_msg = ""; last_time = 0
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
    if not f or not to_uid: return jsonify({"ok":False})
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
        return jsonify({"ok":False,"msg":str(e)})

@app.route("/api/upload_avatar", methods=["POST"])
def api_upload_avatar():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    f = request.files.get("avatar")
    if not f: return jsonify({"ok":False,"msg":"Tidak ada file"})
    try:
        url, _ = upload_to_storage(f, "avatars")
        db.collection("users").document(user["uid"]).update({"avatar":url})
        return jsonify({"ok":True,"url":url})
    except Exception as e:
        return jsonify({"ok":False,"msg":str(e)})

@app.route("/api/update_profile", methods=["POST"])
def api_update_profile():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    username = request.form.get("username","").strip()
    bio      = request.form.get("bio","").strip()
    try:
        upd = {"bio":bio}
        if username and username != user.get("username"):
            if db.collection("users").where("username","==",username).get():
                return jsonify({"ok":False,"msg":"Username sudah dipakai"})
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
            "uid":user["uid"],"type":data.get("type","text"),
            "content":data.get("content",""),"media_url":None,
            "time":int(time.time()),"viewers":[]
        })
        return jsonify({"ok":True})
    except Exception as e:
        return jsonify({"ok":False,"msg":str(e)})

@app.route("/api/status/upload", methods=["POST"])
def api_status_upload():
    user = get_current_user(request)
    if not user: return jsonify({"ok":False})
    f = request.files.get("file")
    stype = request.form.get("type","image")
    if not f: return jsonify({"ok":False})
    try:
        url, _ = upload_to_storage(f, "statuses")
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
    if not user: return jsonify({"statuses":[]})
    try:
        cutoff = int(time.time()) - 86400  # 24 jam
        docs = db.collection("statuses").where("time",">=",cutoff).order_by("time").stream()
        return jsonify({"statuses":[{**d.to_dict(),"id":d.id} for d in docs if d.to_dict().get("uid")!=user["uid"]]})
    except Exception as e:
        return jsonify({"statuses":[]})

@app.route("/api/status/user/<uid>")
def api_status_user(uid):
    user = get_current_user(request)
    if not user: return jsonify({"statuses":[]})
    try:
        cutoff = int(time.time()) - 86400
        docs = db.collection("statuses").where("uid","==",uid).where("time",">=",cutoff).order_by("time").stream()
        return jsonify({"statuses":[{**d.to_dict(),"id":d.id} for d in docs]})
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
        # Return ICE candidates from the OTHER side
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
    app.run(host="0.0.0.0", port=port)