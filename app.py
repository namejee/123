from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os
import random
from datetime import datetime, timedelta
import click
from itertools import groupby
from sqlalchemy import func
import logging
from logging.handlers import RotatingFileHandler

# 创建 logs 目录
os.makedirs('logs', exist_ok=True)

# 配置日志
formatter = logging.Formatter(
    '[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
)

# 文件处理器 - 记录所有日志
file_handler = RotatingFileHandler(
    'logs/app.log', 
    maxBytes=1024 * 1024,  # 1MB
    backupCount=10
)
file_handler.setFormatter(formatter)
file_handler.setLevel(logging.INFO)

# 错误日志处理器 - 只记录错误
error_handler = RotatingFileHandler(
    'logs/error.log',
    maxBytes=1024 * 1024,
    backupCount=10
)
error_handler.setFormatter(formatter)
error_handler.setLevel(logging.ERROR)

# 配置 Flask 应用的日志
app = Flask(__name__)
app.logger.addHandler(file_handler)
app.logger.addHandler(error_handler)
app.logger.setLevel(logging.INFO)

app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'your-secret-key-goes-here')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///payment.db')
app.config['UPLOAD_FOLDER'] = 'static/qrcodes'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

db = SQLAlchemy(app)

# 数据模型
class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(120), nullable=False)

class QRCode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(20), nullable=False)  # 'alipay' or 'wechat'
    filename = db.Column(db.String(255), nullable=False)
    active = db.Column(db.Boolean, default=True)
    remark = db.Column(db.String(255))  # 添加备注字段

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    id_card = db.Column(db.String(18), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    payment_method = db.Column(db.String(20), nullable=False)
    qrcode_filename = db.Column(db.String(255))  # 添加二维码文件名
    qrcode_remark = db.Column(db.String(255))    # 添加二维码备注
    created_at = db.Column(db.DateTime, default=datetime.now)

# 路由
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/recharge', methods=['GET', 'POST'])
def recharge():
    if request.method == 'POST':
        name = request.form.get('name')
        phone = request.form.get('phone')
        id_card = request.form.get('id_card')
        amount = request.form.get('amount')
        payment_method = request.form.get('payment_method')
        
        # 获取所有可用的二维码并按ID排序
        qrcodes = QRCode.query.filter_by(type=payment_method, active=True).order_by(QRCode.id).all()
        if not qrcodes:
            flash('支付方式暂不可用')
            return redirect(url_for('recharge'))
        
        # 从session中获取当前索引，如果没有则初始化为0
        current_index = session.get('qrcode_index', 0)
        
        # 获取当前二维码并更新索引
        qrcode = qrcodes[current_index % len(qrcodes)]
        session['qrcode_index'] = (current_index + 1) % len(qrcodes)
            
        return render_template('payment.html', 
                               qrcode=qrcode,
                               name=name,
                               phone=phone,
                               id_card=id_card,
                               amount=amount,
                               payment_method=payment_method)
    
    return render_template('recharge.html')

@app.route('/complete_payment', methods=['POST'])
def complete_payment():
    try:
        name = request.form.get('name')
        phone = request.form.get('phone')
        id_card = request.form.get('id_card')
        amount = float(request.form.get('amount'))
        payment_method = request.form.get('payment_method')
        qrcode_filename = request.form.get('qrcode_filename')
        qrcode_remark = request.form.get('qrcode_remark')
        
        order_number = datetime.now().strftime('%Y%m%d%H%M%S') + str(random.randint(1000, 9999))
        
        order = Order(
            order_number=order_number,
            name=name,
            phone=phone,
            id_card=id_card,
            amount=amount,
            payment_method=payment_method,
            qrcode_filename=qrcode_filename,
            qrcode_remark=qrcode_remark
        )
        
        db.session.add(order)
        db.session.commit()
        
        app.logger.info(f'订单创建成功: {order_number}, 金额: {amount}')
        return jsonify({'success': True, 'order_number': order_number})
    except Exception as e:
        app.logger.error(f'订单创建失败: {str(e)}')
        return jsonify({'success': False, 'message': '订单创建失败'})

# 管理员路由
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        admin = Admin.query.filter_by(username=username).first()
        if admin and check_password_hash(admin.password_hash, password):
            session['admin_logged_in'] = True
            app.logger.info(f'管理员登录成功: {username}')
            return redirect(url_for('admin_dashboard'))
            
        app.logger.warning(f'管理员登录失败: {username}')
        flash('用户名或密码错误')
    return render_template('admin/login.html')

@app.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    return render_template('admin/dashboard.html')

@app.route('/admin/qrcodes', methods=['GET', 'POST'])
def admin_qrcodes():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
        
    if request.method == 'POST':
        try:
            file = request.files.get('qrcode')
            qrcode_type = request.form.get('type')
            remark = request.form.get('remark')
            
            if file and qrcode_type:
                timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
                filename = f"{qrcode_type}_{timestamp}_{secure_filename(file.filename)}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                
                qrcode = QRCode(type=qrcode_type, filename=filename, remark=remark)
                db.session.add(qrcode)
                db.session.commit()
                
                app.logger.info(f'二维码上传成功: {filename}')
                flash('二维码上传成功')
                return redirect(url_for('admin_qrcodes'))
        except Exception as e:
            app.logger.error(f'二维码上传失败: {str(e)}')
            flash('二维码上传失败')
            
    qrcodes = QRCode.query.all()
    return render_template('admin/qrcodes.html', qrcodes=qrcodes)

@app.route('/admin/qrcode/<int:id>/toggle', methods=['POST'])
def toggle_qrcode(id):
    if not session.get('admin_logged_in'):
        return jsonify({'success': False, 'message': '未登录'})
        
    qrcode = QRCode.query.get_or_404(id)
    qrcode.active = not qrcode.active
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/admin/qrcode/<int:id>/delete', methods=['POST'])
def delete_qrcode(id):
    if not session.get('admin_logged_in'):
        return jsonify({'success': False, 'message': '未登录'})
        
    qrcode = QRCode.query.get_or_404(id)
    
    # 删除文件
    try:
        os.remove(os.path.join(app.config['UPLOAD_FOLDER'], qrcode.filename))
    except OSError:
        pass  # 如果文件不存在则忽略
    
    # 删除数据库记录
    db.session.delete(qrcode)
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/admin/order/<int:id>/delete', methods=['POST'])
def delete_order(id):
    if not session.get('admin_logged_in'):
        return jsonify({'success': False, 'message': '未登录'})
        
    order = Order.query.get_or_404(id)
    db.session.delete(order)
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/admin/orders')
def admin_orders():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
        
    # 获取所有订单并关联二维码信息
    orders = Order.query.order_by(Order.created_at.desc()).all()
    # 获取所有二维码信息
    qrcodes = {(qr.type, qr.filename): qr for qr in QRCode.query.all()}
    return render_template('admin/orders.html', orders=orders, qrcodes=qrcodes)

@app.route('/admin/statistics')
def admin_statistics():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    
    # 获取查询参数
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    qrcode_remark = request.args.get('qrcode_remark')
    payment_method = request.args.get('payment_method')
    
    # 构建查询
    query = Order.query
    
    # 按条件筛选
    if start_date:
        query = query.filter(Order.created_at >= datetime.strptime(start_date, '%Y-%m-%d'))
    if end_date:
        end = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
        query = query.filter(Order.created_at < end)
    if qrcode_remark:
        query = query.filter(Order.qrcode_remark.ilike(f'%{qrcode_remark}%'))
    if payment_method:
        query = query.filter(Order.payment_method == payment_method)
    
    # 执行查询
    orders = query.all()
    
    # 计算统计数据
    stats = {
        'total_orders': len(orders),
        'total_amount': sum(order.amount for order in orders),
        'avg_amount': sum(order.amount for order in orders) / len(orders) if orders else 0,
        'qrcode_stats': []
    }
    
    # 按二维码备注分组统计
    if orders:
        orders_by_qrcode = groupby(
            sorted(orders, key=lambda x: x.qrcode_remark or ''),
            key=lambda x: x.qrcode_remark
        )
        for remark, group in orders_by_qrcode:
            group_list = list(group)
            stats['qrcode_stats'].append({
                'remark': remark,
                'count': len(group_list),
                'total': sum(order.amount for order in group_list),
                'average': sum(order.amount for order in group_list) / len(group_list)
            })
    
    return render_template('admin/statistics.html', stats=stats)

@app.route('/admin/logs')
def admin_logs():
    if not session.get('admin_logged_in'):
        return redirect(url_for('admin_login'))
    
    log_type = request.args.get('type', 'all')
    log_file = 'logs/error.log' if log_type == 'error' else 'logs/app.log'
    
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            logs = f.read()
    except Exception as e:
        logs = f'无法读取日志文件: {str(e)}'
        app.logger.error(f'日志查看失败: {str(e)}')
    
    return render_template('admin/logs.html', logs=logs)

@app.cli.command('clear-payment-data')
def clear_payment_data():
    """清空所有支付相关数据，包括订单记录"""
    if click.confirm('确定要清空所有支付数据吗？此操作不可恢复！'):
        Order.query.delete()
        db.session.commit()
        click.echo('所有支付数据已清空')

def init_db():
    with app.app_context():
        db.create_all()
        # 创建默认管理员账户
        if not Admin.query.filter_by(username='admin').first():
            admin = Admin(username='admin',
                         password_hash=generate_password_hash('Aadmin123'))
            db.session.add(admin)
            db.session.commit()

if __name__ == '__main__':
    # 确保上传目录存在
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    # 初始化数据库  
    init_db()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
    # 使用SSL证书运行HTTPS服务器
    # ssl_context = None
    # cert_path = os.environ.get('SSL_CERT_PATH')
    # key_path = os.environ.get('SSL_KEY_PATH')
    # if cert_path and key_path:
    #     ssl_context = (cert_path, key_path)
    # app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 443)), ssl_context=ssl_context)