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
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Shift Check - 출퇴근 계획</title>
  <style>
    body {
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background:#f4f4f4;
      font-size:18px;
      line-height:1.5;
    }
    .wrap {
      max-width: 460px;
      margin:16px auto;
      padding:24px 20px;
      background:white;
      border-radius:16px;
      box-shadow:0 4px 12px rgba(0,0,0,0.05);
      text-align:center;
    }
    h1 { margin-bottom:8px; font-size:1.6rem; }
    .role-btns a {
      display:block;
      margin:14px 0;
      padding:14px 16px;
      border-radius:10px;
      text-decoration:none;
      font-weight:600;
      font-size:1.1rem;
    }
    .worker { background:#e0f2ff; color:#0052a3; }
    .owner { background:#ffe8d5; color:#a34700; }
    .small { color:#666; font-size:0.95rem; margin-top:12px; }
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
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{{ title }}</title>
  <style>
    body {
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background:#f4f4f4;
      font-size:18px;
      line-height:1.5;
    }
    .wrap {
      max-width: 460px;
      margin:16px auto;
      padding:24px 20px;
      background:white;
      border-radius:16px;
      box-shadow:0 4px 12px rgba(0,0,0,0.05);
    }
    h1 { margin-bottom:16px; font-size:1.4rem; }
    label { display:block; margin-top:14px; font-weight:600; font-size:1rem; }
    input {
      width:100%;
      padding:10px;
      margin-top:6px;
      box-sizing:border-box;
      border-radius:10px;
      border:1px solid #ccc;
      font-size:1rem;
    }
    button {
      margin-top:20px;
      width:100%;
      padding:12px;
      border:none;
      border-radius:12px;
      background:#4f46e5;
      color:white;
      font-size:1.1rem;
      font-weight:600;
      cursor:pointer;
    }
    .small { margin-top:14px; font-size:0.95rem; color:#555; }
    .error { color:#c00; margin-top:10px; font-size:0.95rem; }
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
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{{ title }}</title>
  <style>
    body {
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background:#f4f4f4;
      font-size:18px;
      line-height:1.5;
    }
    .wrap {
      max-width: 960px;
      margin:12px auto;
      padding:20px 14px;
      background:white;
      border-radius:16px;
      box-shadow:0 4px 12px rgba(0,0,0,0.05);
    }
    h1 { margin-bottom:4px; font-size:1.5rem; }
    .subtitle { color:#555; margin-bottom:12px; }
    .top-bar {
      display:flex;
      justify-content:space-between;
      align-items:flex-start;
      gap:10px;
      margin-bottom:16px;
      flex-wrap:wrap;
    }
    .tag {
      display:inline-block;
      padding:4px 10px;
      border-radius:999px;
      font-size:0.9rem;
    }
    .tag-worker { background:#e0f2ff; color:#0052a3; }
    .tag-owner { background:#ffe8d5; color:#a34700; }
    form.shift-form {
      margin:16px 0 24px 0;
      padding:14px;
      background:#f9fafb;
      border-radius:12px;
      font-size:0.95rem;
    }
    label { display:inline-block; margin:8px 8px 4px 0; }
    input[type="date"], input[type="time"], input[type="text"] {
        padding:8px 6px;
        border-radius:8px;
        border:1px solid #ccc;
        font-size:0.95rem;
    }
    button {
      padding:8px 14px;
      border:none;
      border-radius:999px;
      background:#4f46e5;
      color:white;
      font-weight:600;
      cursor:pointer;
      font-size:0.95rem;
    }
    .small { font-size:0.85rem; color:#666; margin-top:6px; }

    .table-wrap { overflow-x:auto; margin-top:12px; }
    table { width:100%; border-collapse:collapse; font-size:0.9rem; min-width:640px; }
    th, td { border-bottom:1px solid #eee; padding:8px 6px; text-align:left; white-space:nowrap; }
    th { background:#f9fafb; }
    tr:nth-child(even) { background:#fafafa; }
    .actions a, .actions button {
      font-size:0.8rem;
      padding:4px 8px;
      border-radius:999px;
      margin-left:4px;
    }
    .actions form { display:inline; }
    .filter-form {
      margin:8px 0 16px 0;
      padding:10px;
      background:#f9fafb;
      border-radius:12px;
      font-size:0.9rem;
    }
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
      <form method="post" class="shift-form">
        <label>날짜<br>
          <input type="date" name="shift_date" value="{{ today }}" required>
        </label>
        <label>출근<br>
          <input type="time" name="start_time" required>
        </label>
        <label>퇴근<br>
          <input type="time" name="end_time" required>
        </label>
        <label>메모<br>
          <input type="text" name="note" placeholder="예: 강남구 위주, 점심만" style="min-width:220px;">
        </label>
        <br>
        <button type="submit">저장</button>
      </form>
    {% else %}
      <div class="filter-form">
        <form method="get">
          <label>시작 날짜
            <input type="date" name="start" value="{{ filter_start or '' }}">
          </label>
          <label>끝 날짜
            <input type="date" name="end" value="{{ filter_end or '' }}">
          </label>
          <button type="submit">조회</button>
        </form>
        <p class="small">날짜를 비워두면 전체 기간을 조회합니다.</p>
      </div>
    {% endif %}

    <h2>전체 출퇴근 계획</h2>
    <p class="small">기사/사업주 누구나 같은 화면을 보고 협의할 수 있습니다.</p>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>날짜</th>
            <th>이름</th>
            <th>출근</th>
            <th>퇴근</th>
            <th>메모</th>
            <th>등록시간 / 관리</th>
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
              <td>
                {{ s['created_at'] }}
                {% if s['can_manage'] %}
                  <span class="actions">
                    <a href="{{ url_for('edit_shift', shift_id=s['id']) }}">수정</a>
                    <form method="post" action="{{ url_for('delete_shift', shift_id=s['id']) }}" onsubmit="return confirm('이 기록을 삭제할까요?');">
                      <button type="submit">삭제</button>
                    </form>
                  </span>
                {% endif %}
              </td>
            </tr>
          {% else %}
            <tr><td colspan="6">아직 등록된 출퇴근 계획이 없습니다.</td></tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>
</body>
</html>
"""


EDIT_SHIFT_HTML = """
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>출퇴근 기록 수정</title>
  <style>
    body {
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background:#f4f4f4;
      font-size:18px;
      line-height:1.5;
    }
    .wrap {
      max-width: 460px;
      margin:16px auto;
      padding:24px 20px;
      background:white;
      border-radius:16px;
      box-shadow:0 4px 12px rgba(0,0,0,0.05);
    }
    h1 { margin-bottom:16px; font-size:1.4rem; }
    label { display:block; margin-top:14px; font-weight:600; font-size:1rem; }
    input {
      width:100%;
      padding:10px;
      margin-top:6px;
      box-sizing:border-box;
      border-radius:10px;
      border:1px solid #ccc;
      font-size:1rem;
    }
    button {
      margin-top:20px;
      width:100%;
      padding:12px;
      border:none;
      border-radius:12px;
      background:#4f46e5;
      color:white;
      font-size:1.1rem;
      font-weight:600;
      cursor:pointer;
    }
    .small { margin-top:14px; font-size:0.95rem; color:#555; }
    a { color:#4f46e5; text-decoration:none; }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>출퇴근 기록 수정</h1>
    <form method="post">
      <label>날짜
        <input type="date" name="shift_date" value="{{ shift['shift_date'] }}" required>
      </label>
      <label>출근
        <input type="time" name="start_time" value="{{ shift['start_time'] }}" required>
      </label>
      <label>퇴근
        <input type="time" name="end_time" value="{{ shift['end_time'] }}" required>
      </label>
      <label>메모
        <input type="text" name="note" value="{{ shift['note'] or '' }}">
      </label>
      <button type="submit">저장하기</button>
    </form>
    <p class="small"><a href="{{ back_url }}">← 돌아가기</a></p>
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


def load_all_shifts(current_user, start=None, end=None):
    db = get_db()
    sql = """
        SELECT s.*, u.name
        FROM shifts s
        JOIN users u ON s.user_id = u.id
    """
    conditions = []
    params = []
    if start:
        conditions.append("s.shift_date >= ?")
        params.append(start)
    if end:
        conditions.append("s.shift_date <= ?")
        params.append(end)
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY s.shift_date ASC, s.start_time ASC"
    rows = db.execute(sql, params).fetchall()

    result = []
    for r in rows:
        d = dict(r)
        d["can_manage"] = (current_user["role"] == "owner") or (current_user["id"] == r["user_id"])
        result.append(d)
    return result


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

    shifts = load_all_shifts(user)
    today = datetime.utcnow().strftime("%Y-%m-%d")
    return render_template_string(
        DASHBOARD_HTML,
        title="기사 출퇴근 계획",
        user=user,
        shifts=shifts,
        today=today,
        filter_start=None,
        filter_end=None,
    )


# ---- 사업주 대시보드 ----

@app.route("/owner/dashboard")
def owner_dashboard():
    user, resp = require_login("owner")
    if resp:
        return resp

    start = request.args.get("start") or None
    end = request.args.get("end") or None

    shifts = load_all_shifts(user, start, end)
    today = datetime.utcnow().strftime("%Y-%m-%d")
    return render_template_string(
        DASHBOARD_HTML,
        title="사업주 대시보드",
        user=user,
        shifts=shifts,
        today=today,
        filter_start=start,
        filter_end=end,
    )


# ---- 출퇴근 기록 수정/삭제 ----

def can_manage_shift(user, shift_row):
    return (user["role"] == "owner") or (user["id"] == shift_row["user_id"])


@app.route("/shift/<int:shift_id>/edit", methods=["GET", "POST"])
def edit_shift(shift_id):
    user, resp = require_login()
    if resp:
        return resp

    db = get_db()
    shift = db.execute("SELECT * FROM shifts WHERE id = ?", (shift_id,)).fetchone()
    if not shift or not can_manage_shift(user, shift):
        return redirect(url_for("index"))

    if request.method == "POST":
        shift_date = request.form.get("shift_date")
        start_time = request.form.get("start_time")
        end_time = request.form.get("end_time")
        note = request.form.get("note", "").strip()
        if shift_date and start_time and end_time:
            db.execute(
                """
                UPDATE shifts
                SET shift_date = ?, start_time = ?, end_time = ?, note = ?
                WHERE id = ?
                """,
                (shift_date, start_time, end_time, note, shift_id),
            )
            db.commit()
            # 돌아갈 위치: 역할에 따라
            if user["role"] == "worker":
                return redirect(url_for("worker_dashboard"))
            else:
                return redirect(url_for("owner_dashboard"))

    back_url = url_for("worker_dashboard") if user["role"] == "worker" else url_for("owner_dashboard")
    return render_template_string(EDIT_SHIFT_HTML, shift=shift, back_url=back_url)


@app.route("/shift/<int:shift_id>/delete", methods=["POST"])
def delete_shift(shift_id):
    user, resp = require_login()
    if resp:
        return resp

    db = get_db()
    shift = db.execute("SELECT * FROM shifts WHERE id = ?", (shift_id,)).fetchone()
    if shift and can_manage_shift(user, shift):
        db.execute("DELETE FROM shifts WHERE id = ?", (shift_id,))
        db.commit()

    if user["role"] == "worker":
        return redirect(url_for("worker_dashboard"))
    else:
        return redirect(url_for("owner_dashboard"))


if __name__ == "__main__":
    app.run(debug=True)
