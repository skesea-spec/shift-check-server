from flask import Flask, request, redirect, url_for, session, g, render_template_string
import sqlite3
import os
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
# 실제 서비스에서는 환경변수로 SECRET_KEY를 넣는 게 좋지만, 지금은 테스트용 고정값.
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "shift.db")


# ---------------- DB 유틸 ----------------

def get_db():
    """요청당 한 번만 연결하고, 테이블이 없으면 만든다."""
    if "db" not in g:
        first = not os.path.exists(DATABASE)
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        if first:
            init_db(g.db)
        else:
            # 혹시 파일은 있는데 테이블이 없을 수도 있으니 안전하게 한 번 더 실행
            init_db(g.db, if_not_exists=True)
    return g.db


def init_db(db, if_not_exists: bool = False):
    """DB 테이블 생성. if_not_exists=True면 IF NOT EXISTS 옵션 사용."""
    if if_not_exists:
        users_sql = """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """
        shifts_sql = """
            CREATE TABLE IF NOT EXISTS shifts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                shift_date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
        """
    else:
        users_sql = """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """
        shifts_sql = """
            CREATE TABLE shifts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                shift_date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
        """
    db.executescript(users_sql + shifts_sql)
    db.commit()


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return user


def login_user(user):
    session["user_id"] = user["id"]
    session["role"] = user["role"]


def logout_user():
    session.clear()


# ---------------- 템플릿 ----------------

INDEX_HTML = """
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>Shift Check - 출퇴근 계획</title>
  <style>
    body { font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:#f4f4f4; }
    .wrap { max-width: 480px; margin:40px auto; padding:24px; background:white; border-radius:12px;
            box-shadow:0 4px 12px rgba(0,0,0,0.05); text-align:center; }
    h1 { margin-bottom:8px; }
    .role-btns a { display:block; margin:12px 0; padding:12px; border-radius:8px; text-decoration:none;
                   font-weight:600; }
    .worker { background:#e0f2ff; color:#0052a3; }
    .owner { background:#ffe8d5; color:#a34700; }
    .small { color:#666; font-size:0.9rem; margin-top:12px; }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Shift Check</h1>
    <p>프리랜서/배달 기사 출퇴근 계획 공유 서비스</p>
    {% if user %}
      <p><strong>{{ user['name'] }}</strong>님은 이미 로그인 되어 있습니다.</p>
      {% if user['role'] == 'worker' %}
        <p><a href="{{ url_for('worker_dashboard') }}">기사 화면으로 이동</a></p>
      {% else %}
        <p><a href="{{ url_for('owner_dashboard') }}">사업주 화면으로 이동</a></p>
      {% endif %}
      <p class="small"><a href="{{ url_for('logout') }}">로그아웃</a></p>
    {% else %}
      <div class="role-btns">
        <a class="worker" href="{{ url_for('worker_login') }}">기사(워커)로 시작하기</a>
        <a class="owner" href="{{ url_for('owner_login') }}">사업주로 시작하기</a>
      </div>
      <p class="small">가입 승인 절차 없이 바로 사용 가능합니다.</p>
    {% endif %}
  </div>
</body>
</html>
"""


AUTH_HTML = """
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>{{ title }}</title>
  <style>
    body { font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:#f4f4f4; }
    .wrap { max-width: 420px; margin:40px auto; padding:24px; background:white; border-radius:12px;
            box-shadow:0 4px 12px rgba(0,0,0,0.05); }
    h1 { margin-bottom:16px; }
    label { display:block; margin-top:12px; font-weight:600; font-size:0.9rem; }
    input { width:100%; padding:8px; margin-top:4px; box-sizing:border-box; border-radius:6px; border:1px solid #ccc; }
    button { margin-top:16px; width:100%; padding:10px; border:none; border-radius:8px; background:#4f46e5; color:white;
             font-size:1rem; font-weight:600; cursor:pointer; }
    .small { margin-top:12px; font-size:0.9rem; color:#555; }
    .error { color:#c00; margin-top:8px; }
    a { color:#4f46e5; text-decoration:none; }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>{{ heading }}</h1>
    <form method="post">
      {% if form_type == 'register' %}
        <label>이름
          <input type="text" name="name" required>
        </label>
      {% endif %}
      <label>이메일
        <input type="email" name="email" required>
      </label>
      <label>비밀번호
        <input type="password" name="password" required>
      </label>
      <button type="submit">{{ button_text }}</button>
      {% if error %}
        <div class="error">{{ error }}</div>
      {% endif %}
    </form>
    <p class="small">
      {% if form_type == 'login' %}
        처음 이용하시나요?
        {% if role == 'worker' %}
          <a href="{{ url_for('worker_register') }}">기사 회원가입</a>
        {% else %}
          <a href="{{ url_for('owner_register') }}">사업주 회원가입</a>
        {% endif %}
      {% else %}
        이미 계정이 있으신가요?
        {% if role == 'worker' %}
          <a href="{{ url_for('worker_login') }}">기사 로그인</a>
        {% else %}
          <a href="{{ url_for('owner_login') }}">사업주 로그인</a>
        {% endif %}
      {% endif %}
    </p>
    <p class="small"><a href="{{ url_for('index') }}">← 처음 화면으로</a></p>
  </div>
</body>
</html>
"""


DASHBOARD_HTML = """
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>{{ title }}</title>
  <style>
    body { font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:#f4f4f4; }
    .wrap { max-width: 900px; margin:24px auto; padding:24px; background:white; border-radius:12px;
            box-shadow:0 4px 12px rgba(0,0,0,0.05); }
    h1 { margin-bottom:4px; }
    .subtitle { color:#555; margin-bottom:16px; }
    .top-bar { display:flex; justify-content:space-between; align-items:center; margin-bottom:16px; }
    .tag { display:inline-block; padding:4px 8px; border-radius:999px; font-size:0.8rem; }
    .tag-worker { background:#e0f2ff; color:#0052a3; }
    .tag-owner { background:#ffe8d5; color:#a34700; }
    form { margin:16px 0 24px 0; padding:16px; background:#f9fafb; border-radius:8px; }
    label { display:inline-block; margin-right:12px; font-size:0.9rem; }
    input[type="date"], input[type="time"], input[type="text"] {
        padding:4px 6px; border-radius:6px; border:1px solid #ccc;
    }
    button { padding:8px 14px; border:none; border-radius:8px; background:#4f46e5; color:white;
             font-weight:600; cursor:pointer; }
    table { width:100%; border-collapse:collapse; font-size:0.9rem; }
    th, td { border-bottom:1px solid #eee; padding:8px 6px; text-align:left; }
    th { background:#f9fafb; }
    tr:nth-child(even) { background:#fafafa; }
    .small { font-size:0.85rem; color:#666; margin-top:8px; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="top-bar">
      <div>
        <h1>{{ title }}</h1>
        <div class="subtitle">
          {{ user['name'] }} 님 ({{ '기사' if user['role']=='worker' else '사업주' }})
        </div>
      </div>
      <div>
        {% if user['role'] == 'worker' %}
          <span class="tag tag-worker">기사 모드</span>
        {% else %}
          <span class="tag tag-owner">사업주 모드</span>
        {% endif %}
        <a href="{{ url_for('logout') }}" class="small">로그아웃</a>
      </div>
    </div>

    {% if user['role'] == 'worker' %}
      <h2>오늘/향후 근무 계획 입력</h2>
      <form method="post">
        <label>날짜
          <input type="date" name="shift_date" value="{{ today }}" required>
        </label>
        <label>출근
          <input type="time" name="start_time" required>
        </label>
        <label>퇴근
          <input type="time" name="end_time" required>
        </label>
        <label>메모
          <input type="text" name="note" placeholder="예: 강남구 위주, 점심만" style="width:220px;">
        </label>
        <button type="submit">저장</button>
      </form>
    {% else %}
      <p class="small">
        사업주 화면에서는 전체 기사들의 출퇴근 계획을 한눈에 볼 수 있습니다.
      </p>
    {% endif %}

    <h2>전체 출퇴근 계획</h2>
    <p class="small">기사/사업주 누구나 같은 화면을 보고 협의할 수 있습니다.</p>
    <table>
      <thead>
        <tr>
          <th>날짜</th>
          <th>이름</th>
          <th>출근</th>
          <th>퇴근</th>
          <th>메모</th>
          <th>등록시간</th>
        </tr>
      </thead>
      <tbody>
        {% for s in shifts %}
          <tr>
            <td>{{ s['shift_date'] }}</td>
            <td>{{ s['name'] }}</td>
            <td>{{ s['start_time'] }}</td>
            <td>{{ s['end_time'] }}</td>
            <td>{{ s['note'] or '' }}</td>
            <td>{{ s['created_at'] }}</td>
          </tr>
        {% else %}
          <tr><td colspan="6">아직 등록된 출퇴근 계획이 없습니다.</td></tr>
        {% endfor %}
      </tbody>
    </table>
  </div>
</body>
</html>
"""


# ---------------- 라우트 ----------------

@app.route("/")
def index():
    user = get_current_user()
    return render_template_string(INDEX_HTML, user=user)


@app.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("index"))


# ---- 기사(워커) 인증 ----

@app.route("/worker/register", methods=["GET", "POST"])
def worker_register():
    error = None
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not name or not email or not password:
            error = "모든 필드를 입력해 주세요."
        else:
            db = get_db()
            existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if existing:
                error = "이미 등록된 이메일입니다. 로그인 해 주세요."
            else:
                db.execute(
                    "INSERT INTO users (role, name, email, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                    (
                        "worker",
                        name,
                        email,
                        generate_password_hash(password),
                        datetime.utcnow().isoformat(timespec="seconds"),
                    ),
                )
                db.commit()
                user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
                login_user(user)
                return redirect(url_for("worker_dashboard"))
    return render_template_string(
        AUTH_HTML,
        title="기사 회원가입",
        heading="기사(워커) 회원가입",
        button_text="가입하기",
        form_type="register",
        role="worker",
        error=error,
    )


@app.route("/worker/login", methods=["GET", "POST"])
def worker_login():
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE email = ? AND role = 'worker'", (email,)
        ).fetchone()
        if not user or not check_password_hash(user["password_hash"], password):
            error = "이메일 또는 비밀번호가 올바르지 않습니다."
        else:
            login_user(user)
            return redirect(url_for("worker_dashboard"))
    return render_template_string(
        AUTH_HTML,
        title="기사 로그인",
        heading="기사(워커) 로그인",
        button_text="로그인",
        form_type="login",
        role="worker",
        error=error,
    )


# ---- 사업주 인증 ----

@app.route("/owner/register", methods=["GET", "POST"])
def owner_register():
    error = None
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not name or not email or not password:
            error = "모든 필드를 입력해 주세요."
        else:
            db = get_db()
            existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
            if existing:
                error = "이미 등록된 이메일입니다. 로그인 해 주세요."
            else:
                db.execute(
                    "INSERT INTO users (role, name, email, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                    (
                        "owner",
                        name,
                        email,
                        generate_password_hash(password),
                        datetime.utcnow().isoformat(timespec="seconds"),
                    ),
                )
                db.commit()
                user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
                login_user(user)
                return redirect(url_for("owner_dashboard"))
    return render_template_string(
        AUTH_HTML,
        title="사업주 회원가입",
        heading="사업주 회원가입",
        button_text="가입하기",
        form_type="register",
        role="owner",
        error=error,
    )


@app.route("/owner/login", methods=["GET", "POST"])
def owner_login():
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE email = ? AND role = 'owner'", (email,)
        ).fetchone()
        if not user or not check_password_hash(user["password_hash"], password):
            error = "이메일 또는 비밀번호가 올바르지 않습니다."
        else:
            login_user(user)
            return redirect(url_for("owner_dashboard"))
    return render_template_string(
        AUTH_HTML,
        title="사업주 로그인",
        heading="사업주 로그인",
        button_text="로그인",
        form_type="login",
        role="owner",
        error=error,
    )


# ---- 공통: 로그인 체크 & 데이터 ----

def require_login(role=None):
    user = get_current_user()
    if not user:
        return None, redirect(url_for("index"))
    if role and user["role"] != role:
        return None, redirect(url_for("index"))
    return user, None


def load_all_shifts():
    db = get_db()
    rows = db.execute(
        """
        SELECT s.*, u.name
        FROM shifts s
        JOIN users u ON s.user_id = u.id
        ORDER BY s.shift_date ASC, s.start_time ASC
        """
    ).fetchall()
    return rows


# ---- 기사 대시보드 ----

@app.route("/worker/dashboard", methods=["GET", "POST"])
def worker_dashboard():
    user, resp = require_login("worker")
    if resp:
        return resp

    db = get_db()
    if request.method == "POST":
        shift_date = request.form.get("shift_date")
        start_time = request.form.get("start_time")
        end_time = request.form.get("end_time")
        note = request.form.get("note", "").strip()
        if shift_date and start_time and end_time:
            db.execute(
                """
                INSERT INTO shifts (user_id, shift_date, start_time, end_time, note, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user["id"],
                    shift_date,
                    start_time,
                    end_time,
                    note,
                    datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
                ),
            )
            db.commit()

    shifts = load_all_shifts()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    return render_template_string(
        DASHBOARD_HTML,
        title="기사 출퇴근 계획",
        user=user,
        shifts=shifts,
        today=today,
    )


# ---- 사업주 대시보드 ----

@app.route("/owner/dashboard")
def owner_dashboard():
    user, resp = require_login("owner")
    if resp:
        return resp

    shifts = load_all_shifts()
    today = datetime.utcnow().strftime("%Y-%m-%d")
    return render_template_string(
        DASHBOARD_HTML,
        title="사업주 대시보드",
        user=user,
        shifts=shifts,
        today=today,
    )


if __name__ == "__main__":
    app.run(debug=True)
