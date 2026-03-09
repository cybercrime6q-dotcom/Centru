from flask import Flask, request, jsonify, redirect, url_for, make_response
import firebase_admin
from firebase_admin import credentials, firestore, storage, auth
from werkzeug.security import generate_password_hash, check_password_hash
import time, sys, os, json

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
        firebase_admin.initialize_app(cred, {
            'storageBucket': 'data-base-d7fda.appspot.com'
        })
    db = firestore.client()
    bucket = storage.bucket()
    print(f"Firebase connected using {cred_path}", file=sys.stderr)
except Exception as e:
    print("Firebase ERROR:", e, file=sys.stderr)

ALLOWED_EXTENSIONS = {'png','jpg','jpeg','gif','txt','pdf','mp4','webm'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.',1)[1].lower() in ALLOWED_EXTENSIONS

def get_current_user(req):
    uid = req.cookies.get("uid")
    if not uid or not db: return None
    try:
        doc = db.collection("users").document(uid).get()
        if doc.exists:
            return doc.to_dict()
    except:
        pass
    return None

def load_messages(user_uid, friend_uid):
    if not db: return []
    try:
        chat_id = "_".join(sorted([user_uid, friend_uid]))
        msgs = db.collection("chats").document(chat_id).collection("messages").order_by("time").limit(100).stream()
        messages = []
        for m in msgs:
            d = m.to_dict()
            d["id"] = m.id
            messages.append(d)
        return messages
    except Exception as e:
        print("load_messages error:", e, file=sys.stderr)
        return []

def save_message(from_uid, to_uid, text, file_url=None, file_type=None):
    if not db: return
    try:
        chat_id = "_".join(sorted([from_uid, to_uid]))
        msg = {
            "from": from_uid,
            "to": to_uid,
            "message": text or "",
            "time": int(time.time()),
            "status": "sent",
            "file": file_url,
            "file_type": file_type
        }
        db.collection("chats").document(chat_id).collection("messages").add(msg)
        # update last message for both users
        db.collection("chats").document(chat_id).set({
            "participants": [from_uid, to_uid],
            "last_message": text or ("ðŸ“Ž File" if file_url else ""),
            "last_time": int(time.time()),
            "last_from": from_uid
        }, merge=True)
        # add notification for receiver
        db.collection("notifications").add({
            "to": to_uid,
            "from": from_uid,
            "message": text or "ðŸ“Ž File",
            "time": int(time.time()),
            "read": False
        })
    except Exception as e:
        print("save_message error:", e, file=sys.stderr)

def mark_messages_read(user_uid, friend_uid):
    if not db: return
    try:
        chat_id = "_".join(sorted([user_uid, friend_uid]))
        msgs = db.collection("chats").document(chat_id).collection("messages")\
            .where("to", "==", user_uid).where("status", "!=", "read").stream()
        for m in msgs:
            m.reference.update({"status": "read"})
        # mark notifications read
        notifs = db.collection("notifications").where("to", "==", user_uid).where("from", "==", friend_uid).stream()
        for n in notifs:
            n.reference.update({"read": True})
    except Exception as e:
        print("mark_read error:", e, file=sys.stderr)

# ===============================
# HTML TEMPLATES
# ===============================

BASE_STYLE = """
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Nunito:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
:root{
  --green:#00a884;--dark:#111b21;--panel:#202c33;--bubble-out:#005c4b;
  --bubble-in:#202c33;--border:#2a3942;--text:#e9edef;--subtext:#8696a0;
  --hover:#2a3942;--accent:#00a884;--red:#f15c6d;--blue:#53bdeb;
}
*{margin:0;padding:0;box-sizing:border-box;}
body{font-family:'Nunito',sans-serif;background:var(--dark);color:var(--text);height:100vh;overflow:hidden;}
::-webkit-scrollbar{width:6px;}
::-webkit-scrollbar-track{background:transparent;}
::-webkit-scrollbar-thumb{background:var(--border);border-radius:3px;}
input,textarea{outline:none;border:none;background:var(--panel);color:var(--text);font-family:'Nunito',sans-serif;}
button{cursor:pointer;font-family:'Nunito',sans-serif;}
.toast{position:fixed;bottom:30px;left:50%;transform:translateX(-50%);background:var(--panel);color:var(--text);
  padding:12px 24px;border-radius:12px;border-left:4px solid var(--accent);z-index:9999;
  box-shadow:0 8px 32px rgba(0,0,0,.4);opacity:0;transition:opacity .3s;pointer-events:none;font-weight:600;}
.toast.show{opacity:1;}
</style>
"""

AUTH_PAGE = """<!DOCTYPE html>
<html>
<head>
<title>WaClone â€“ Login</title>
""" + BASE_STYLE + """
<style>
body{display:flex;align-items:center;justify-content:center;background:var(--dark);}
.auth-wrap{width:100%;max-width:400px;padding:20px;}
.logo{text-align:center;margin-bottom:40px;}
.logo svg{width:72px;height:72px;}
.logo h1{font-size:28px;font-weight:800;color:var(--accent);margin-top:10px;letter-spacing:-1px;}
.logo p{color:var(--subtext);font-size:14px;}
.card{background:var(--panel);border-radius:16px;padding:32px;border:1px solid var(--border);}
.tabs{display:flex;gap:4px;background:var(--dark);border-radius:10px;padding:4px;margin-bottom:28px;}
.tab{flex:1;padding:10px;text-align:center;border-radius:8px;font-weight:700;font-size:14px;
  color:var(--subtext);cursor:pointer;transition:.2s;}
.tab.active{background:var(--accent);color:#fff;}
.form-group{margin-bottom:16px;}
.form-group label{display:block;font-size:12px;font-weight:700;color:var(--subtext);margin-bottom:6px;text-transform:uppercase;letter-spacing:.5px;}
.form-group input{width:100%;padding:12px 16px;border-radius:10px;font-size:15px;
  background:var(--dark);border:1.5px solid var(--border);color:var(--text);transition:.2s;}
.form-group input:focus{border-color:var(--accent);background:#1a2328;}
.btn{width:100%;padding:14px;background:var(--accent);color:#fff;border:none;border-radius:10px;
  font-size:16px;font-weight:800;letter-spacing:.3px;transition:.2s;margin-top:8px;}
.btn:hover{background:#009070;transform:translateY(-1px);}
.panel-form{display:none;}
.panel-form.active{display:block;}
.error{color:var(--red);font-size:13px;margin-top:8px;text-align:center;}
</style>
</head>
<body>
<div class="auth-wrap">
  <div class="logo">
    <svg viewBox="0 0 72 72" fill="none">
      <circle cx="36" cy="36" r="36" fill="#00a884"/>
      <path d="M36 14C24 14 14 24 14 36c0 3.9 1.1 7.5 3 10.6L14 58l11.7-3.1A22 22 0 1036 14z" fill="white"/>
      <path d="M28 30c0-.6.5-1 1-1h14c.6 0 1 .4 1 1v.5c0 .5-.4 1-1 1H29c-.5 0-1-.5-1-1V30zm0 7c0-.6.5-1 1-1h9c.5 0 1 .4 1 1v.5c0 .5-.5 1-1 1h-9c-.5 0-1-.5-1-1V37z" fill="#00a884"/>
    </svg>
    <h1>WaClone</h1>
    <p>Simple. Fast. Private.</p>
  </div>
  <div class="card">
    <div class="tabs">
      <div class="tab active" onclick="switchTab('login')">Login</div>
      <div class="tab" onclick="switchTab('register')">Register</div>
    </div>

    <div id="login-panel" class="panel-form active">
      <div class="form-group"><label>Email</label><input id="l-email" type="email" placeholder="nama@email.com"></div>
      <div class="form-group"><label>Password</label><input id="l-pass" type="password" placeholder="â€¢â€¢â€¢â€¢â€¢â€¢â€¢â€¢"></div>
      <div class="error" id="l-error"></div>
      <button class="btn" onclick="doLogin()">Masuk â†’</button>
    </div>

    <div id="register-panel" class="panel-form">
      <div class="form-group"><label>Username</label><input id="r-user" placeholder="username kamu"></div>
      <div class="form-group"><label>Email</label><input id="r-email" type="email" placeholder="nama@email.com"></div>
      <div class="form-group"><label>Password</label><input id="r-pass" type="password" placeholder="min. 6 karakter"></div>
      <div class="error" id="r-error"></div>
      <button class="btn" onclick="doRegister()">Daftar â†’</button>
    </div>
  </div>
</div>
<div class="toast" id="toast"></div>
<script>
function switchTab(t){
  document.querySelectorAll('.tab').forEach(e=>e.classList.remove('active'));
  document.querySelectorAll('.panel-form').forEach(e=>e.classList.remove('active'));
  document.getElementById(t+'-panel').classList.add('active');
  document.querySelectorAll('.tab')[t==='login'?0:1].classList.add('active');
}
function showToast(msg, dur=3000){
  const t=document.getElementById('toast'); t.textContent=msg; t.classList.add('show');
  setTimeout(()=>t.classList.remove('show'),dur);
}
async function doLogin(){
  const email=document.getElementById('l-email').value;
  const pass=document.getElementById('l-pass').value;
  const err=document.getElementById('l-error');
  if(!email||!pass){err.textContent='Isi semua field!';return;}
  const fd=new FormData(); fd.append('email',email); fd.append('password',pass);
  const r=await fetch('/login',{method:'POST',body:fd});
  const d=await r.json();
  if(d.ok){showToast('Login berhasil! ðŸŽ‰'); setTimeout(()=>location.href='/home',800);}
  else{err.textContent=d.msg||'Login gagal';}
}
async function doRegister(){
  const user=document.getElementById('r-user').value;
  const email=document.getElementById('r-email').value;
  const pass=document.getElementById('r-pass').value;
  const err=document.getElementById('r-error');
  if(!user||!email||!pass){err.textContent='Isi semua field!';return;}
  const fd=new FormData(); fd.append('username',user); fd.append('email',email); fd.append('password',pass);
  const r=await fetch('/register',{method:'POST',body:fd});
  const d=await r.json();
  if(d.ok){showToast('Registrasi berhasil! ðŸŽ‰'); setTimeout(()=>location.href='/home',800);}
  else{err.textContent=d.msg||'Registrasi gagal';}
}
</script>
</body>
</html>"""

def main_app_html(current_user):
    uid = current_user.get("uid","")
    username = current_user.get("username","User")
    email = current_user.get("email","")
    avatar = current_user.get("avatar", "")
    bio = current_user.get("bio","Hey there! I am using WaClone.")
    avatar_html = f'<img src="{avatar}" style="width:42px;height:42px;border-radius:50%;object-fit:cover;">' if avatar else f'<div class="avatar-placeholder">{username[0].upper()}</div>'
    
    return f"""<!DOCTYPE html>
<html>
<head>
<title>WaClone</title>
{BASE_STYLE}
<style>
body{{display:flex;height:100vh;overflow:hidden;}}

/* ===== SIDEBAR ===== */
.sidebar{{width:375px;min-width:375px;background:var(--panel);display:flex;flex-direction:column;border-right:1px solid var(--border);}}
.sidebar-header{{padding:10px 16px;display:flex;align-items:center;gap:12px;background:var(--panel);border-bottom:1px solid var(--border);height:62px;}}
.sidebar-header .avatar-placeholder,.sidebar-header img{{width:42px;height:42px;border-radius:50%;object-fit:cover;background:var(--accent);display:flex;align-items:center;justify-content:center;font-weight:800;font-size:18px;cursor:pointer;color:#fff;flex-shrink:0;}}
.sidebar-header h2{{font-size:18px;font-weight:800;flex:1;}}
.header-actions{{display:flex;gap:4px;}}
.icon-btn{{width:40px;height:40px;border:none;background:transparent;color:var(--subtext);border-radius:50%;display:flex;align-items:center;justify-content:center;transition:.2s;position:relative;}}
.icon-btn:hover{{background:var(--hover);color:var(--text);}}
.badge{{position:absolute;top:4px;right:4px;background:var(--accent);color:#fff;border-radius:50%;width:16px;height:16px;font-size:10px;font-weight:800;display:flex;align-items:center;justify-content:center;}}

.search-bar{{padding:8px 12px;}}
.search-bar input{{width:100%;padding:9px 16px 9px 40px;border-radius:10px;background:var(--dark);font-size:14px;}}
.search-wrap{{position:relative;}}
.search-wrap svg{{position:absolute;left:12px;top:50%;transform:translateY(-50%);color:var(--subtext);}}

.contact-list{{flex:1;overflow-y:auto;}}
.contact-item{{display:flex;align-items:center;gap:12px;padding:10px 16px;cursor:pointer;border-bottom:1px solid var(--border);transition:.15s;}}
.contact-item:hover,.contact-item.active{{background:var(--hover);}}
.contact-avatar{{width:50px;height:50px;border-radius:50%;background:var(--accent);display:flex;align-items:center;justify-content:center;font-weight:800;font-size:20px;color:#fff;flex-shrink:0;position:relative;}}
.contact-avatar img{{width:50px;height:50px;border-radius:50%;object-fit:cover;}}
.online-dot{{position:absolute;bottom:2px;right:2px;width:12px;height:12px;background:#44c56a;border-radius:50%;border:2px solid var(--panel);}}
.contact-info{{flex:1;min-width:0;}}
.contact-name{{font-weight:700;font-size:15px;}}
.contact-preview{{font-size:13px;color:var(--subtext);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin-top:2px;}}
.contact-meta{{display:flex;flex-direction:column;align-items:flex-end;gap:4px;}}
.contact-time{{font-size:11px;color:var(--subtext);}}
.unread-badge{{background:var(--accent);color:#fff;border-radius:50%;width:20px;height:20px;font-size:11px;font-weight:800;display:flex;align-items:center;justify-content:center;}}

/* ===== TABS ===== */
.sidebar-tabs{{display:flex;border-bottom:1px solid var(--border);}}
.stab{{flex:1;padding:12px;text-align:center;font-size:13px;font-weight:700;color:var(--subtext);cursor:pointer;border-bottom:2px solid transparent;transition:.2s;}}
.stab.active{{color:var(--accent);border-bottom-color:var(--accent);}}

/* ===== MAIN AREA ===== */
.main{{flex:1;display:flex;flex-direction:column;background:var(--dark);position:relative;overflow:hidden;}}
.no-chat{{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;color:var(--subtext);}}
.no-chat svg{{opacity:.3;margin-bottom:24px;}}
.no-chat h2{{font-size:28px;font-weight:800;color:var(--text);margin-bottom:8px;}}
.no-chat p{{font-size:15px;}}

/* ===== CHAT AREA ===== */
.chat-header{{height:62px;background:var(--panel);display:flex;align-items:center;gap:12px;padding:0 16px;border-bottom:1px solid var(--border);flex-shrink:0;}}
.chat-header .avatar-placeholder,.chat-header img{{width:42px;height:42px;border-radius:50%;object-fit:cover;background:var(--accent);display:flex;align-items:center;justify-content:center;font-weight:800;font-size:18px;color:#fff;flex-shrink:0;cursor:pointer;}}
.chat-header-info{{flex:1;}}
.chat-header-info h3{{font-weight:800;font-size:16px;}}
.chat-header-info p{{font-size:12px;color:var(--accent);}}

.messages-area{{flex:1;overflow-y:auto;padding:20px 60px;display:flex;flex-direction:column;gap:4px;background:var(--dark);}}

/* WhatsApp chat background pattern */
.messages-area{{background-image:url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23ffffff' fill-opacity='0.02'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E");}}

.msg-row{{display:flex;margin:2px 0;}}
.msg-row.out{{justify-content:flex-end;}}
.msg-row.in{{justify-content:flex-start;}}
.bubble{{max-width:65%;padding:8px 12px 6px;border-radius:12px;font-size:14.5px;line-height:1.5;word-break:break-word;position:relative;box-shadow:0 1px 4px rgba(0,0,0,.3);}}
.msg-row.out .bubble{{background:var(--bubble-out);border-bottom-right-radius:3px;}}
.msg-row.in .bubble{{background:var(--bubble-in);border-bottom-left-radius:3px;}}
.bubble-time{{font-size:11px;color:rgba(255,255,255,.5);text-align:right;margin-top:4px;display:flex;align-items:center;justify-content:flex-end;gap:4px;}}
.status-icon{{font-size:13px;}}
.status-icon.read{{color:var(--blue);}}
.status-icon.delivered{{color:rgba(255,255,255,.5);}}
.status-icon.sent{{color:rgba(255,255,255,.5);}}

.bubble img{{max-width:240px;border-radius:8px;display:block;margin-bottom:4px;cursor:pointer;}}
.bubble a{{color:var(--blue);text-decoration:none;}}
.date-divider{{text-align:center;color:var(--subtext);font-size:12px;margin:12px 0;}}
.date-divider span{{background:rgba(255,255,255,.1);padding:4px 12px;border-radius:20px;}}

/* ===== INPUT BAR ===== */
.input-bar{{background:var(--panel);padding:10px 16px;display:flex;align-items:center;gap:12px;border-top:1px solid var(--border);flex-shrink:0;}}
.input-bar input[type=text]{{flex:1;padding:11px 18px;border-radius:24px;font-size:15px;background:var(--dark);border:1.5px solid var(--border);color:var(--text);transition:.2s;}}
.input-bar input[type=text]:focus{{border-color:var(--accent);}}
.send-btn{{width:46px;height:46px;border-radius:50%;background:var(--accent);border:none;display:flex;align-items:center;justify-content:center;transition:.2s;flex-shrink:0;}}
.send-btn:hover{{background:#009070;transform:scale(1.05);}}
.attach-btn{{width:40px;height:40px;border-radius:50%;background:transparent;border:none;color:var(--subtext);display:flex;align-items:center;justify-content:center;cursor:pointer;}}
.attach-btn:hover{{color:var(--text);background:var(--hover);border-radius:50%;}}

/* ===== PANELS ===== */
.panel-overlay{{position:fixed;inset:0;background:rgba(0,0,0,.5);z-index:100;display:none;align-items:center;justify-content:center;}}
.panel-overlay.open{{display:flex;}}
.panel-box{{background:var(--panel);border-radius:20px;width:380px;max-height:80vh;overflow-y:auto;border:1px solid var(--border);box-shadow:0 20px 60px rgba(0,0,0,.5);}}
.panel-head{{padding:20px 24px 0;display:flex;align-items:center;justify-content:space-between;}}
.panel-head h2{{font-size:20px;font-weight:800;}}
.close-btn{{background:var(--hover);border:none;color:var(--subtext);width:32px;height:32px;border-radius:50%;font-size:18px;display:flex;align-items:center;justify-content:center;}}
.close-btn:hover{{color:var(--text);}}
.panel-body{{padding:20px 24px;}}

/* ===== PROFILE PANEL ===== */
.profile-avatar-wrap{{text-align:center;margin-bottom:24px;}}
.profile-big-avatar{{width:100px;height:100px;border-radius:50%;background:var(--accent);margin:0 auto 12px;font-size:40px;font-weight:800;color:#fff;display:flex;align-items:center;justify-content:center;overflow:hidden;}}
.profile-big-avatar img{{width:100px;height:100px;object-fit:cover;}}
.profile-name{{font-size:22px;font-weight:800;}}
.profile-email{{color:var(--subtext);font-size:14px;}}
.edit-field{{margin-bottom:14px;}}
.edit-field label{{font-size:12px;font-weight:700;color:var(--accent);text-transform:uppercase;letter-spacing:.5px;display:block;margin-bottom:6px;}}
.edit-field input,.edit-field textarea{{width:100%;padding:10px 14px;border-radius:10px;background:var(--dark);border:1.5px solid var(--border);color:var(--text);font-size:14px;font-family:'Nunito',sans-serif;}}
.edit-field textarea{{resize:none;height:80px;line-height:1.5;}}
.edit-field input:focus,.edit-field textarea:focus{{border-color:var(--accent);}}
.save-btn{{width:100%;padding:12px;background:var(--accent);color:#fff;border:none;border-radius:10px;font-size:15px;font-weight:800;margin-top:8px;}}
.save-btn:hover{{background:#009070;}}
.logout-btn{{width:100%;padding:12px;background:transparent;color:var(--red);border:1.5px solid var(--red);border-radius:10px;font-size:15px;font-weight:800;margin-top:10px;}}
.logout-btn:hover{{background:var(--red);color:#fff;}}

/* ===== NOTIF PANEL ===== */
.notif-item{{display:flex;gap:12px;align-items:center;padding:12px 0;border-bottom:1px solid var(--border);cursor:pointer;}}
.notif-item:last-child{{border-bottom:none;}}
.notif-avatar{{width:44px;height:44px;border-radius:50%;background:var(--accent);display:flex;align-items:center;justify-content:center;font-weight:800;font-size:18px;color:#fff;flex-shrink:0;}}
.notif-body{{flex:1;}}
.notif-name{{font-weight:700;font-size:14px;}}
.notif-msg{{font-size:13px;color:var(--subtext);margin-top:2px;}}
.notif-time{{font-size:11px;color:var(--subtext);}}
.notif-dot{{width:10px;height:10px;background:var(--accent);border-radius:50%;flex-shrink:0;}}

/* ===== STATUS ===== */
.status-grid{{display:grid;grid-template-columns:1fr 1fr;gap:12px;}}
.status-card{{background:var(--dark);border-radius:12px;padding:16px;border:1px solid var(--border);position:relative;overflow:hidden;}}
.status-card .status-avatar{{width:48px;height:48px;border-radius:50%;background:var(--accent);display:flex;align-items:center;justify-content:center;font-weight:800;font-size:20px;color:#fff;margin-bottom:10px;border:3px solid var(--accent);}}
.status-card .status-name{{font-weight:700;font-size:13px;}}
.status-card .status-time{{font-size:11px;color:var(--subtext);}}
.status-card .online-indicator{{position:absolute;top:12px;right:12px;width:10px;height:10px;background:#44c56a;border-radius:50%;}}
.my-status-btn{{width:100%;padding:12px;background:var(--dark);border:2px dashed var(--border);border-radius:12px;color:var(--subtext);font-size:14px;font-weight:700;margin-bottom:16px;}}
.my-status-btn:hover{{border-color:var(--accent);color:var(--accent);}}
</style>
</head>
<body>
<!-- SIDEBAR -->
<div class="sidebar">
  <div class="sidebar-header">
    <div onclick="openProfile()" title="Profil kamu">
      {avatar_html}
    </div>
    <h2>WaClone</h2>
    <div class="header-actions">
      <button class="icon-btn" onclick="openStatus()" title="Status">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 14.5v-9l6 4.5-6 4.5z"/></svg>
      </button>
      <button class="icon-btn" onclick="openNotif()" title="Notifikasi" id="notif-btn">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M12 22c1.1 0 2-.9 2-2h-4c0 1.1.9 2 2 2zm6-6v-5c0-3.07-1.63-5.64-4.5-6.32V4c0-.83-.67-1.5-1.5-1.5s-1.5.67-1.5 1.5v.68C7.64 5.36 6 7.92 6 11v5l-2 2v1h16v-1l-2-2z"/></svg>
        <span class="badge" id="notif-badge" style="display:none">0</span>
      </button>
    </div>
  </div>
  
  <div class="sidebar-tabs">
    <div class="stab active" onclick="switchSideTab('chats')">ðŸ’¬ Chat</div>
    <div class="stab" onclick="switchSideTab('contacts')">ðŸ‘¥ Kontak</div>
  </div>

  <div class="search-bar">
    <div class="search-wrap">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor"><path d="M15.5 14h-.79l-.28-.27A6.471 6.471 0 0 0 16 9.5 6.5 6.5 0 1 0 9.5 16c1.61 0 3.09-.59 4.23-1.57l.27.28v.79l5 4.99L20.49 19l-4.99-5zm-6 0C7.01 14 5 11.99 5 9.5S7.01 5 9.5 5 14 7.01 14 9.5 11.99 14 9.5 14z"/></svg>
      <input type="text" placeholder="Cari atau mulai chat baru..." oninput="filterContacts(this.value)">
    </div>
  </div>

  <div class="contact-list" id="contact-list">
    <div style="padding:20px;text-align:center;color:var(--subtext);font-size:14px;">Memuat kontak...</div>
  </div>
</div>

<!-- MAIN -->
<div class="main" id="main">
  <div class="no-chat" id="no-chat">
    <svg width="120" height="120" viewBox="0 0 24 24" fill="currentColor"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm-2 12H6v-2h12v2zm0-3H6V9h12v2zm0-3H6V6h12v2z"/></svg>
    <h2>WaClone</h2>
    <p>Pilih chat untuk mulai berkirim pesan</p>
  </div>
  <div id="chat-area" style="display:none;flex-direction:column;height:100%;">
    <div class="chat-header" id="chat-header"></div>
    <div class="messages-area" id="messages-area"></div>
    <div class="input-bar">
      <label for="file-input" class="attach-btn" title="Kirim file">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M16.5 6v11.5c0 2.21-1.79 4-4 4s-4-1.79-4-4V5c0-1.38 1.12-2.5 2.5-2.5s2.5 1.12 2.5 2.5v10.5c0 .55-.45 1-1 1s-1-.45-1-1V6H10v9.5c0 1.38 1.12 2.5 2.5 2.5s2.5-1.12 2.5-2.5V5c0-2.21-1.79-4-4-4S7 2.79 7 5v12.5c0 3.04 2.46 5.5 5.5 5.5s5.5-2.46 5.5-5.5V6h-1.5z"/></svg>
      </label>
      <input type="file" id="file-input" style="display:none" onchange="handleFile(this)" accept="image/*,video/*,.pdf,.txt">
      <input type="text" id="msg-input" placeholder="Ketik pesan..." onkeydown="if(event.key==='Enter')sendMsg()">
      <button class="send-btn" onclick="sendMsg()">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="white"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
      </button>
    </div>
  </div>
</div>

<!-- PROFILE PANEL -->
<div class="panel-overlay" id="profile-panel">
  <div class="panel-box">
    <div class="panel-head">
      <h2>Profil Saya</h2>
      <button class="close-btn" onclick="closePanel('profile-panel')">âœ•</button>
    </div>
    <div class="panel-body">
      <div class="profile-avatar-wrap">
        <div class="profile-big-avatar" id="profile-big-avatar">
          {username[0].upper()}
        </div>
        <div class="profile-name">{username}</div>
        <div class="profile-email">{email}</div>
      </div>
      <div class="edit-field">
        <label>Username</label>
        <input id="edit-username" value="{username}">
      </div>
      <div class="edit-field">
        <label>Bio / Status</label>
        <textarea id="edit-bio">{bio}</textarea>
      </div>
      <div class="edit-field">
        <label>Foto Profil (URL)</label>
        <input id="edit-avatar" value="{avatar}" placeholder="https://...">
      </div>
      <button class="save-btn" onclick="saveProfile()">ðŸ’¾ Simpan Profil</button>
      <button class="logout-btn" onclick="doLogout()">ðŸšª Logout</button>
    </div>
  </div>
</div>

<!-- NOTIFICATIONS PANEL -->
<div class="panel-overlay" id="notif-panel">
  <div class="panel-box">
    <div class="panel-head">
      <h2>Notifikasi</h2>
      <button class="close-btn" onclick="closePanel('notif-panel');markNotifsRead()">âœ•</button>
    </div>
    <div class="panel-body" id="notif-list">
      <div style="text-align:center;color:var(--subtext);padding:20px;">Tidak ada notifikasi</div>
    </div>
  </div>
</div>

<!-- STATUS PANEL -->
<div class="panel-overlay" id="status-panel">
  <div class="panel-box">
    <div class="panel-head">
      <h2>Status</h2>
      <button class="close-btn" onclick="closePanel('status-panel')">âœ•</button>
    </div>
    <div class="panel-body" id="status-list">
      <div style="text-align:center;color:var(--subtext);padding:20px;">Memuat status...</div>
    </div>
  </div>
</div>

<!-- IMAGE PREVIEW -->
<div class="panel-overlay" id="img-preview" onclick="closePanel('img-preview')">
  <img id="preview-img" style="max-width:90vw;max-height:90vh;border-radius:12px;box-shadow:0 20px 60px rgba(0,0,0,.7);">
</div>

<div class="toast" id="toast"></div>

<script>
const ME = {{uid:"{uid}", username:"{username}"}};
let currentFriend = null;
let allUsers = [];
let pollTimer = null;

// ===== TOAST =====
function showToast(msg, dur=2500){{
  const t=document.getElementById('toast'); t.textContent=msg; t.classList.add('show');
  setTimeout(()=>t.classList.remove('show'), dur);
}}

// ===== PANEL =====
function openProfile(){{document.getElementById('profile-panel').classList.add('open');}}
function openNotif(){{document.getElementById('notif-panel').classList.add('open'); loadNotifications();}}
function openStatus(){{document.getElementById('status-panel').classList.add('open'); loadStatus();}}
function closePanel(id){{document.getElementById(id).classList.remove('open');}}

// ===== SIDEBAR TABS =====
let sideTab = 'chats';
function switchSideTab(t){{
  sideTab = t;
  document.querySelectorAll('.stab').forEach((e,i)=>e.classList.toggle('active', (t==='chats'&&i===0)||(t==='contacts'&&i===1)));
  renderContactList();
}}

// ===== LOAD USERS =====
async function loadUsers(){{
  const r = await fetch('/api/users');
  const d = await r.json();
  allUsers = d.users || [];
  renderContactList();
  checkNotifications();
}}

function filterContacts(q){{
  const items = document.querySelectorAll('.contact-item');
  items.forEach(it=>{{
    const name = it.dataset.name||'';
    it.style.display = name.toLowerCase().includes(q.toLowerCase()) ? '' : 'none';
  }});
}}

function renderContactList(){{
  const list = document.getElementById('contact-list');
  const others = allUsers.filter(u=>u.uid !== ME.uid);
  if(others.length===0){{list.innerHTML='<div style="padding:20px;text-align:center;color:var(--subtext);">Belum ada kontak terdaftar</div>'; return;}}
  
  const html = others.map(u=>{{
    const av = u.avatar ? `<img src="${{u.avatar}}" style="width:50px;height:50px;border-radius:50%;object-fit:cover;">` 
                        : `<div style="width:50px;height:50px;border-radius:50%;background:var(--accent);display:flex;align-items:center;justify-content:center;font-weight:800;font-size:20px;color:#fff;">${{u.username[0].toUpperCase()}}</div>`;
    const onlineDot = u.online ? '<div class="online-dot"></div>' : '';
    const preview = u.last_msg || (u.bio ? u.bio.substring(0,40) : 'Klik untuk chat');
    const timeStr = u.last_time ? formatTime(u.last_time) : '';
    const unread = u.unread_count > 0 ? `<div class="unread-badge">${{u.unread_count}}</div>` : '';
    return `<div class="contact-item" data-uid="${{u.uid}}" data-name="${{u.username}}" onclick="openChat('${{u.uid}}','${{u.username}}','${{u.avatar||''}}')">
      <div class="contact-avatar">${{av}}${{onlineDot}}</div>
      <div class="contact-info">
        <div class="contact-name">${{u.username}}</div>
        <div class="contact-preview">${{preview}}</div>
      </div>
      <div class="contact-meta">
        <div class="contact-time">${{timeStr}}</div>
        ${{unread}}
      </div>
    </div>`;
  }}).join('');
  list.innerHTML = html;
}}

function formatTime(ts){{
  const d = new Date(ts*1000);
  const now = new Date();
  if(d.toDateString()===now.toDateString())
    return d.getHours().toString().padStart(2,'0')+':'+d.getMinutes().toString().padStart(2,'0');
  const diff = Math.floor((now-d)/86400000);
  if(diff===1) return 'Kemarin';
  if(diff<7) return ['Min','Sen','Sel','Rab','Kam','Jum','Sab'][d.getDay()];
  return d.getDate()+'/'+(d.getMonth()+1);
}}

// ===== OPEN CHAT =====
function openChat(friendUid, friendName, friendAvatar){{
  currentFriend = {{uid: friendUid, name: friendName, avatar: friendAvatar}};
  document.getElementById('no-chat').style.display = 'none';
  const ca = document.getElementById('chat-area');
  ca.style.display = 'flex';
  
  const av = friendAvatar 
    ? `<img src="${{friendAvatar}}" style="width:42px;height:42px;border-radius:50%;object-fit:cover;">`
    : `<div style="width:42px;height:42px;border-radius:50%;background:var(--accent);display:flex;align-items:center;justify-content:center;font-weight:800;font-size:18px;color:#fff;">${{friendName[0].toUpperCase()}}</div>`;
  
  document.getElementById('chat-header').innerHTML = `
    ${{av}}
    <div class="chat-header-info">
      <h3>${{friendName}}</h3>
      <p id="friend-status">Sedang online...</p>
    </div>
    <div style="display:flex;gap:4px;">
      <button class="icon-btn" title="Info kontak" onclick="showContactInfo('${{friendUid}}')">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-6h2v6zm0-8h-2V7h2v2z"/></svg>
      </button>
    </div>
  `;
  
  document.querySelectorAll('.contact-item').forEach(e=>e.classList.toggle('active', e.dataset.uid===friendUid));
  loadMessages();
  
  if(pollTimer) clearInterval(pollTimer);
  pollTimer = setInterval(loadMessages, 3000);
  
  fetch('/api/mark_read', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{friend_uid: friendUid}})}});
}}

// ===== LOAD MESSAGES =====
async function loadMessages(){{
  if(!currentFriend) return;
  const r = await fetch(`/api/messages?friend_uid=${{currentFriend.uid}}`);
  const d = await r.json();
  renderMessages(d.messages || []);
  
  // update friend status
  const friend = allUsers.find(u=>u.uid===currentFriend.uid);
  if(friend){{
    const sel = document.getElementById('friend-status');
    if(sel) sel.textContent = friend.online ? 'ðŸŸ¢ Online' : (friend.last_seen ? `Terakhir dilihat ${{formatTime(friend.last_seen)}}` : 'Offline');
  }}
}}

function renderMessages(msgs){{
  const area = document.getElementById('messages-area');
  const wasBottom = area.scrollHeight - area.clientHeight <= area.scrollTop + 50;
  
  let html = '';
  let lastDate = '';
  msgs.forEach(m=>{{
    const d = new Date(m.time*1000);
    const dateStr = d.toLocaleDateString('id-ID', {{day:'2-digit',month:'long',year:'numeric'}});
    if(dateStr !== lastDate){{
      html += `<div class="date-divider"><span>${{dateStr}}</span></div>`;
      lastDate = dateStr;
    }}
    const isOut = m.from === ME.uid;
    const timeStr = d.getHours().toString().padStart(2,'0')+':'+d.getMinutes().toString().padStart(2,'0');
    
    let statusIcon = '';
    if(isOut){{
      if(m.status==='read') statusIcon='<span class="status-icon read">âœ“âœ“</span>';
      else if(m.status==='delivered') statusIcon='<span class="status-icon delivered">âœ“âœ“</span>';
      else statusIcon='<span class="status-icon sent">âœ“</span>';
    }}
    
    let content = '';
    if(m.file){{
      const ft = m.file_type || '';
      if(ft.startsWith('image/')||/\.(jpg|jpeg|png|gif|webp)$/i.test(m.file))
        content += `<img src="${{m.file}}" onclick="previewImg('${{m.file}}')" alt="foto">`;
      else
        content += `<a href="${{m.file}}" target="_blank">ðŸ“Ž Buka file</a><br>`;
    }}
    if(m.message) content += m.message;
    
    html += `<div class="msg-row ${{isOut?'out':'in'}}">
      <div class="bubble">
        ${{content}}
        <div class="bubble-time">${{timeStr}} ${{statusIcon}}</div>
      </div>
    </div>`;
  }});
  
  area.innerHTML = html || '<div style="text-align:center;color:var(--subtext);padding:40px;font-size:14px;">Belum ada pesan. Mulai percakapan! ðŸ‘‹</div>';
  if(wasBottom) area.scrollTop = area.scrollHeight;
}}

function previewImg(src){{
  document.getElementById('preview-img').src=src;
  document.getElementById('img-preview').classList.add('open');
}}

// ===== SEND MESSAGE =====
async function sendMsg(){{
  const input = document.getElementById('msg-input');
  const text = input.value.trim();
  if(!text || !currentFriend) return;
  input.value='';
  
  const r = await fetch('/api/send', {{
    method:'POST', 
    headers:{{'Content-Type':'application/json'}},
    body: JSON.stringify({{to_uid: currentFriend.uid, message: text}})
  }});
  const d = await r.json();
  if(d.ok) loadMessages();
  else showToast('Gagal kirim pesan ðŸ˜•');
}}

// ===== SEND FILE =====
async function handleFile(input){{
  if(!input.files[0]||!currentFriend) return;
  const fd = new FormData();
  fd.append('file', input.files[0]);
  fd.append('to_uid', currentFriend.uid);
  showToast('Mengupload file... â³');
  const r = await fetch('/api/send_file', {{method:'POST', body:fd}});
  const d = await r.json();
  if(d.ok){{showToast('File terkirim! ðŸ“Ž'); loadMessages();}}
  else showToast('Gagal upload file ðŸ˜•');
  input.value='';
}}

// ===== PROFILE =====
async function saveProfile(){{
  const fd = new FormData();
  fd.append('username', document.getElementById('edit-username').value);
  fd.append('bio', document.getElementById('edit-bio').value);
  fd.append('avatar', document.getElementById('edit-avatar').value);
  const r = await fetch('/api/update_profile', {{method:'POST', body:fd}});
  const d = await r.json();
  if(d.ok){{showToast('Profil disimpan! âœ…'); closePanel('profile-panel'); setTimeout(()=>location.reload(),800);}}
  else showToast('Gagal simpan profil ðŸ˜•');
}}

function doLogout(){{
  fetch('/logout', {{method:'POST'}}).then(()=>location.href='/');
}}

// ===== NOTIFICATIONS =====
async function checkNotifications(){{
  const r = await fetch('/api/notifications');
  const d = await r.json();
  const count = (d.notifications||[]).filter(n=>!n.read).length;
  const badge = document.getElementById('notif-badge');
  badge.style.display = count>0 ? '' : 'none';
  badge.textContent = count;
}}

async function loadNotifications(){{
  const r = await fetch('/api/notifications');
  const d = await r.json();
  const list = document.getElementById('notif-list');
  const notifs = d.notifications || [];
  if(notifs.length===0){{list.innerHTML='<div style="text-align:center;color:var(--subtext);padding:20px;">Tidak ada notifikasi ðŸŽ‰</div>'; return;}}
  list.innerHTML = notifs.reverse().map(n=>{{
    const sender = allUsers.find(u=>u.uid===n.from);
    const name = sender?.username || 'Pengguna';
    return `<div class="notif-item" onclick="closePanel('notif-panel');openChat('${{n.from}}','${{name}}','${{sender?.avatar||''}}')">
      <div class="notif-avatar">${{name[0].toUpperCase()}}</div>
      <div class="notif-body">
        <div class="notif-name">${{name}}</div>
        <div class="notif-msg">${{n.message}}</div>
        <div class="notif-time">${{formatTime(n.time)}}</div>
      </div>
      ${{!n.read ? '<div class="notif-dot"></div>' : ''}}
    </div>`;
  }}).join('');
}}

async function markNotifsRead(){{
  await fetch('/api/notifications/read', {{method:'POST'}});
  checkNotifications();
}}

// ===== STATUS =====
async function loadStatus(){{
  const r = await fetch('/api/users');
  const d = await r.json();
  const users = (d.users||[]).filter(u=>u.uid!==ME.uid);
  const list = document.getElementById('status-list');
  if(users.length===0){{list.innerHTML='<div style="text-align:center;color:var(--subtext);padding:20px;">Belum ada pengguna lain</div>'; return;}}
  list.innerHTML = `<div class="status-grid">${{users.map(u=>{{
    const av = u.avatar 
      ? `<img src="${{u.avatar}}" style="width:48px;height:48px;border-radius:50%;object-fit:cover;border:3px solid var(--accent);">`
      : `<div class="status-avatar">${{u.username[0].toUpperCase()}}</div>`;
    return `<div class="status-card">
      ${{u.online ? '<div class="online-indicator"></div>' : ''}}
      ${{av}}
      <div class="status-name">${{u.username}}</div>
      <div class="status-time">${{u.online ? 'ðŸŸ¢ Online' : (u.last_seen ? `Dilihat ${{formatTime(u.last_seen)}}` : 'âš« Offline')}}</div>
      <div style="font-size:12px;color:var(--subtext);margin-top:4px;">${{(u.bio||'').substring(0,50)}}</div>
    </div>`;
  }}).join('')}}</div>`;
}}

function showContactInfo(uid){{
  const u = allUsers.find(x=>x.uid===uid);
  if(!u) return;
  showToast(`ðŸ‘¤ ${{u.username}} â€” ${{u.bio||'Tidak ada bio'}}`);
}}

// ===== PRESENCE =====
async function updatePresence(){{
  await fetch('/api/presence', {{method:'POST'}});
}}

// ===== INIT =====
loadUsers();
updatePresence();
setInterval(()=>{{loadUsers(); checkNotifications(); updatePresence();}}, 8000);
</script>
</body>
</html>"""

# ===============================
# ROUTES
# ===============================

@app.route("/")
def index():
    user = get_current_user(request)
    if user:
        return redirect("/home")
    return AUTH_PAGE

@app.route("/home")
def home():
    user = get_current_user(request)
    if not user:
        return redirect("/")
    return main_app_html(user)

@app.route("/register", methods=["POST"])
def register():
    username = request.form.get("username","").strip()
    email = request.form.get("email","").strip()
    password = request.form.get("password","")
    if not username or not email or not password:
        return jsonify({"ok": False, "msg": "Semua field harus diisi"})
    if len(password) < 6:
        return jsonify({"ok": False, "msg": "Password minimal 6 karakter"})
    try:
        existing = db.collection("users").where("username","==",username).get()
        if existing:
            return jsonify({"ok": False, "msg": "Username sudah dipakai"})
        try:
            auth.get_user_by_email(email)
            return jsonify({"ok": False, "msg": "Email sudah terdaftar"})
        except auth.UserNotFoundError:
            pass
        firebase_user = auth.create_user(email=email, password=password)
        hashed = generate_password_hash(password)
        db.collection("users").document(firebase_user.uid).set({
            "uid": firebase_user.uid,
            "username": username,
            "email": email,
            "password": hashed,
            "bio": "Hey there! I am using WaClone.",
            "avatar": "",
            "online": True,
            "last_seen": int(time.time()),
            "created_at": int(time.time())
        })
        # Auto-login: set cookie langsung setelah register berhasil
        resp = make_response(jsonify({"ok": True}))
        resp.set_cookie("uid", firebase_user.uid, max_age=7*24*3600, httponly=True)
        return resp
    except Exception as e:
        print("Register error:", e, file=sys.stderr)
        return jsonify({"ok": False, "msg": str(e)})

@app.route("/login", methods=["POST"])
def login():
    email = request.form.get("email","").strip()
    password = request.form.get("password","")
    if not email or not password:
        return jsonify({"ok": False, "msg": "Email/password kosong"})
    try:
        users = db.collection("users").where("email","==",email).get()
        if not users:
            return jsonify({"ok": False, "msg": "Email tidak ditemukan"})
        user = users[0].to_dict()
        if check_password_hash(user.get("password",""), password):
            uid = user.get("uid")
            db.collection("users").document(uid).update({"online": True, "last_seen": int(time.time())})
            resp = make_response(jsonify({"ok": True}))
            resp.set_cookie("uid", uid, max_age=7*24*3600, httponly=True)
            return resp
        return jsonify({"ok": False, "msg": "Password salah"})
    except Exception as e:
        print("Login error:", e, file=sys.stderr)
        return jsonify({"ok": False, "msg": "Login gagal"})

@app.route("/logout", methods=["POST"])
def logout():
    user = get_current_user(request)
    if user:
        db.collection("users").document(user["uid"]).update({"online": False, "last_seen": int(time.time())})
    resp = make_response(jsonify({"ok": True}))
    resp.set_cookie("uid", "", expires=0)
    return resp

# ===== API =====
@app.route("/api/users")
def api_users():
    user = get_current_user(request)
    if not user: return jsonify({"users": []})
    try:
        docs = db.collection("users").stream()
        current_uid = user["uid"]
        users = []
        for d in docs:
            u = d.to_dict()
            if u.get("uid") == current_uid:
                continue
            # get unread count
            chat_id = "_".join(sorted([current_uid, u["uid"]]))
            unread = 0
            try:
                unread_msgs = db.collection("chats").document(chat_id).collection("messages")\
                    .where("to","==",current_uid).where("status","!=","read").stream()
                unread = sum(1 for _ in unread_msgs)
            except: pass
            # get last message
            last_msg = ""
            last_time = 0
            try:
                chat_doc = db.collection("chats").document(chat_id).get()
                if chat_doc.exists:
                    cd = chat_doc.to_dict()
                    last_msg = cd.get("last_message","")
                    last_time = cd.get("last_time", 0)
            except: pass
            users.append({
                "uid": u.get("uid"),
                "username": u.get("username",""),
                "bio": u.get("bio",""),
                "avatar": u.get("avatar",""),
                "online": u.get("online", False),
                "last_seen": u.get("last_seen", 0),
                "unread_count": unread,
                "last_msg": last_msg,
                "last_time": last_time
            })
        users.sort(key=lambda x: x.get("last_time",0), reverse=True)
        return jsonify({"users": users})
    except Exception as e:
        return jsonify({"users": [], "error": str(e)})

@app.route("/api/messages")
def api_messages():
    user = get_current_user(request)
    if not user: return jsonify({"messages": []})
    friend_uid = request.args.get("friend_uid")
    if not friend_uid: return jsonify({"messages": []})
    msgs = load_messages(user["uid"], friend_uid)
    return jsonify({"messages": msgs})

@app.route("/api/send", methods=["POST"])
def api_send():
    user = get_current_user(request)
    if not user: return jsonify({"ok": False})
    data = request.get_json()
    to_uid = data.get("to_uid")
    message = data.get("message","").strip()
    if not to_uid or not message: return jsonify({"ok": False})
    save_message(user["uid"], to_uid, message)
    return jsonify({"ok": True})

@app.route("/api/send_file", methods=["POST"])
def api_send_file():
    user = get_current_user(request)
    if not user: return jsonify({"ok": False})
    to_uid = request.form.get("to_uid")
    f = request.files.get("file")
    if not f or not to_uid: return jsonify({"ok": False})
    if not allowed_file(f.filename): return jsonify({"ok": False, "msg": "Tipe file tidak diizinkan"})
    try:
        unique_name = f"{int(time.time())}_{f.filename}"
        blob = bucket.blob(f"chats/{unique_name}")
        blob.upload_from_file(f.stream, content_type=f.content_type)
        blob.make_public()
        file_url = blob.public_url
        save_message(user["uid"], to_uid, "", file_url=file_url, file_type=f.content_type)
        return jsonify({"ok": True, "file_url": file_url})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})

@app.route("/api/mark_read", methods=["POST"])
def api_mark_read():
    user = get_current_user(request)
    if not user: return jsonify({"ok": False})
    data = request.get_json()
    friend_uid = data.get("friend_uid")
    if friend_uid:
        mark_messages_read(user["uid"], friend_uid)
    return jsonify({"ok": True})

@app.route("/api/notifications")
def api_notifications():
    user = get_current_user(request)
    if not user: return jsonify({"notifications": []})
    try:
        notifs = db.collection("notifications").where("to","==",user["uid"]).order_by("time").limit(50).stream()
        return jsonify({"notifications": [n.to_dict() for n in notifs]})
    except Exception as e:
        return jsonify({"notifications": []})

@app.route("/api/notifications/read", methods=["POST"])
def api_notifs_read():
    user = get_current_user(request)
    if not user: return jsonify({"ok": False})
    try:
        notifs = db.collection("notifications").where("to","==",user["uid"]).where("read","==",False).stream()
        for n in notifs:
            n.reference.update({"read": True})
        return jsonify({"ok": True})
    except:
        return jsonify({"ok": False})

@app.route("/api/update_profile", methods=["POST"])
def api_update_profile():
    user = get_current_user(request)
    if not user: return jsonify({"ok": False})
    username = request.form.get("username","").strip()
    bio = request.form.get("bio","").strip()
    avatar = request.form.get("avatar","").strip()
    try:
        update_data = {"bio": bio, "avatar": avatar}
        if username and username != user.get("username"):
            existing = db.collection("users").where("username","==",username).get()
            if existing and existing[0].id != user["uid"]:
                return jsonify({"ok": False, "msg": "Username sudah dipakai"})
            update_data["username"] = username
        db.collection("users").document(user["uid"]).update(update_data)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})

@app.route("/api/presence", methods=["POST"])
def api_presence():
    user = get_current_user(request)
    if not user: return jsonify({"ok": False})
    try:
        db.collection("users").document(user["uid"]).update({
            "online": True,
            "last_seen": int(time.time())
        })
    except: pass
    return jsonify({"ok": True})

# ===============================
# RUN SERVER
# ===============================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)