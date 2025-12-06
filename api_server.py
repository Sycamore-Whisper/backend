from flask import Flask, request, jsonify, abort
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone
from flask_cors import CORS
from flask import send_from_directory
import zipfile
from flask import send_file
from werkzeug.utils import secure_filename
import os
import shutil
import hashlib

# === Flask 初始化 ===
app = Flask(__name__)
CORS(app, supports_credentials=True)
DB_PATH = 'database.db'
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{DB_PATH}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)
def get_utc_now():
    """获取当前 UTC 时间"""
    return datetime.now(timezone.utc)


# === 模型定义 ===
class Submission(db.Model):
    __tablename__ = 'submissions'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True) 
    content = db.Column(db.Text, nullable=False)
    status = db.Column(db.Enum('Pass', 'Pending', 'Deny'), default='Pending')
    created_at = db.Column(db.DateTime, default=get_utc_now)
    updated_at = db.Column(db.DateTime, default=get_utc_now, onupdate=get_utc_now)
    upvotes = db.Column(db.Integer, default=0)
    downvotes = db.Column(db.Integer, default=0)

    comments = db.relationship('Comment', backref='submission', lazy=True, cascade='all, delete-orphan')


class Comment(db.Model):
    __tablename__ = 'comments'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    submission_id = db.Column(db.Integer, db.ForeignKey('submissions.id'), nullable=False)
    nickname = db.Column(db.String(50), default='匿名用户')
    content = db.Column(db.Text, nullable=False)
    parent_comment_id = db.Column(db.Integer, db.ForeignKey('comments.id'), default=0)
    created_at = db.Column(db.DateTime, default=get_utc_now)

    replies = db.relationship(
        'Comment',
        backref=db.backref('parent', remote_side=[id]),
        lazy=True,
        cascade='all, delete-orphan'
    )


class Report(db.Model):
    __tablename__ = 'reports'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    submission_id = db.Column(db.Integer, nullable=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    status = db.Column(db.Enum('Pass', 'Pending', 'Deny'), default='Pending')
    created_at = db.Column(db.DateTime, default=get_utc_now)


class Config(db.Model):
    __tablename__ = 'config'
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.String(200), nullable=False)


class Notice(db.Model):
    __tablename__ = 'notices'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    type = db.Column(db.Enum('md', 'url'), default='md', nullable=False)
    content = db.Column(db.Text, default='', nullable=False)
    version = db.Column(db.Integer, default=0, nullable=False)
    created_at = db.Column(db.DateTime, default=get_utc_now)
    updated_at = db.Column(db.DateTime, default=get_utc_now, onupdate=get_utc_now)



# === 工具函数 ===
def get_config(key, default=None):
    """从数据库获取配置值"""
    conf = Config.query.filter_by(key=key).first()
    return conf.value if conf else default


def set_config(key, value):
    """设置配置值"""
    conf = Config.query.filter_by(key=key).first()
    if conf:
        conf.value = str(value)
    else:
        conf = Config(key=key, value=str(value))
        db.session.add(conf)
    db.session.commit()


def ensure_default_notice():
    """确保至少存在一条公告记录"""
    try:
        existing = Notice.query.first()
        if not existing:
            n = Notice(type='md', content='', version=0)
            db.session.add(n)
            db.session.commit()
    except Exception:
        db.session.rollback()
        # 初始化失败时不抛出致命错误，交由后续请求重试创建


def get_current_notice():
    """获取当前公告，若不存在则返回默认结构"""
    n = Notice.query.order_by(Notice.id.asc()).first()
    if not n:
        return {"type": "md", "content": "", "version": 0}
    return {"type": n.type, "content": n.content, "version": int(n.version)}


# === 变量 ===
DEFAULT_BANNED_KEYWORDS = [
    "default"
]

# === 延迟初始化配置 ===
DEFAULT_ADMIN_TOKEN_HASH = hashlib.sha256("Sycamore_whisper".encode('utf-8')).hexdigest()
DEFAULT_UPLOAD_FOLDER = "img"
DEFAULT_ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
DEFAULT_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
DEFAULT_RATE_LIMIT = 10  # 次/分钟，0为无限制

CONFIG = {}
INIT = False
NEED_AUDIT = False

# 运行时使用的变量，初始为默认值
ADMIN_TOKEN_HASH = DEFAULT_ADMIN_TOKEN_HASH
UPLOAD_FOLDER = DEFAULT_UPLOAD_FOLDER
ALLOWED_EXTENSIONS = set(DEFAULT_ALLOWED_EXTENSIONS)
MAX_FILE_SIZE = DEFAULT_MAX_FILE_SIZE
BANNED_KEYWORDS = list(DEFAULT_BANNED_KEYWORDS)
RATE_LIMIT = DEFAULT_RATE_LIMIT

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'database.db')
IMG_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), UPLOAD_FOLDER)
BACKUP_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backups')
os.makedirs(BACKUP_FOLDER, exist_ok=True)

ALLOWED_BACKUP_EXTENSIONS = {'zip'}

def allowed_backup_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_BACKUP_EXTENSIONS

def apply_config_to_globals():
    global ADMIN_TOKEN_HASH, UPLOAD_FOLDER, ALLOWED_EXTENSIONS, MAX_FILE_SIZE, IMG_FOLDER, BANNED_KEYWORDS, RATE_LIMIT
    ADMIN_TOKEN_HASH = CONFIG.get('ADMIN_TOKEN_HASH', DEFAULT_ADMIN_TOKEN_HASH)
    UPLOAD_FOLDER = CONFIG.get('UPLOAD_FOLDER', DEFAULT_UPLOAD_FOLDER)
    ALLOWED_EXTENSIONS = set(CONFIG.get('ALLOWED_EXTENSIONS', DEFAULT_ALLOWED_EXTENSIONS))
    MAX_FILE_SIZE = int(CONFIG.get('MAX_FILE_SIZE', DEFAULT_MAX_FILE_SIZE))
    BANNED_KEYWORDS = list(CONFIG.get('BANNED_KEYWORDS', DEFAULT_BANNED_KEYWORDS))
    RATE_LIMIT = int(CONFIG.get('RATE_LIMIT', DEFAULT_RATE_LIMIT))
    IMG_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), UPLOAD_FOLDER)
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def load_config():
    global CONFIG, INIT
    try:
        import importlib, sys
        importlib.invalidate_caches()
        if 'config' in sys.modules:
            cfg = importlib.reload(sys.modules['config'])
        else:
            cfg = importlib.import_module('config')

        # 兼容性处理：如果只有 ADMIN_TOKEN 没有 ADMIN_TOKEN_HASH，则迁移
        admin_token_hash = getattr(cfg, 'ADMIN_TOKEN_HASH', None)
        if admin_token_hash is None:
            # 尝试从旧的 ADMIN_TOKEN 迁移
            old_token = getattr(cfg, 'ADMIN_TOKEN', None)
            if old_token is not None:
                # 对旧token做哈希
                admin_token_hash = hashlib.sha256(old_token.encode('utf-8')).hexdigest()
                # 重写配置文件，使用哈希值
                upload_folder = getattr(cfg, 'UPLOAD_FOLDER', DEFAULT_UPLOAD_FOLDER)
                allowed_extensions = set(getattr(cfg, 'ALLOWED_EXTENSIONS', DEFAULT_ALLOWED_EXTENSIONS))
                max_file_size = int(getattr(cfg, 'MAX_FILE_SIZE', DEFAULT_MAX_FILE_SIZE))
                banned_keywords = list(getattr(cfg, 'BANNED_KEYWORDS', DEFAULT_BANNED_KEYWORDS))
                rate_limit = int(getattr(cfg, 'RATE_LIMIT', DEFAULT_RATE_LIMIT))
                write_config_py(admin_token_hash, upload_folder, allowed_extensions, max_file_size, banned_keywords, rate_limit)
                # 重新加载配置
                importlib.invalidate_caches()
                cfg = importlib.reload(sys.modules['config'])
                admin_token_hash = getattr(cfg, 'ADMIN_TOKEN_HASH')

        CONFIG = {
            'ADMIN_TOKEN_HASH': admin_token_hash,
            'UPLOAD_FOLDER': getattr(cfg, 'UPLOAD_FOLDER'),
            'ALLOWED_EXTENSIONS': set(getattr(cfg, 'ALLOWED_EXTENSIONS')),
            'MAX_FILE_SIZE': int(getattr(cfg, 'MAX_FILE_SIZE')),
            'BANNED_KEYWORDS': list(getattr(cfg, 'BANNED_KEYWORDS', DEFAULT_BANNED_KEYWORDS)),
            'RATE_LIMIT': int(getattr(cfg, 'RATE_LIMIT', DEFAULT_RATE_LIMIT)),
        }
        INIT = True
        apply_config_to_globals()
    except Exception:
        INIT = False
        CONFIG = {}

# 启动时尝试加载配置
load_config()

# 全部接口在初始化完成前返回 503（仅 /init 允许）
@app.before_request
def gate_uninitialized():
    if request.path == '/init':
        return None
    global INIT
    # 若未初始化，尝试动态加载配置（兼容多进程/热重载场景）
    if not INIT:
        try:
            load_config()
        except Exception:
            pass
    if not INIT:
        return jsonify({"status": "Fail", "reason": "Uninitialized"}), 503

def write_config_py(token_hash, upload_folder, allowed_exts, max_file_size, banned_keywords=None, rate_limit=DEFAULT_RATE_LIMIT):
    # 归一化扩展名为小写且唯一
    exts = sorted(set(str(e).strip().lower() for e in allowed_exts if str(e).strip()))
    # 归一化敏感词为去空格的字符串列表
    banned = banned_keywords if banned_keywords is not None else DEFAULT_BANNED_KEYWORDS
    banned = [str(w).strip() for w in banned if str(w).strip()]
    content = (
        "# Auto-generated by /init\n"
        f"ADMIN_TOKEN_HASH = {repr(token_hash)}\n"
        f"UPLOAD_FOLDER = {repr(upload_folder)}\n"
        f"ALLOWED_EXTENSIONS = {repr(exts)}\n"
        f"MAX_FILE_SIZE = {int(max_file_size)}\n"
        f"BANNED_KEYWORDS = {repr(banned)}\n"
        f"RATE_LIMIT = {int(rate_limit)}\n"
    )
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.py')
    with open(config_path, 'w', encoding='utf-8') as f:
        f.write(content)

@app.route('/init', methods=['POST'])
def init_service():
    global INIT
    if INIT:
        return jsonify({"status": "Fail", "reason": "Already initialized"}), 403
    data = request.get_json() or {}
    required = ["ADMIN_TOKEN", "UPLOAD_FOLDER", "ALLOWED_EXTENSIONS", "MAX_FILE_SIZE", "RATE_LIMIT"]
    missing = [k for k in required if k not in data]
    if missing:
        return jsonify({"status": "Fail", "reason": f"Missing fields: {', '.join(missing)}"}), 400

    # 接收明文 token，在后端做哈希处理
    token = str(data["ADMIN_TOKEN"])
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    upload_folder = str(data["UPLOAD_FOLDER"]).strip()
    # 接受 list 或 逗号字符串
    exts = data["ALLOWED_EXTENSIONS"]
    if isinstance(exts, str):
        allowed_exts = [x.strip() for x in exts.split(',')]
    elif isinstance(exts, list):
        allowed_exts = exts
    else:
        return jsonify({"status": "Fail", "reason": "ALLOWED_EXTENSIONS must be list or comma string"}), 400

    try:
        max_file_size = int(data["MAX_FILE_SIZE"])
    except Exception:
        return jsonify({"status": "Fail", "reason": "MAX_FILE_SIZE must be int"}), 400

    # 必填的 RATE_LIMIT（次/分钟，0为无限制）
    try:
        rate_limit = int(data["RATE_LIMIT"])
        if rate_limit < 0:
            return jsonify({"status": "Fail", "reason": "RATE_LIMIT must be >= 0"}), 400
    except Exception:
        return jsonify({"status": "Fail", "reason": "RATE_LIMIT must be int"}), 400

    # 可选的 BANNED_KEYWORDS
    bk = data.get("BANNED_KEYWORDS", DEFAULT_BANNED_KEYWORDS)
    if isinstance(bk, str):
        banned_keywords = [x.strip() for x in bk.split(',') if x.strip()]
    elif isinstance(bk, list):
        banned_keywords = [str(x).strip() for x in bk if str(x).strip()]
    else:
        return jsonify({"status": "Fail", "reason": "BANNED_KEYWORDS must be list or comma string"}), 400

    try:
        write_config_py(token_hash, upload_folder, allowed_exts, max_file_size, banned_keywords, rate_limit)
        load_config()
        initialize_database()
        try:
            global NEED_AUDIT
            NEED_AUDIT = get_config("need_audit", "false").lower() == "true"
        except Exception:
            NEED_AUDIT = False
        return jsonify({"status": "OK"}), 200
    except Exception as e:
        return jsonify({"status": "Fail", "reason": str(e)}), 500

# === 限流（Rate Limit）实现 ===
RATE_LIMIT_STORE = {}

def get_client_ip():
    """在反向代理后正确获取客户端 IP。
    优先级：CF-Connecting-IP > X-Forwarded-For(首个) > X-Real-IP > remote_addr
    """
    ip = (
        request.headers.get('CF-Connecting-IP')
        or request.headers.get('X-Forwarded-For')
        or request.headers.get('X-Real-IP')
        or request.remote_addr
        or '127.0.0.1'
    )
    if isinstance(ip, str):
        # X-Forwarded-For 可能包含多个 IP，取第一个
        if ',' in ip:
            ip = ip.split(',')[0].strip()
        ip = ip.strip()
    return ip

def rate_limit_exceeded() -> bool:
    """返回是否超过限流。0 表示无限制。窗口从首次请求开始，持续 60 秒。"""
    if RATE_LIMIT == 0:
        return False
    ip = get_client_ip()
    ip_hash = hashlib.sha256(ip.encode('utf-8')).hexdigest()
    now = datetime.now(timezone.utc)
    rec = RATE_LIMIT_STORE.get(ip_hash)
    if rec is None:
        RATE_LIMIT_STORE[ip_hash] = {'count': 1, 'start': now}
        return False
    # 窗口超过 60 秒则重置
    if (now - rec['start']).total_seconds() >= 60:
        rec['count'] = 1
        rec['start'] = now
        return False
    # 累加计数并判断是否超过
    rec['count'] += 1
    return rec['count'] > RATE_LIMIT

def guard_rate_limit():
    """超过限流则返回 403，否则返回 None。"""
    if rate_limit_exceeded():
        return jsonify({"status": "Fail", "reason": "Rate Limit Exceeded"}), 403
    return None


# 在服务收到请求且已配置后，确保数据库表创建并加载审核状态
@app.before_request
def ensure_db_and_audit():
    global NEED_AUDIT
    if not getattr(ensure_db_and_audit, "_has_run", False) and INIT:
        try:
            initialize_database()
            try:
                NEED_AUDIT = get_config("need_audit", "false").lower() == "true"
            except Exception:
                NEED_AUDIT = False
        except Exception:
            pass
        finally:
            setattr(ensure_db_and_audit, "_has_run", True)


# === 管理端文章状态修改工具函数 ===
def admin_change_status(submission_id, from_status, to_status):
    submission = db.session.get(Submission, submission_id)
    if not submission:
        return False, "Post not found"
    if submission.status != from_status:
        return False, f"Post in wrong state"
    submission.status = to_status
    submission.updated_at = get_utc_now()
    db.session.commit()
    return True, None


# === 管理端接口 ===
def require_admin(func):
    """装饰器：检查 Bearer token"""
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"status": "Fail", "reason": "Token invalid"}), 401
        token = auth_header.split(" ", 1)[1]
        # 对传入的token做哈希后与配置文件中的哈希值比对
        token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
        if token_hash != ADMIN_TOKEN_HASH:
            return jsonify({"status": "Fail", "reason": "Token invalid"}), 403
        return func(*args, **kwargs)
    return wrapper

# === 路由 ===
@app.route('/post', methods=['POST'])
def submit_post():
    guard = guard_rate_limit()
    if guard is not None:
        return guard
    data = request.get_json()
    if not data or "content" not in data:
        return jsonify({"error": "Content not found"}), 400

    content = data["content"].strip()
    if not content:
        return jsonify({"error": "Content should not be null"}), 400

    # --- 违规检测 ---
    if any(bad_word in content for bad_word in BANNED_KEYWORDS):
        return jsonify({"status": "Deny"}), 403

    # --- 状态判断 ---
    need_audit = get_config("need_audit", "false").lower() == "true"
    status = "Pending" if need_audit else "Pass"

    submission = Submission(
        content=content,
        status=status,
        created_at=datetime.now(timezone.utc)
    )
    db.session.add(submission)
    db.session.commit()

    return jsonify({"id": submission.id, "status": submission.status}), 201

@app.route('/up', methods=['POST'])
def upvote():
    guard = guard_rate_limit()
    if guard is not None:
        return guard
    data = request.get_json()
    if not data or "id" not in data:
        return jsonify({"status": "Fail", "reason": "Value ID not found"}), 400

    submission = db.session.get(Submission, data["id"])
    if not submission:
        return jsonify({"status": "Fail", "reason": "Post not found"}), 404

    submission.upvotes += 1
    db.session.commit()
    return jsonify({"status": "OK"}), 200


@app.route('/get/notice', methods=['GET'])
def get_notice():
    """公开接口：获取当前公告内容与版本"""
    try:
        ensure_default_notice()
        return jsonify(get_current_notice()), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/admin/modify_notice', methods=['POST'])
@require_admin
def admin_modify_notice():
    """管理员接口：修改公告内容、类型与版本"""
    data = request.get_json() or {}
    n_type = str(data.get('type', 'md')).lower()
    content = str(data.get('content', ''))
    version = data.get('version', None)

    if n_type not in ['md', 'url']:
        return jsonify({"status": "Fail", "reason": "type must be 'md' or 'url'"}), 400

    try:
        ensure_default_notice()
        n = Notice.query.order_by(Notice.id.asc()).first()
        if not n:
            n = Notice(type=n_type, content=content, version=int(version or 0))
            db.session.add(n)
        else:
            n.type = n_type
            n.content = content
            if version is None:
                n.version = int(n.version) + 1
            else:
                try:
                    n.version = int(version)
                except Exception:
                    return jsonify({"status": "Fail", "reason": "version must be integer"}), 400
        db.session.commit()
        return jsonify({"status": "OK", "version": int(n.version)}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "Fail", "reason": str(e)}), 500


@app.route('/down', methods=['POST'])
def downvote():
    guard = guard_rate_limit()
    if guard is not None:
        return guard
    data = request.get_json()
    if not data or "id" not in data:
        return jsonify({"status": "Fail", "reason": "Value ID not found"}), 400

    submission = db.session.get(Submission, data["id"])
    if not submission:
        return jsonify({"status": "Fail", "reason": "Post not found"}), 404

    submission.downvotes += 1
    db.session.commit()
    return jsonify({"status": "OK"}), 200

@app.route('/comment', methods=['POST'])
def post_comment():
    guard = guard_rate_limit()
    if guard is not None:
        return guard
    data = request.get_json()
    required_fields = ["content", "submission_id", "parent_comment_id", "nickname"]
    if not all(field in data for field in required_fields):
        return jsonify({"id": None, "status": "Fail"}), 400

    content = data["content"].strip()
    submission_id = data["submission_id"]
    parent_comment_id = data["parent_comment_id"]
    nickname = data["nickname"].strip() or "匿名用户"

    # 检查投稿是否存在
    submission = db.session.get(Submission, submission_id)
    if not submission:
        return jsonify({"id": None, "status": "Fail"}), 404

    # 检查违规关键词
    if any(bad_word in content for bad_word in BANNED_KEYWORDS):
        return jsonify({"id": None, "status": "Deny"}), 403

    # 检查回复的评论是否合法
    if parent_comment_id != 0:
        reply_comment = db.session.get(Comment, parent_comment_id)
        if not reply_comment or reply_comment.submission_id != submission_id:
            return jsonify({"id": None, "status": "Wrong_Reply"}), 400

    # 创建评论
    comment = Comment(
        submission_id=submission_id,
        parent_comment_id=parent_comment_id,
        nickname=nickname,
        content=content,
        created_at=get_utc_now()
    )
    db.session.add(comment)
    db.session.commit()

    return jsonify({"id": comment.id, "status": "Pass"}), 200

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def random_string(length=5):
    import random, string
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

@app.route('/upload_pic', methods=['POST'])
def upload_pic():
    guard = guard_rate_limit()
    if guard is not None:
        return guard
    if 'file' not in request.files:
        return jsonify({"status": "Fail", "url": None}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"status": "Fail", "url": None}), 400

    if not allowed_file(file.filename):
        return jsonify({"status": "Wrong_Format", "url": None}), 400

    file.seek(0, os.SEEK_END)
    file_length = file.tell()
    file.seek(0)
    if file_length >= MAX_FILE_SIZE:
        return jsonify({"status": "Too_Large", "url": None}), 400

    ext = file.filename.rsplit('.', 1)[1].lower()
    date_str = datetime.now().strftime("%y%m%d")
    filename = f"{date_str}_{random_string()}.{ext}"
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)

    # 返回 URL
    url = f"/img/{filename}"
    return jsonify({"status": "OK", "url": url}), 201


@app.route('/img/<filename>', methods=['GET'])
def serve_image(filename):
    # 检测后缀
    if not allowed_file(filename):
        return 'Request not allowed', 403  # 后缀不允许
    # 返回图片
    return send_from_directory(UPLOAD_FOLDER, filename)


@app.route('/report', methods=['POST'])
def submit_report():
    guard = guard_rate_limit()
    if guard is not None:
        return guard
    data = request.get_json()
    if not data:
        return jsonify({"status": "Fail", "reason": "No data provided"}), 400

    # 必须包含的字段
    required_fields = ["id", "title", "content"]
    for field in required_fields:
        if field not in data:
            return jsonify({"status": "Fail", "reason": f"{field} not provided"}), 400

    submission = db.session.get(Submission, data["id"])
    if not submission:
        return jsonify({"status": "Fail", "reason": "Post not found"}), 404

    report = Report(
        submission_id=data["id"],
        title=data["title"].strip(),
        content=data["content"].strip(),
        status="Pending",  # 投诉默认Pending
        created_at=get_utc_now()
    )

    try:
        db.session.add(report)
        db.session.commit()
        return jsonify({"id": report.id, "status": "OK"}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "Fail", "reason": str(e)}), 500

@app.route('/get/post_state', methods=['GET'])
def get_post_state():
    post_id = request.args.get("id")
    if not post_id:
        return jsonify({"status": "Fail", "reason": "ID not provided"}), 400

    submission = db.session.get(Submission, post_id)
    if not submission:
        return jsonify({"status": "Deleted or Not Found"}), 200

    if submission.status == "Pass":
        return jsonify({"status": "Approved"}), 200
    elif submission.status == "Deny":
        return jsonify({"status": "Rejected"}), 200
    else:
        return jsonify({"status": "Pending"}), 200

@app.route('/get/report_state', methods=['GET'])
def get_report_state():
    report_id = request.args.get("id")
    if not report_id:
        return jsonify({"status": "Fail", "reason": "ID not provided"}), 400

    report = db.session.get(Report, report_id)
    if not report:
        return jsonify({"status": "Deleted or Not Found"}), 200

    if report.status == "Pass":
        return jsonify({"status": "Approved"}), 200
    elif report.status == "Deny":
        return jsonify({"status": "Rejected"}), 200
    else:
        return jsonify({"status": "Pending"}), 200


@app.route('/get/post_info', methods=['GET'])
def get_post_info():
    post_id = request.args.get("id", type=int)
    if not post_id:
        return jsonify({"status": "Fail", "reason": "ID missing"}), 400

    submission = db.session.get(Submission, post_id)
    if not submission or submission.status != "Pass":
        return jsonify({"status": "Fail", "reason": "Not found"}), 404

    return jsonify({
        "id": submission.id,
        "content": submission.content,
        "upvotes": submission.upvotes,
        "downvotes": submission.downvotes
    }), 200


@app.route('/admin/get/post_info', methods=['GET'])
@require_admin
def get_admin_post_info():
    post_id = request.args.get("id", type=int)
    if not post_id:
        return jsonify({"status": "Fail", "reason": "ID missing"}), 400

    submission = db.session.get(Submission, post_id)
    if not submission:
        return jsonify({"status": "Fail", "reason": "Not found"}), 404

    return jsonify({
        "id": submission.id,
        "content": submission.content,
        "created_at": submission.created_at.isoformat(),
        "updated_at": submission.updated_at.isoformat(),
        "status": submission.status,
        "upvotes": submission.upvotes,
        "downvotes": submission.downvotes
    }), 200


@app.route('/get/comment', methods=['GET'])
def get_comments():
    post_id = request.args.get("id", type=int)
    if not post_id:
        return jsonify({"status": "Fail", "reason": "ID missing"}), 400

    submission = db.session.get(Submission, post_id)
    if not submission or submission.status != "Pass":
        return jsonify({"status": "Fail", "reason": "Post not found"}), 404

    def serialize_comment(comment):
        return {
            "id": comment.id,
            "nickname": comment.nickname,
            "content": comment.content,
            "parent_comment_id": comment.parent_comment_id
        }

    comments = [serialize_comment(c) for c in submission.comments]
    return jsonify(comments), 200


@app.route('/get/10_info', methods=['GET'])
def get_10_info():
    page = request.args.get("page", 1, type=int)
    if page < 1:
        page = 1

    per_page = 10
    # 排序 id 从大到小
    all_posts = Submission.query.order_by(Submission.id.desc()).all()
    result = []

    for submission in all_posts:
        if submission.status == "Pass":
            result.append(submission)
        if len(result) >= page * per_page:
            break

    start = (page - 1) * per_page
    end = start + per_page
    page_posts = result[start:end]

    return jsonify([{
        "id": s.id,
        "content": s.content,
        "upvotes": s.upvotes,
        "downvotes": s.downvotes
    } for s in page_posts]), 200


@app.route('/get/statics', methods=['GET'])
def get_statics():
    num_posts = Submission.query.count()
    num_comments = Comment.query.count()
    num_images = len(os.listdir('img')) if os.path.exists('img') else 0

    return jsonify({
        "posts": num_posts,
        "comments": num_comments,
        "images": num_images
    }), 200

@app.route('/get/teapot', methods=['GET'])
def return_418():
    abort(418)

# === Admin测试API接口 ===
@app.route('/test', methods=['GET', 'POST'])
def return_200():
    return 'API OK!!!', 200

@app.route('/admin/need_audit', methods=['POST'])
@require_admin
def toggle_audit():
    data = request.get_json()
    if not data or "need_audit" not in data:
        return jsonify({"status": "Fail", "reason": "value need_audit not found"}), 400

    need_audit = data["need_audit"]
    if not isinstance(need_audit, bool):
        return jsonify({"status": "Fail", "reason": "Not bool"}), 400

    set_config("need_audit", str(need_audit)) 
    global NEED_AUDIT
    NEED_AUDIT = need_audit
    return jsonify({"status": "OK"}), 200

@app.route('/admin/get/need_audit', methods=['GET'])
@require_admin
def get_need_audit():
    global NEED_AUDIT
    return jsonify({"status": NEED_AUDIT}), 200

# 动态敏感词配置
@app.route('/admin/get/banned_keywords', methods=['GET'])
@require_admin
def get_banned_keywords():
    return jsonify({"keywords": BANNED_KEYWORDS}), 200

@app.route('/admin/banned_keywords', methods=['POST'])
@require_admin
def set_banned_keywords():
    data = request.get_json() or {}
    keywords = data.get("BANNED_KEYWORDS", data.get("banned_keywords"))
    if keywords is None:
        return jsonify({"status": "Fail", "reason": "BANNED_KEYWORDS not found"}), 400
    if isinstance(keywords, str):
        new_keywords = [x.strip() for x in keywords.split(',') if x.strip()]
    elif isinstance(keywords, list):
        new_keywords = [str(x).strip() for x in keywords if str(x).strip()]
    else:
        return jsonify({"status": "Fail", "reason": "BANNED_KEYWORDS must be list or comma string"}), 400

    global BANNED_KEYWORDS
    BANNED_KEYWORDS = new_keywords
    try:
        # 重写配置文件，确保重启后仍生效
        write_config_py(ADMIN_TOKEN_HASH, UPLOAD_FOLDER, list(ALLOWED_EXTENSIONS), MAX_FILE_SIZE, BANNED_KEYWORDS)
        load_config()
        return jsonify({"status": "OK"}), 200
    except Exception as e:
        return jsonify({"status": "Fail", "reason": str(e)}), 500

@app.route('/admin/approve', methods=['POST'])
@require_admin
def admin_approve():
    data = request.get_json()
    if not data or "id" not in data:
        return jsonify({"status": "Fail", "reason": "Value ID not found"}), 400
    success, reason = admin_change_status(data["id"], "Pending", "Pass")
    if success:
        return jsonify({"status": "OK"})
    else:
        return jsonify({"status": "Fail", "reason": reason})


@app.route('/admin/disapprove', methods=['POST'])
@require_admin
def admin_disapprove():
    data = request.get_json()
    if not data or "id" not in data:
        return jsonify({"status": "Fail", "reason": "Value ID not found"}), 400
    success, reason = admin_change_status(data["id"], "Pending", "Deny")
    if success:
        return jsonify({"status": "OK"})
    else:
        return jsonify({"status": "Fail", "reason": reason})


@app.route('/admin/reaudit', methods=['POST'])
@require_admin
def admin_reaudit():
    data = request.get_json()
    if not data or "id" not in data:
        return jsonify({"status": "Fail", "reason": "Value ID not found"}), 400
    success, reason = admin_change_status(data["id"], "Pass", "Pending")
    if success:
        return jsonify({"status": "OK"})
    else:
        return jsonify({"status": "Fail", "reason": reason})
    
@app.route('/admin/del_comment', methods=['POST'])
@require_admin
def admin_delete_comment():
    data = request.get_json()
    if not data or "id" not in data:
        return jsonify({"status": "Fail", "reason": "Value ID not found"}), 400

    comment = db.session.get(Comment, data["id"])
    if not comment:
        return jsonify({"status": "Fail", "reason": "Comment not found"}), 404

    try:
        db.session.delete(comment)
        db.session.commit()
        return jsonify({"status": "OK"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "Fail", "reason": str(e)}), 500
    
@app.route('/admin/modify_comment', methods=['POST'])
@require_admin
def admin_modify_comment():
    data = request.get_json()
    # --- 参数检查 ---
    if not data or not all(k in data for k in ("id", "content", "parent_comment_id", "nickname")):
        return jsonify({"status": "Fail", "reason": "Missing required fields"}), 400

    comment = db.session.get(Comment, data["id"])
    if not comment:
        return jsonify({"status": "Fail", "reason": "Comment not found"}), 404

    new_content = data["content"].strip()
    new_parent_id = int(data["parent_comment_id"])
    new_nickname = data["nickname"].strip() or "匿名用户"

    # --- 检查回复目标是否合法 ---
    if new_parent_id != 0:
        parent_comment = db.session.get(Comment, new_parent_id)
        if not parent_comment or parent_comment.submission_id != comment.submission_id:
            return jsonify({"status": "Wrong_Reply"}), 400

    # --- 执行修改 ---
    try:
        comment.content = new_content
        comment.parent_comment_id = new_parent_id
        comment.nickname = new_nickname
        db.session.commit()
        return jsonify({"status": "OK"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "Fail", "reason": str(e)}), 500

@app.route('/admin/del_post', methods=['POST'])
@require_admin
def admin_del_post():
    data = request.get_json()
    if not data or "id" not in data:
        return jsonify({"status": "Fail", "reason": "Value ID not found"}), 400

    submission = db.session.get(Submission, data["id"])
    if not submission:
        return jsonify({"status": "Fail", "reason": "Post not found"}), 404

    try:
        db.session.delete(submission)
        db.session.commit()
        return jsonify({"status": "OK"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "Fail", "reason": str(e)}), 500

@app.route('/admin/modify_post', methods=['POST'])
@require_admin
def admin_modify_post():

    data = request.get_json()
    if not data or "id" not in data or "content" not in data:
        return jsonify({"status": "Fail", "reason": "Missing id or content"}), 400

    submission = db.session.get(Submission, data["id"])
    if not submission:
        return jsonify({"status": "Fail", "reason": "Post not found"}), 404

    submission.content = data["content"].strip()
    submission.updated_at = get_utc_now()
    db.session.commit()

    return jsonify({"status": "OK"}), 200

@app.route('/admin/del_pic', methods=['POST'])
@require_admin
def admin_del_pic():
    data = request.get_json()
    if not data or "filename" not in data:
        return jsonify({"status": "Fail", "reason": "filename not found"}), 400

    filename = data["filename"]
    file_path = os.path.join(os.getcwd(), UPLOAD_FOLDER, filename)

    if not os.path.isfile(file_path):
        return jsonify({"status": "Fail", "reason": "file not found"}), 404

    try:
        os.remove(file_path)
        return jsonify({"status": "OK"}), 200
    except Exception as e:
        return jsonify({"status": "Fail", "reason": str(e)}), 500

@app.route('/admin/approve_report', methods=['POST'])
@require_admin
def approve_report():
    data = request.get_json()
    if not data or "id" not in data:
        return jsonify({"status": "Fail", "reason": "Value ID not found"}), 400

    report = db.session.get(Report, data["id"])
    if not report:
        return jsonify({"status": "Fail", "reason": "Report not found"}), 404

    try:
        # 先将投诉状态标记为 Pass
        report.status = "Pass"
        db.session.commit()  # <- 先提交状态

        # 删除文章及其所有评论
        submission = db.session.get(Submission, report.submission_id)
        if submission:
            db.session.delete(submission)
            db.session.commit()

        return jsonify({"status": "OK"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "Fail", "reason": str(e)}), 500



@app.route('/admin/reject_report', methods=['POST'])
@require_admin
def reject_report():
    data = request.get_json()
    if not data or "id" not in data:
        return jsonify({"status": "Fail", "reason": "Value ID not found"}), 400

    report = db.session.get(Report, data["id"])
    if not report:
        return jsonify({"status": "Fail", "reason": "Report not found"}), 404

    try:
        report.status = "Deny"
        db.session.commit()
        return jsonify({"status": "OK"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "Fail", "reason": str(e)}), 500
    
@app.route('/admin/get/backup', methods=['GET'])
@require_admin
def admin_get_backup():
    try:
        backup_name = f"backup_{datetime.now().strftime('%y%m%d_%H%M%S')}.zip"
        backup_path = os.path.join(BACKUP_FOLDER, backup_name)
        
        with zipfile.ZipFile(backup_path, 'w') as zipf:
            # 添加数据库
            if os.path.exists(DB_FILE):
                zipf.write(DB_FILE, arcname=os.path.basename(DB_FILE))
            # 添加配置文件
            config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.py')
            if os.path.exists(config_path):
                zipf.write(config_path, arcname='config.py')
            # 添加 img 文件夹
            if os.path.exists(IMG_FOLDER):
                for root, dirs, files in os.walk(IMG_FOLDER):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, os.path.dirname(IMG_FOLDER))
                        zipf.write(file_path, arcname=arcname)
        
        return send_file(backup_path, as_attachment=True)
    except Exception as e:
        return jsonify({"status": "Fail", "reason": str(e)}), 500


@app.route('/admin/recover', methods=['POST'])
@require_admin
def admin_recover():
    if 'file' not in request.files:
        return jsonify({"status": "Fail", "reason": "No file uploaded"}), 400
    
    file = request.files['file']
    if file.filename == '' or not allowed_backup_file(file.filename):
        return jsonify({"status": "Fail", "reason": "Wrong file type"}), 400
    
    filename = secure_filename(file.filename)
    temp_path = os.path.join(BACKUP_FOLDER, filename)
    file.save(temp_path)

    try:
        # 1) 解压到临时目录，不直接覆盖源目录
        extract_dir = os.path.join(BACKUP_FOLDER, f"extracted_{os.path.splitext(filename)[0]}")
        if os.path.exists(extract_dir):
            shutil.rmtree(extract_dir, ignore_errors=True)
        os.makedirs(extract_dir, exist_ok=True)

        with zipfile.ZipFile(temp_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)

        # 2) 先恢复配置文件并重新加载配置
        try:
            src_config = os.path.join(extract_dir, 'config.py')
            if os.path.isfile(src_config):
                dest_config = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.py')
                shutil.copy2(src_config, dest_config)
                # 重新加载配置以应用可能变化的上传目录等
                try:
                    load_config()
                except Exception:
                    pass
        except Exception as e:
            app.logger.warning(f"Recover config.py failed: {e}")

        # 3) 恢复 img 文件夹到应用目录（根据当前配置中的上传目录）
        src_img = os.path.join(extract_dir, 'img')
        if os.path.isdir(src_img):
            # 清空并复制
            shutil.rmtree(IMG_FOLDER, ignore_errors=True)
            shutil.copytree(src_img, IMG_FOLDER)

        # 4) 恢复数据库到 DB_FILE
        target_db = DB_FILE
        db_basename = os.path.basename(target_db)
        candidate = os.path.join(extract_dir, db_basename)
        if not os.path.isfile(candidate):
            # 兜底：在压缩包中搜索常见数据库文件扩展
            candidate = None
            for root, _, files in os.walk(extract_dir):
                for f in files:
                    if f.lower().endswith(('.db', '.sqlite', '.sqlite3')):
                        candidate = os.path.join(root, f)
                        break
                if candidate:
                    break
        if not candidate:
            return jsonify({"status": "Fail", "reason": "DB file not found in backup"}), 400

        # 处理 SQLite WAL/SHM，避免增量日志合并新数据
        wal = f"{target_db}-wal"
        shm = f"{target_db}-shm"
        for fpath in (wal, shm):
            if os.path.exists(fpath):
                try:
                    os.remove(fpath)
                except Exception as e:
                    app.logger.warning(f"Failed to remove {fpath}: {e}")

        # 确保 instance 目录存在
        os.makedirs(os.path.dirname(target_db), exist_ok=True)
        # 覆盖数据库文件
        shutil.copy2(candidate, target_db)

        # 5) 释放 SQLAlchemy 连接（如果持有旧句柄）
        try:
            db.session.remove()
            db.engine.dispose()
        except Exception:
            pass

        # 6) 清理临时文件夹与压缩包
        try:
            os.remove(temp_path)
        except Exception:
            pass
        shutil.rmtree(extract_dir, ignore_errors=True)

        return jsonify({"status": "OK"}), 200
    except Exception as e:
        return jsonify({"status": "Fail", "reason": str(e)}), 500

@app.route('/admin/get/pending_posts', methods=['GET'])
@require_admin
def admin_pending_posts():
    posts = Submission.query.filter_by(status="Pending").all()
    return jsonify([{
        "id": s.id,
        "content": s.content,
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
        "status": s.status
    } for s in posts]), 200


@app.route('/admin/get/reject_posts', methods=['GET'])
@require_admin
def admin_reject_posts():
    posts = Submission.query.filter_by(status="Deny").all()
    return jsonify([{
        "id": s.id,
        "content": s.content,
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
        "status": s.status
    } for s in posts]), 200


@app.route('/admin/get/pic_links', methods=['GET'])
@require_admin
def admin_get_pic_links():
    page = request.args.get("page", 1, type=int)
    if page < 1:
        page = 1

    per_page = 20
    if not os.path.exists(UPLOAD_FOLDER):
        return jsonify([]), 200

    all_files = sorted(
        [f for f in os.listdir(UPLOAD_FOLDER) if os.path.isfile(os.path.join(UPLOAD_FOLDER, f))],
        key=lambda x: os.path.getmtime(os.path.join(UPLOAD_FOLDER, x)),
        reverse=True
    )

    start = (page - 1) * per_page
    end = start + per_page
    page_files = all_files[start:end]
    urls = [f"/img/{f}" for f in page_files]

    return jsonify(urls), 200


@app.route('/admin/get/pending_reports', methods=['GET'])
@require_admin
def admin_pending_reports():
    reports = Report.query.filter_by(status="Pending").all()
    return jsonify([{
        "id": r.id,
        "submission_id": r.submission_id,
        "title": r.title,
        "content": r.content,
        "status": r.status,
        "created_at": r.created_at.isoformat()
    } for r in reports]), 200


@app.route('/admin/test', methods=['GET', 'POST'])
@require_admin
def admin_return_200():
    return 'Admin API OK!!!', 200

# === 数据库初始化 ===
def initialize_database():
    """若数据库不存在则创建并初始化"""
    db.create_all()  # 安全创建表

    if not Config.query.filter_by(key="need_audit").first():
        default_config = Config(key="need_audit", value="false")
        db.session.add(default_config)
        db.session.commit()

    # 确保公告表有默认记录
    ensure_default_notice()


# === 启动 ===
if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000) # 监听IP&端口，建议监听127.0.0.1并配置反向代理
