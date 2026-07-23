from gevent import monkey
monkey.patch_all()

import gevent
import socket

# FIX PER RENDER + GEVENT: Forza la risoluzione DNS solo su IPv4
# Impedisce l'errore [Errno 101] Network is unreachable
orig_getaddrinfo = socket.getaddrinfo
def patched_getaddrinfo(host, port, family=0, *args, **kwargs):
    if family == 0 or family == socket.AF_UNSPEC:
        family = socket.AF_INET  # Forza IPv4 ed esclude IPv6
    return orig_getaddrinfo(host, port, family, *args, **kwargs)
socket.getaddrinfo = patched_getaddrinfo

import os
import threading
import werkzeug.utils
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, render_template, redirect, url_for, request, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from authlib.integrations.flask_client import OAuth
from flask_socketio import SocketIO, join_room, emit
from flask_mail import Mail, Message
from werkzeug.middleware.proxy_fix import ProxyFix

# Carica le variabili dal file .env
load_dotenv()

ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'default-dev-key')
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

# =========================================================
# CONFIGURAZIONE DATABASE POSTGRESQL (NEON CLOUD)
# =========================================================
NEON_DB_URL = "postgresql://neondb_owner:npg_dxSrXjnUl0g4@ep-autumn-field-asfmciz0-pooler.c-4.eu-central-1.aws.neon.tech/neondb?sslmode=require"

db_url = os.getenv('DATABASE_URL', NEON_DB_URL)

if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_pre_ping': True,
    'pool_recycle': 280,
}

# Configurazione Mail
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USE_TLS'] = False
app.config['MAIL_USE_SSL'] = True
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_USERNAME')

# Configurazione Upload File Chat
app.config['UPLOAD_FOLDER'] = os.path.join(app.root_path, 'static/uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)

# SocketIO ottimizzato con Eventlet
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='gevent',  # <--- Deve essere esattamente 'gevent'
    ping_timeout=60,
    ping_interval=25
)

mail = Mail(app)

login_manager = LoginManager(app)
login_manager.login_view = 'login'

# Configurazione Google OAuth protetta
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.getenv('GOOGLE_CLIENT_ID'), 
    client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),                   
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

# =========================================================
# MODELLI DATABASE
# =========================================================

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    google_id = db.Column(db.String(120), unique=True)
    name = db.Column(db.String(100))
    email = db.Column(db.String(120), unique=True, nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    requests = db.relationship('SiteRequest', backref='client', lazy=True)
    messages = db.relationship('ChatMessage', backref='sender', lazy=True)
    notifications = db.relationship('Notification', backref='user', lazy=True, cascade="all, delete-orphan")

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.String(255), nullable=False)
    category = db.Column(db.String(50), default='Info')
    link = db.Column(db.String(255), nullable=True)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class SiteRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    site_name = db.Column(db.String(100), nullable=False)
    business_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), default='In Attesa')
    cost = db.Column(db.Float, default=0.0)
    quote_accepted = db.Column(db.Boolean, default=False)
    periodic_amount = db.Column(db.Float, default=0.0)
    periodic_desc = db.Column(db.String(200), default='')
    periodic_accepted = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    messages = db.relationship('ChatMessage', backref='project', lazy=True, cascade="all, delete-orphan")

class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey('site_request.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    is_from_admin = db.Column(db.Boolean, default=False)
    content = db.Column(db.Text, nullable=False)
    attachment = db.Column(db.String(255), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    author_name = db.Column(db.String(100), nullable=False)
    site_name = db.Column(db.String(100), nullable=False)
    rating = db.Column(db.Float, nullable=False)
    description = db.Column(db.Text, nullable=False)
    approved = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# =========================================================
# CREAZIONE TABELLE AUTOMATICA
# =========================================================
with app.app_context():
    db.create_all()


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.context_processor
def inject_notifications():
    if current_user.is_authenticated:
        unread = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
        return dict(unread_notifications=unread)
    return dict(unread_notifications=0)


# =========================================================
# HELPER NOTIFICHE & EMAIL ASINCRONE
# =========================================================
def send_async_email_api(mail_username, mail_password, to_email, subject, body_text):
    """Invia l'email bypassando Flask-Mail e usando il modulo nativo."""
    try:
        import smtplib
        from email.mime.text import MIMEText
        from email.header import Header
        
        # FIX: Aggiunto 'utf-8' per impedire il blocco causato da lettere accentate (es. 'più')
        msg = MIMEText(body_text, 'plain', 'utf-8')
        msg['Subject'] = Header(subject, 'utf-8')
        msg['From'] = mail_username
        msg['To'] = to_email
        
        # Connessione pulita SSL sulla porta 465
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(mail_username, mail_password)
        server.sendmail(mail_username, [to_email], msg.as_string())
        server.quit()
        print(f"[EMAIL SUCCESS] Inviata con successo tramite socket nativo a {to_email}")
    except Exception as e:
        print(f"[EMAIL ERROR] Fallimento definitivo invio: {str(e)}")

def create_notification_and_email(user_id, message, category, link):
    user = User.query.get(user_id)
    if not user: 
        return
    
    notif = Notification(user_id=user.id, message=message, category=category, link=link)
    db.session.add(notif)
    
    mail_username = app.config.get('MAIL_USERNAME')
    mail_password = app.config.get('MAIL_PASSWORD')
    
    if user.email and mail_username and mail_password:
        try:
            subject = f"Aggiornamento Progetto: {category}"
            body_text = f"Ciao {user.name},\n\nHai ricevuto un nuovo aggiornamento:\n\n{message}\n\nAccedi alla piattaforma per visualizzare i dettagli."
            
            # Usiamo gevent.spawn per non bloccare la richiesta dell'utente
            gevent.spawn(send_async_email_api, mail_username, mail_password, user.email, subject, body_text)
        except Exception as e:
            print(f"[EMAIL PREPARATION ERROR] {e}")


# =========================================================
# ROTTE PRINCIPALI
# =========================================================
@app.route('/')
def home():
    reviews = Review.query.filter_by(approved=True).order_by(Review.created_at.desc()).all()
    return render_template('index.html', reviews=reviews)

@app.route('/login')
def login():
    redirect_uri = url_for('auth', _external=True)
    return google.authorize_redirect(redirect_uri)

@app.route('/auth')
def auth():
    token = google.authorize_access_token()
    user_info = token.get('userinfo') or token.get('id_token')

    user = User.query.filter_by(email=user_info['email']).first()
    
    # FIX: Utilizzo di .strip() per evitare bug legati a spazi accidentali nel .env
    admin_env = os.getenv("ADMIN_EMAIL", "").strip().lower()
    is_admin_check = True if admin_env and user_info['email'].lower() == admin_env else False

    if not user:
        user = User(
            google_id=user_info['sub'],
            name=user_info.get('name', 'Cliente'),
            email=user_info['email'],
            is_admin=is_admin_check
        )
        db.session.add(user)
        db.session.commit()
    else:
        # FIX: Aggiorna l'account ad Admin se avevi loggato prima di correggere il .env
        if is_admin_check and not user.is_admin:
            user.is_admin = True
            db.session.commit()

    login_user(user)
    return redirect(url_for('admin' if user.is_admin else 'dashboard'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logout effettuato con successo.', 'info')
    return redirect(url_for('home'))

@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    if current_user.is_admin:
        return redirect(url_for('admin'))

    if request.method == 'POST':
        new_req = SiteRequest(
            user_id=current_user.id,
            site_name=request.form.get('site_name'),
            business_name=request.form.get('business_name'),
            phone=request.form.get('phone'),
            description=request.form.get('description')
        )
        db.session.add(new_req)
        
        # 1. NOTIFICA ED EMAIL ALL'ADMIN
        admin_user = User.query.filter_by(is_admin=True).first()
        if admin_user:
            create_notification_and_email(admin_user.id, f"Nuova commissione ricevuta da {current_user.name}: {new_req.site_name}", "Nuova Commissione", "/admin")
        elif os.getenv("ADMIN_EMAIL"):
            # Fallback di emergenza: manda l'email anche se l'admin non è registrato nel DB
            admin_email_raw = os.getenv("ADMIN_EMAIL").strip()
            gevent.spawn(send_async_email_api, app.config.get('MAIL_USERNAME'), app.config.get('MAIL_PASSWORD'), admin_email_raw, "Nuova Commissione", f"Nuova commissione ricevuta da {current_user.name}: {new_req.site_name}")
            
        # 2. NOTIFICA ED EMAIL AL CLIENTE
        create_notification_and_email(current_user.id, f"Grazie per la tua richiesta! Abbiamo preso in carico il progetto per '{new_req.site_name}'. Ti risponderemo al più presto.", "Conferma Ricezione", "/dashboard")

        db.session.commit()
        flash('Richiesta inviata con successo!', 'success')
        return redirect(url_for('dashboard'))

    user_requests = SiteRequest.query.filter_by(user_id=current_user.id).order_by(SiteRequest.created_at.desc()).all()
    return render_template('dashboard.html', requests=user_requests)

@app.route('/notifications')
@login_required
def notifications():
    user_notifs = Notification.query.filter_by(user_id=current_user.id).order_by(Notification.created_at.desc()).all()
    for n in user_notifs:
        n.is_read = True
    db.session.commit()
    return render_template('notifications.html', notifications=user_notifs)


# --- GESTIONE PREVENTIVI E STATI ---
@app.route('/dashboard/accept_quote/<int:request_id>', methods=['POST'])
@login_required
def accept_quote(request_id):
    req = SiteRequest.query.get_or_404(request_id)
    if req.user_id == current_user.id:
        req.quote_accepted = True
        admin_user = User.query.filter_by(is_admin=True).first()
        if admin_user:
            create_notification_and_email(admin_user.id, f"Il cliente {current_user.name} ha accettato il preventivo per {req.site_name}.", "Preventivo", "/admin")
        db.session.commit()
        flash('Preventivo accettato!', 'success')
    return redirect(url_for('dashboard'))

@app.route('/dashboard/accept_periodic/<int:request_id>', methods=['POST'])
@login_required
def accept_periodic(request_id):
    req = SiteRequest.query.get_or_404(request_id)
    if req.user_id == current_user.id:
        req.periodic_accepted = True
        admin_user = User.query.filter_by(is_admin=True).first()
        if admin_user:
            create_notification_and_email(admin_user.id, f"Il cliente {current_user.name} ha approvato il pagamento periodico per {req.site_name}.", "Preventivo", "/admin")
        db.session.commit()
        flash('Pagamento periodico accettato!', 'success')
    return redirect(url_for('dashboard'))


# --- ROTTE ADMIN ---
@app.route('/admin')
@login_required
def admin():
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    all_requests = SiteRequest.query.order_by(SiteRequest.created_at.desc()).all()
    all_reviews = Review.query.order_by(Review.created_at.desc()).all()
    
    client_users = User.query.filter(User.is_admin != True).all()
    
    return render_template('admin.html', requests=all_requests, reviews=all_reviews, users=client_users)

@app.route('/admin/user_profile/<int:user_id>')
@login_required
def user_profile(user_id):
    if not current_user.is_admin:
        return redirect(url_for('dashboard'))
    
    user = User.query.get_or_404(user_id)
    user_requests = SiteRequest.query.filter_by(user_id=user.id).order_by(SiteRequest.created_at.desc()).all()
    
    return render_template('user_profile.html', user=user, requests=user_requests)

@app.route('/admin/update_status/<int:request_id>', methods=['POST'])
@login_required
def update_status(request_id):
    if not current_user.is_admin: 
        return redirect(url_for('dashboard'))
        
    req = SiteRequest.query.get_or_404(request_id)
    
    old_status, old_cost, old_periodic_amount = req.status, req.cost, req.periodic_amount
    req.status = request.form.get('status')
    
    try: 
        req.cost = float(request.form.get('cost', 0))
    except ValueError: 
        pass
    
    if req.cost != old_cost: 
        req.quote_accepted = False
        create_notification_and_email(req.user_id, f"Il preventivo per '{req.site_name}' è stato modificato.", "Preventivo", "/dashboard")

    try: 
        req.periodic_amount = float(request.form.get('periodic_amount', 0))
    except ValueError: 
        pass
    
    if req.periodic_amount != old_periodic_amount: 
        req.periodic_accepted = False
        create_notification_and_email(req.user_id, f"Le condizioni di pagamento periodico per '{req.site_name}' sono cambiate.", "Preventivo", "/dashboard")
        
    req.periodic_desc = request.form.get('periodic_desc', '')
        
    if req.status != old_status:
        create_notification_and_email(req.user_id, f"Lo stato del progetto '{req.site_name}' è: {req.status}.", "Stato Lavoro", "/dashboard")
        
    db.session.commit()
    flash('Progetto aggiornato!', 'success')
    return redirect(url_for('admin'))

@app.route('/admin/delete/<int:request_id>', methods=['POST'])
@login_required
def delete_request(request_id):
    if not current_user.is_admin: 
        return redirect(url_for('dashboard'))
        
    req = SiteRequest.query.get_or_404(request_id)
    db.session.delete(req)
    db.session.commit()
    flash('Richiesta eliminata.', 'danger')
    return redirect(url_for('admin'))


# --- RECENSIONI ---
@app.route('/submit_review', methods=['POST'])
def submit_review():
    rating = float(request.form.get('rating', 0))
    new_rev = Review(
        author_name=request.form.get('author_name'),
        site_name=request.form.get('site_name'),
        rating=max(0, min(5, rating)),
        description=request.form.get('description')
    )
    db.session.add(new_rev)
    db.session.commit()
    flash('Recensione inviata con successo! Sarà visibile non appena approvata dall\'admin.', 'success')
    return redirect(request.referrer or url_for('home'))

@app.route('/admin/approve_review/<int:review_id>', methods=['POST'])
@login_required
def approve_review(review_id):
    if current_user.is_admin:
        rev = Review.query.get_or_404(review_id)
        rev.approved = True
        db.session.commit()
    return redirect(url_for('admin'))

@app.route('/admin/delete_review/<int:review_id>', methods=['POST'])
@login_required
def delete_review(review_id):
    if current_user.is_admin:
        rev = Review.query.get_or_404(review_id)
        db.session.delete(rev)
        db.session.commit()
    return redirect(url_for('admin'))


# --- CHAT ED ALLEGATI ---
@app.route('/chat/<int:request_id>')
@login_required
def chat(request_id):
    req = SiteRequest.query.get_or_404(request_id)
    if not current_user.is_admin and req.user_id != current_user.id:
        return redirect(url_for('dashboard'))
    messages = ChatMessage.query.filter_by(request_id=request_id).order_by(ChatMessage.timestamp.asc()).all()
    return render_template('chat.html', request=req, messages=messages)

@app.route('/chat/<int:request_id>/upload', methods=['POST'])
@login_required
def upload_chat_file(request_id):
    if 'file' not in request.files: 
        return jsonify({'success': False, 'error': 'Nessun file'})
    file = request.files['file']
    if file.filename == '': 
        return jsonify({'success': False, 'error': 'Nome file vuoto'})

    filename = werkzeug.utils.secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    new_msg = ChatMessage(
        request_id=request_id,
        user_id=current_user.id,
        content="File inviato",
        is_from_admin=current_user.is_admin,
        attachment=filename
    )
    db.session.add(new_msg)
    
    req = SiteRequest.query.get(request_id)
    target_id = req.user_id if current_user.is_admin else User.query.filter_by(is_admin=True).first().id
    if not Notification.query.filter_by(user_id=target_id, is_read=False, category="Chat").first():
        create_notification_and_email(target_id, f"Nuovo allegato in chat per {req.site_name}.", "Chat", f"/chat/{request_id}")
    
    db.session.commit()
    
    socketio.emit('receive_message', {
        'msg': new_msg.content, 
        'sender': current_user.name, 
        'is_admin': current_user.is_admin,
        'time': new_msg.timestamp.strftime('%H:%M'),
        'attachment': filename
    }, room=str(request_id))
    
    return jsonify({'success': True})

@socketio.on('join')
def on_join(data):
    join_room(str(data['room']))

@socketio.on('send_message')
def handle_message(data):
    room = str(data['room'])
    msg_content = data['message'].strip()
    if not msg_content: 
        return
        
    new_msg = ChatMessage(request_id=int(room), user_id=current_user.id, content=msg_content, is_from_admin=current_user.is_admin)
    db.session.add(new_msg)
    
    req = SiteRequest.query.get(int(room))
    target_id = req.user_id if current_user.is_admin else User.query.filter_by(is_admin=True).first().id
    if not Notification.query.filter_by(user_id=target_id, is_read=False, category="Chat", link=f"/chat/{room}").first():
        create_notification_and_email(target_id, f"Nuovo messaggio da {current_user.name} per {req.site_name}.", "Chat", f"/chat/{room}")
    
    db.session.commit()
    emit('receive_message', {'msg': msg_content, 'sender': current_user.name, 'is_admin': current_user.is_admin, 'time': new_msg.timestamp.strftime('%H:%M')}, room=room)


if __name__ == '__main__':
    socketio.run(app, debug=True)