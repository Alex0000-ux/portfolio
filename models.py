from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    google_id = db.Column(db.String(120), unique=True)
    name = db.Column(db.String(100))
    email = db.Column(db.String(120), unique=True, nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    requests = db.relationship('SiteRequest', backref='client', lazy=True)
    messages = db.relationship('ChatMessage', backref='sender', lazy=True)

class SiteRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    site_name = db.Column(db.String(100), nullable=False)
    business_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), default='Pending')
    cost = db.Column(db.Float, nullable=True)
    messages = db.relationship('ChatMessage', backref='project', lazy=True) # Collega la chat al progetto

class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    request_id = db.Column(db.Integer, db.ForeignKey('site_request.id'), nullable=False) # ID del sito a cui si riferisce
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    is_from_admin = db.Column(db.Boolean, default=False)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)