from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()

class QRCode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(20), nullable=False)  # 'alipay' or 'wechat'
    filename = db.Column(db.String(255), nullable=False)
    active = db.Column(db.Boolean, default=True)
    remark = db.Column(db.String(255))