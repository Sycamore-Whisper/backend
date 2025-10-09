from flask import Flask, request, jsonify, abort
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timezone
from flask_cors import CORS
from flask import send_from_directory
import zipfile
from flask import send_file
from werkzeug.utils import secure_filename
import os

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


# === 变量 ===
BANNED_KEYWORDS = [
    "傻逼", "煞笔", "傻叉", "脑残", "狗东西",
    "操你妈", "你妈的", "滚", "神经病", "贱人", "杂种", "王八蛋",
    "臭婊子", "蠢货", "白痴", "妈的",
    "约吗", "开房", "一夜情", "裸聊", "床照",
    "小电影", "嫖娼", "成人网", "🈷吗",
    "毒品", "枪支", "赌博", "六合彩", "博彩", "赌球",
    "诈骗", "洗钱", "开票", "假证", "网监",
    "习近平", "毛泽东", "共产党", "台湾独立", "台独", "法轮功",
    "反动", "民主运动", "六四", "政变",
    "割腕", "跳楼"
]

ADMIN_TOKEN = "LeonXieNeko14235^"

UPLOAD_FOLDER = "img"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance', 'database.db')
IMG_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'img')
BACKUP_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backups')
os.makedirs(BACKUP_FOLDER, exist_ok=True)

ALLOWED_BACKUP_EXTENSIONS = {'zip'}

def allowed_backup_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_BACKUP_EXTENSIONS


# === 管理端文章状态修改工具函数 ===
def admin_change_status(submission_id, from_status, to_status):
    submission = Submission.query.get(submission_id)
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
        if token != ADMIN_TOKEN:
            return jsonify({"status": "Fail", "reason": "Token invalid"}), 403
        return func(*args, **kwargs)
    return wrapper

# === 路由 ===
@app.route('/post', methods=['POST'])
def submit_post():
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
    data = request.get_json()
    if not data or "id" not in data:
        return jsonify({"status": "Fail", "reason": "Value ID not found"}), 400

    submission = Submission.query.get(data["id"])
    if not submission:
        return jsonify({"status": "Fail", "reason": "Post not found"}), 404

    submission.upvotes += 1
    db.session.commit()
    return jsonify({"status": "OK"}), 200


@app.route('/down', methods=['POST'])
def downvote():
    data = request.get_json()
    if not data or "id" not in data:
        return jsonify({"status": "Fail", "reason": "Value ID not found"}), 400

    submission = Submission.query.get(data["id"])
    if not submission:
        return jsonify({"status": "Fail", "reason": "Post not found"}), 404

    submission.downvotes += 1
    db.session.commit()
    return jsonify({"status": "OK"}), 200

@app.route('/comment', methods=['POST'])
def post_comment():
    data = request.get_json()
    required_fields = ["content", "submission_id", "parent_comment_id", "nickname"]
    if not all(field in data for field in required_fields):
        return jsonify({"id": None, "status": "Fail"}), 400

    content = data["content"].strip()
    submission_id = data["submission_id"]
    parent_comment_id = data["parent_comment_id"]
    nickname = data["nickname"].strip() or "匿名用户"

    # 检查投稿是否存在
    submission = Submission.query.get(submission_id)
    if not submission:
        return jsonify({"id": None, "status": "Fail"}), 404

    # 检查违规关键词
    if any(bad_word in content for bad_word in BANNED_KEYWORDS):
        return jsonify({"id": None, "status": "Deny"}), 403

    # 检查回复的评论是否合法
    if parent_comment_id != 0:
        reply_comment = Comment.query.get(parent_comment_id)
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
    return send_from_directory('img', filename)


@app.route('/report', methods=['POST'])
def submit_report():
    data = request.get_json()
    if not data:
        return jsonify({"status": "Fail", "reason": "No data provided"}), 400

    # 必须包含的字段
    required_fields = ["id", "title", "content"]
    for field in required_fields:
        if field not in data:
            return jsonify({"status": "Fail", "reason": f"{field} not provided"}), 400

    submission = Submission.query.get(data["id"])
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

    submission = Submission.query.get(post_id)
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

    report = Report.query.get(report_id)
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

    submission = Submission.query.get(post_id)
    if not submission or submission.status != "Pass":
        return jsonify({"status": "Fail", "reason": "Not found"}), 404

    return jsonify({
        "id": submission.id,
        "content": submission.content,
        "created_at": submission.created_at.isoformat(),
        "updated_at": submission.updated_at.isoformat(),
        "upvotes": submission.upvotes,
        "downvotes": submission.downvotes
    }), 200


@app.route('/admin/get/post_info', methods=['GET'])
@require_admin
def get_admin_post_info():
    post_id = request.args.get("id", type=int)
    if not post_id:
        return jsonify({"status": "Fail", "reason": "ID missing"}), 400

    submission = Submission.query.get(post_id)
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

    submission = Submission.query.get(post_id)
    if not submission or submission.status != "Pass":
        return jsonify({"status": "Fail", "reason": "Post not found"}), 404

    def serialize_comment(comment):
        return {
            "id": comment.id,
            "nickname": comment.nickname,
            "content": comment.content,
            "parent_comment_id": comment.parent_comment_id,
            "created_at": comment.created_at.isoformat()
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
        "created_at": s.created_at.isoformat(),
        "updated_at": s.updated_at.isoformat(),
        "status": s.status
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

@app.route('/get/api_info', methods=['GET'])
def get_api_info():
    return '<a>Sycamore_whisper API v1.0.0</a>   Made with ❤️ By <a href="https://leonxie.cn">Leonxie</a>', 200

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

    comment = Comment.query.get(data["id"])
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

    comment = Comment.query.get(data["id"])
    if not comment:
        return jsonify({"status": "Fail", "reason": "Comment not found"}), 404

    new_content = data["content"].strip()
    new_parent_id = int(data["parent_comment_id"])
    new_nickname = data["nickname"].strip() or "匿名用户"

    # --- 检查回复目标是否合法 ---
    if new_parent_id != 0:
        parent_comment = Comment.query.get(new_parent_id)
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

    submission = Submission.query.get(data["id"])
    if not submission:
        return jsonify({"status": "Fail", "reason": "Post not found"}), 404

    try:
        db.session.delete(submission)  # 会级联删除所有 comments（你在 Submission 模型里有 cascade='all, delete-orphan'）
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

    submission = Submission.query.get(data["id"])
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
    file_path = os.path.join(os.getcwd(), "img", filename)

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

    report = Report.query.get(data["id"])
    if not report:
        return jsonify({"status": "Fail", "reason": "Report not found"}), 404

    try:
        # 先将投诉状态标记为 Pass
        report.status = "Pass"
        db.session.commit()  # <- 先提交状态

        # 删除文章及其所有评论
        submission = Submission.query.get(report.submission_id)
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

    report = Report.query.get(data["id"])
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
        # 解压到当前目录，会覆盖数据库和 img 文件夹
        with zipfile.ZipFile(temp_path, 'r') as zip_ref:
            zip_ref.extractall(os.path.dirname(os.path.abspath(__file__)))  
        
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
    if not os.path.exists('img'):
        return jsonify([]), 200

    all_files = sorted(
        [f for f in os.listdir('img') if os.path.isfile(os.path.join('img', f))],
        key=lambda x: os.path.getmtime(os.path.join('img', x)),
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


# === 数据库初始化 ===
def initialize_database():
    """若数据库不存在则创建并初始化"""
    db.create_all()  # 安全创建表

    if not Config.query.filter_by(key="need_audit").first():
        default_config = Config(key="need_audit", value="false")
        db.session.add(default_config)
        db.session.commit()


# === 启动 ===
if __name__ == '__main__':
    with app.app_context():
        initialize_database()
        NEED_AUDIT = get_config("need_audit", "false").lower() == "true"
    app.run(host='0.0.0.0', port=5000, debug=True)
