from flask import Flask, request, redirect, url_for, session, g, render_template_string
import sqlite3
import os
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-change-me")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "shift.db")

# -------------------------------------------------
# DB 유틸
# -------------------------------------------------
def get_db():
    if "db" not in g:
        first = not os.path.exists(DATABASE)
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        if first:
            init_db(g.db, if_not_exists=False)
        else:
            init_db(g.db, if_not_exists=True)
    return g.db


def init_db(db, if_not_exists: bool = False):
    opt = "IF NOT EXISTS " if if_not_exists else ""
    users_sql = f"""
        CREATE TABLE {opt}users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
    """
    shifts_sql = f"""
        CREATE TABLE {opt}shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            shift_date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL,
            mileage INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
    """
    mileage_sql = f"""
        CREATE TABLE {opt}mileage_adjustments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
    """
    payouts_sql = f"""
        CREATE TABLE {opt}payout_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            status TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
    """
    db.executescript(users_sql + shifts_sql + mileage_sql + payouts_sql)
    db.commit()
    ensure_schema(db)


def ensure_schema(db):
    # shifts 테이블에 mileage 컬럼 없으면 추가
    info = db.execute("PRAGMA table_info(shifts)").fetchall()
    cols = [row[1] for row in info]
    if "mileage" not in cols:
        db.execute("ALTER TABLE shifts ADD COLUMN mileage INTEGER NOT NULL DEFAULT 0;")
        db.commit()
    # mileage_adjustments 테이블 없으면 생성
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS mileage_adjustments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        """
    )
    # payout_requests 테이블 없으면 생성
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS payout_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            status TEXT NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL,
            completed_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        """
    )
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


def calculate_mileage(shift_date: str, start_time: str, end_time: str) -> int:
    """근무시간을 계산해서 1시간당 100 마일리지로 환산."""
    try:
        start_dt = datetime.strptime(f"{shift_date} {start_time}", "%Y-%m-%d %H:%M")
        end_dt = datetime.strptime(f"{shift_date} {end_time}", "%Y-%m-%d %H:%M")
        # 퇴근이 출근보다 같거나 빠르면 다음날 퇴근 처리
        if end_dt <= start_dt:
            end_dt += timedelta(days=1)
        hours = (end_dt - start_dt).total_seconds() / 3600.0
        mileage = int(round(hours * 100))
        if mileage < 0:
            mileage = 0
        return mileage
    except Exception:
        return 0


def get_user_mileage(user_id: int):
    """자동/수동/총 마일리지 계산."""
    db = get_db()
    auto_row = db.execute(
        "SELECT COALESCE(SUM(mileage),0) AS total FROM shifts WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    auto_mileage = auto_row["total"] if auto_row and auto_row["total"] is not None else 0

    manual_row = db.execute(
        "SELECT COALESCE(SUM(amount),0) AS total FROM mileage_adjustments WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    manual_mileage = (
        manual_row["total"] if manual_row and manual_row["total"] is not None else 0
    )

    total = auto_mileage + manual_mileage
    return auto_mileage, manual_mileage, total


# -------------------------------------------------
# 공통 CSS (모바일용, 큰 글씨)
# -------------------------------------------------
COMMON_CSS = """
body {
  font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  background:#f4f4f4;
  font-size:18px;
  line-height:1.5;
  margin:0;
  padding:0;
}
.wrap {
  max-width: 960px;
  margin:12px auto;
  padding:16px 12px 24px 12px;
  box-sizing:border-box;
}
.card {
  background:white;
  border-radius:16px;
  box-shadow:0 4px 12px rgba(0,0,0,0.05);
  padding:20px 16px;
}
.dk-header {
  display:flex;
  flex-direction:column;
  align-items:flex-start;
  gap:4px;
  margin-bottom:16px;
  padding-bottom:8px;
  border-bottom:1px solid #eee;
}
.dk-logo {
  font-weight:700;
  font-size:1.4rem;
  white-space:nowrap;
}
.dk-logo-text {
  white-space:nowrap;
}
.dk-nav a {
  margin-right:10px;
  font-size:1rem;
  text-decoration:none;
  color:#333;
}
.dk-nav a:hover { text-decoration:underline; }

h1 { margin:0 0 8px 0; font-size:1.5rem; }
h2 { margin:16px 0 8px 0; font-size:1.2rem; }

button {
  padding:10px 16px;
  border:none;
  border-radius:999px;
  background:#4f46e5;
  color:white;
  font-weight:600;
  cursor:pointer;
  font-size:1rem;
}
button.small {
  padding:6px 10px;
  font-size:0.85rem;
}
.small { font-size:0.9rem; color:#666; }
"""


# -------------------------------------------------
# 템플릿들 (Jinja용, f-string 아님)
# -------------------------------------------------
INDEX_HTML = """
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Shift Check - 출퇴근 계획</title>
  <style>
    {{ common_css|safe }}
    .role-btns a {
      display:block;
      margin:14px 0;
      padding:14px 16px;
      border-radius:10px;
      text-decoration:none;
      font-weight:600;
      font-size:1.1rem;
      text-align:center;
    }
    .worker { background:#e0f2ff; color:#0052a3; }
    .owner { background:#ffe8d5; color:#a34700; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <header class="dk-header">
        <div class="dk-logo">
          <span class="dk-logo-text">🛵 동탄콜</span>
        </div>
        <nav class="dk-nav">
          {% if user %}
            <a href="{{ url_for('profile') }}">내 정보</a>
            {% if user['role']=='worker' %}
              <a href="{{ url_for('worker_dashboard') }}">기사 대시보드</a>
            {% else %}
              <a href="{{ url_for('owner_dashboard') }}">사업주 대시보드</a>
            {% endif %}
            <a href="{{ url_for('logout') }}">로그아웃</a>
          {% endif %}
        </nav>
      </header>

      <h1>Shift Check</h1>
      <p>프리랜서/배달 기사 출퇴근 계획 공유 서비스</p>

      {% if user %}
        <p><strong>{{ user['name'] }}</strong>님은 이미 로그인 되어 있습니다.</p>
        {% if user['role'] == 'worker' %}
          <p><a class="worker" href="{{ url_for('worker_dashboard') }}">기사 화면으로 이동</a></p>
        {% else %}
          <p><a class="owner" href="{{ url_for('owner_dashboard') }}">사업주 화면으로 이동</a></p>
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
    {{ common_css|safe }}
    label {
      display:block;
      margin-top:14px;
      font-weight:600;
      font-size:1rem;
    }
    input {
      width:100%;
      padding:10px;
      margin-top:6px;
      box-sizing:border-box;
      border-radius:10px;
      border:1px solid #ccc;
      font-size:1rem;
    }
    .error { color:#c00; margin-top:10px; font-size:0.95rem; }
    a { color:#4f46e5; text-decoration:none; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <header class="dk-header">
        <div class="dk-logo">
          <span class="dk-logo-text">🛵 동탄콜</span>
        </div>
        <nav class="dk-nav">
          {% if user %}
            <a href="{{ url_for('profile') }}">내 정보</a>
            {% if user['role']=='worker' %}
              <a href="{{ url_for('worker_dashboard') }}">기사 대시보드</a>
            {% else %}
              <a href="{{ url_for('owner_dashboard') }}">사업주 대시보드</a>
            {% endif %}
            <a href="{{ url_for('logout') }}">로그아웃</a>
          {% endif %}
        </nav>
      </header>

      <h1>{{ heading }}</h1>
      <form method="post">
        {% if form_type == 'register' %}
          <label>이름
            <input type="text" name="name" required>
          </label>
        {% endif %}
        <label>전화번호
          <input type="text" name="phone" placeholder="예: 010-1234-5678" required>
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
    {{ common_css|safe }}
    .subtitle { color:#555; margin-bottom:8px; }
    .top-bar {
      display:flex;
      justify-content:space-between;
      align-items:flex-start;
      gap:10px;
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
      margin:12px 0 18px 0;
      padding:14px;
      background:#f9fafb;
      border-radius:12px;
      font-size:0.95rem;
    }
    label.inline {
      display:inline-block;
      margin:8px 8px 4px 0;
    }
    input[type="date"], input[type="text"], select {
      padding:8px 6px;
      border-radius:8px;
      border:1px solid #ccc;
      font-size:0.95rem;
    }

    .table-wrap { overflow-x:auto; margin-top:12px; }
    table { width:100%; border-collapse:collapse; font-size:0.9rem; min-width:720px; }
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
    .actions .delete-btn {
      background:#fee2e2;
      color:#b91c1c;
    }
    .actions .delete-btn:hover {
      background:#fecaca;
    }

    .filter-form {
      margin:8px 0 12px 0;
      padding:10px;
      background:#f9fafb;
      border-radius:12px;
      font-size:0.9rem;
    }
    .mileage-box {
      margin:8px 0 16px 0;
      padding:10px;
      background:#fef6e7;
      border-radius:12px;
      font-size:0.9rem;
    }
    .status-badge {
      display:inline-block;
      padding:2px 8px;
      border-radius:999px;
      font-size:0.8rem;
    }
    .status-pending {
      background:#e0f2ff;
      color:#1d4ed8;
    }
    .status-completed {
      background:#dcfce7;
      color:#15803d;
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <header class="dk-header">
        <div class="dk-logo">
          <span class="dk-logo-text">🛵 동탄콜</span>
        </div>
        <nav class="dk-nav">
          <a href="{{ url_for('profile') }}">내 정보</a>
          {% if user['role']=='worker' %}
            <a href="{{ url_for('worker_dashboard') }}">기사 대시보드</a>
          {% else %}
            <a href="{{ url_for('owner_dashboard') }}">사업주 대시보드</a>
          {% endif %}
          <a href="{{ url_for('logout') }}">로그아웃</a>
        </nav>
      </header>

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
        </div>
      </div>

      {% if user['role'] == 'worker' %}
        <h2>오늘/향후 근무 계획 입력</h2>
        <form method="post" class="shift-form">
          <label class="inline">날짜<br>
            <input type="date" name="shift_date" value="{{ today }}" required>
          </label>
          <label class="inline">출근<br>
            <input type="text" name="start_time" inputmode="numeric" pattern="[0-2][0-9]:[0-5][0-9]" placeholder="예: 09:00" required>
          </label>
          <label class="inline">퇴근<br>
            <input type="text" name="end_time" inputmode="numeric" pattern="[0-2][0-9]:[0-5][0-9]" placeholder="예: 18:00" required>
          </label>
          <label class="inline">메모<br>
            <input type="text" name="note" placeholder="예: 강남구 위주, 야간 가능" style="min-width:240px;">
          </label>
          <br>
          <button type="submit">저장</button>
          <p class="small">퇴근 시간이 출근 시간보다 빠르면 자동으로 <strong>다음날 퇴근</strong>으로 계산합니다. (24시간제, 예: 21:00 → 09:00)</p>
        </form>

        <div class="mileage-box">
          <p>현재 누적 마일리지: <strong>{{ total_mileage }}</strong></p>
          {% if pending_payout %}
            <p class="small">이미 출납요청이 접수되어 있습니다. 사업주 처리 후 다시 요청할 수 있습니다.</p>
          {% else %}
            <form method="post" action="{{ url_for('request_payout') }}" onsubmit="return confirm('현재 누적 마일리지 {{ total_mileage }}점을 출납요청 하시겠습니까?');">
              <button type="submit">마일리지 출납요청</button>
            </form>
          {% endif %}
        </div>
      {% else %}
        <div class="filter-form">
          <form method="get">
            <label class="inline">시작 날짜
              <input type="date" name="start" value="{{ filter_start or '' }}">
            </label>
            <label class="inline">끝 날짜
              <input type="date" name="end" value="{{ filter_end or '' }}">
            </label>
            <button type="submit">조회</button>
          </form>
          <p class="small">날짜를 비워두면 기본으로 8일(오늘~7일 후) 범위를 보여줍니다.</p>
        </div>

        <h2>마일리지 관리 (사업주 전용)</h2>
        <div class="mileage-box">
          <form method="post" action="{{ url_for('add_mileage') }}">
            <label class="inline">기사 선택<br>
              <select name="user_id" required>
                {% for w in workers %}
                  <option value="{{ w['id'] }}">{{ w['name'] }}</option>
                {% endfor %}
              </select>
            </label>
            <label class="inline">마일리지 (+/-)<br>
              <input type="number" name="amount" value="0" required>
            </label>
            <label class="inline">메모<br>
              <input type="text" name="note" placeholder="예: 보너스, 정정 등" style="min-width:220px;">
            </label>
            <br>
            <button type="submit">마일리지 조정 추가</button>
          </form>
          <p class="small">출퇴근 계획 자동 적립과 별도로, 보너스/정정이 필요할 때 사용합니다.</p>

          <div class="table-wrap" style="margin-top:8px;">
            <table>
              <thead>
                <tr>
                  <th>시간</th>
                  <th>기사</th>
                  <th>변경 마일리지</th>
                  <th>메모 / 관리</th>
                </tr>
              </thead>
              <tbody>
                {% for adj in owner_adjustments %}
                  <tr>
                    <td>{{ adj['created_at'] }}</td>
                    <td>{{ adj['name'] }}</td>
                    <td>{{ adj['amount'] }}</td>
                    <td>
                      {{ adj['note'] or '' }}
                      <span class="actions">
                        <form method="post" action="{{ url_for('delete_mileage', adj_id=adj['id']) }}" onsubmit="return confirm('이 마일리지 조정을 삭제할까요?');">
                          <button type="submit" class="small delete-btn">삭제</button>
                        </form>
                      </span>
                    </td>
                  </tr>
                {% else %}
                  <tr><td colspan="4">추가된 마일리지 조정 내역이 없습니다.</td></tr>
                {% endfor %}
              </tbody>
            </table>
          </div>
        </div>

        <h2>마일리지 출납요청</h2>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>요청시간</th>
                <th>기사</th>
                <th>요청 마일리지</th>
                <th>상태</th>
                <th>완료시간</th>
                <th>관리</th>
              </tr>
            </thead>
            <tbody>
              {% for req in payout_requests %}
                <tr>
                  <td>{{ req['created_at'] }}</td>
                  <td>{{ req['name'] }}</td>
                  <td>{{ req['amount'] }}</td>
                  <td>
                    {% if req['status'] == 'completed' %}
                      <span class="status-badge status-completed">출납완료</span>
                    {% else %}
                      <span class="status-badge status-pending">출납대기</span>
                    {% endif %}
                  </td>
                  <td>{{ req['completed_at'] or '' }}</td>
                  <td>
                    {% if req['status'] == 'pending' %}
                      <form method="post" action="{{ url_for('complete_payout', req_id=req['id']) }}" onsubmit="return confirm('이 출납요청을 완료 처리할까요? 해당 마일리지만큼 차감됩니다.');">
                        <button type="submit" class="small">출납완료</button>
                      </form>
                    {% endif %}
                  </td>
                </tr>
              {% else %}
                <tr><td colspan="6">접수된 출납요청이 없습니다.</td></tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
      {% endif %}

      <h2>전체 출퇴근 계획</h2>
      <p class="small">
        기사/사업주 모두 같은 화면을 보고 근무 계획을 맞출 수 있습니다. (1시간당 100 마일리지)<br>
        {% if user['role'] == 'worker' %}
          {% if not show_all_shifts %}
            최근 {{ shift_limit }}개만 표시 중입니다.
            <a href="{{ url_for('worker_dashboard', all_shifts='1') }}">전체 보기</a>
          {% else %}
            전체 기록을 표시 중입니다.
            <a href="{{ url_for('worker_dashboard') }}">최근 {{ shift_limit }}개만 보기</a>
          {% endif %}
        {% else %}
          {% if not show_all_shifts %}
            최근 {{ shift_limit }}개만 표시 중입니다.
            <a href="{{ url_for('owner_dashboard', start=filter_start or '', end=filter_end or '', all_shifts='1') }}">전체 보기</a>
          {% else %}
            전체 기록을 표시 중입니다.
            <a href="{{ url_for('owner_dashboard', start=filter_start or '', end=filter_end or '') }}">최근 {{ shift_limit }}개만 보기</a>
          {% endif %}
        {% endif %}
      </p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>날짜</th>
              <th>이름</th>
              <th>출근</th>
              <th>퇴근</th>
              <th>메모</th>
              <th>마일리지</th>
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
                <td>{{ s['mileage'] }}</td>
                <td>
                  {{ s['created_at'] }}
                  {% if s['can_manage'] %}
                    <span class="actions">
                      <a href="{{ url_for('edit_shift', shift_id=s['id']) }}">수정</a>
                      <form method="post" action="{{ url_for('delete_shift', shift_id=s['id']) }}" onsubmit="return confirm('이 기록을 삭제할까요?');">
                        <button type="submit" class="small delete-btn">삭제</button>
                      </form>
                    </span>
                  {% endif %}
                </td>
              </tr>
            {% else %}
              <tr><td colspan="7">아직 등록된 출퇴근 계획이 없습니다.</td></tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
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
    {{ common_css|safe }}
    label {
      display:block;
      margin-top:14px;
      font-weight:600;
      font-size:1rem;
    }
    input {
      width:100%;
      padding:10px;
      margin-top:6px;
      box-sizing:border-box;
      border-radius:10px;
      border:1px solid #ccc;
      font-size:1rem;
    }
    a { color:#4f46e5; text-decoration:none; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <header class="dk-header">
        <div class="dk-logo">
          <span class="dk-logo-text">🛵 동탄콜</span>
        </div>
        <nav class="dk-nav">
          {% if user['role']=='worker' %}
            <a href="{{ url_for('worker_dashboard') }}">기사 대시보드</a>
          {% else %}
            <a href="{{ url_for('owner_dashboard') }}">사업주 대시보드</a>
          {% endif %}
          <a href="{{ url_for('logout') }}">로그아웃</a>
        </nav>
      </header>

      <h1>출퇴근 기록 수정</h1>
      <form method="post">
        <label>날짜
          <input type="date" name="shift_date" value="{{ shift['shift_date'] }}" required>
        </label>
        <label>출근 (24시간제, 예: 09:00)
          <input type="text" name="start_time" value="{{ shift['start_time'] }}" inputmode="numeric" pattern="[0-2][0-9]:[0-5][0-9]" required>
        </label>
        <label>퇴근 (24시간제, 예: 18:00)
          <input type="text" name="end_time" value="{{ shift['end_time'] }}" inputmode="numeric" pattern="[0-2][0-9]:[0-5][0-9]" required>
        </label>
        <label>메모
          <input type="text" name="note" value="{{ shift['note'] or '' }}">
        </label>
        <button type="submit">저장하기</button>
      </form>
      <p class="small"><a href="{{ back_url }}">← 돌아가기</a></p>
    </div>
  </div>
</body>
</html>
"""


PROFILE_HTML = """
<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>내 정보 - 동탄콜</title>
  <style>
    {{ common_css|safe }}
    .summary-box {
      display:flex;
      flex-wrap:wrap;
      gap:12px;
      margin:12px 0 16px 0;
    }
    .summary-item {
      flex:1 1 120px;
      background:#f9fafb;
      border-radius:12px;
      padding:10px 12px;
    }
    .summary-item span {
      display:block;
      font-size:0.9rem;
      color:#666;
    }
    .summary-item strong {
      display:block;
      margin-top:4px;
      font-size:1.3rem;
    }
    .table-wrap { overflow-x:auto; margin-top:12px; }
    table { width:100%; border-collapse:collapse; font-size:0.9rem; min-width:640px; }
    th, td { border-bottom:1px solid #eee; padding:8px 6px; text-align:left; white-space:nowrap; }
    th { background:#f9fafb; }
    tr:nth-child(even) { background:#fafafa; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <header class="dk-header">
        <div class="dk-logo">
          <span class="dk-logo-text">🛵 동탄콜</span>
        </div>
        <nav class="dk-nav">
          {% if user['role']=='worker' %}
            <a href="{{ url_for('worker_dashboard') }}">기사 대시보드</a>
          {% else %}
            <a href="{{ url_for('owner_dashboard') }}">사업주 대시보드</a>
          {% endif %}
          <a href="{{ url_for('logout') }}">로그아웃</a>
        </nav>
      </header>

      <h1>내 정보</h1>
      <p class="small">
        이름: <strong>{{ user['name'] }}</strong><br>
        역할: {{ '기사' if user['role']=='worker' else '사업주' }}<br>
        전화번호: {{ user['email'] }}
      </p>

      <div class="summary-box">
        <div class="summary-item">
          <span>출퇴근 계획 자동 적립</span>
          <strong>{{ auto_mileage }}</strong>
        </div>
        <div class="summary-item">
          <span>사업주 수동 조정</span>
          <strong>{{ manual_mileage }}</strong>
        </div>
        <div class="summary-item">
          <span>총 마일리지</span>
          <strong>{{ total_mileage }}</strong>
        </div>
      </div>

      <h2>최근 출퇴근 기록</h2>
      <p class="small">
        {% if not all_mode %}
          최근 {{ recent_limit }}개만 표시 중입니다.
          <a href="{{ url_for('profile', all='1') }}">전체 보기</a>
        {% else %}
          전체 기록을 표시 중입니다.
          <a href="{{ url_for('profile') }}">최근 {{ recent_limit }}개만 보기</a>
        {% endif %}
      </p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>날짜</th>
              <th>출근</th>
              <th>퇴근</th>
              <th>메모</th>
              <th>마일리지</th>
              <th>등록시간</th>
            </tr>
          </thead>
          <tbody>
            {% for s in recent_shifts %}
              <tr>
                <td>{{ s['shift_date'] }}</td>
                <td>{{ s['start_time'] }}</td>
                <td>{{ s['end_time'] }}</td>
                <td>{{ s['note'] or '' }}</td>
                <td>{{ s['mileage'] }}</td>
                <td>{{ s['created_at'] }}</td>
              </tr>
            {% else %}
              <tr><td colspan="6">출퇴근 기록이 없습니다.</td></tr>
            {% endfor %}
          </tbody>
        </table>
      </div>

      <h2>마일리지 수동 조정 내역</h2>
      <p class="small">
        {% if not all_mode %}
          최근 {{ recent_limit }}개만 표시 중입니다.
          <a href="{{ url_for('profile', all='1') }}">전체 보기</a>
        {% else %}
          전체 기록을 표시 중입니다.
          <a href="{{ url_for('profile') }}">최근 {{ recent_limit }}개만 보기</a>
        {% endif %}
      </p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>시간</th>
              <th>변경 마일리지</th>
              <th>메모</th>
            </tr>
          </thead>
          <tbody>
            {% for adj in my_adjustments %}
              <tr>
                <td>{{ adj['created_at'] }}</td>
                <td>{{ adj['amount'] }}</td>
                <td>{{ adj['note'] or '' }}</td>
              </tr>
            {% else %}
              <tr><td colspan="3">마일리지 수동 조정 내역이 없습니다.</td></tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    </div>
  </div>
</body>
</html>
"""


# -------------------------------------------------
# 공통 헬퍼
# -------------------------------------------------
def require_login(role=None):
    user = get_current_user()
    if not user:
        return None, redirect(url_for("index"))
    if role and user["role"] != role:
        return None, redirect(url_for("index"))
    return user, None


def load_all_shifts(current_user, start=None, end=None, limit=None):
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
    if limit is not None:
        sql += " LIMIT ?"
        params.append(limit)
    rows = db.execute(sql, params).fetchall()

    result = []
    for r in rows:
        d = dict(r)
        d["can_manage"] = (current_user["role"] == "owner") or (current_user["id"] == r["user_id"])
        result.append(d)
    return result


def can_manage_shift(user, shift_row):
    return (user["role"] == "owner") or (user["id"] == shift_row["user_id"])


# -------------------------------------------------
# 라우트들
# -------------------------------------------------
@app.route("/")
def index():
    user = get_current_user()
    return render_template_string(INDEX_HTML, user=user, common_css=COMMON_CSS)


@app.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("index"))


# ----- 기사(워커) 인증 -----
@app.route("/worker/register", methods=["GET", "POST"])
def worker_register():
    error = None
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        if not name or not phone or not password:
            error = "모든 필드를 입력해 주세요."
        else:
            db = get_db()
            existing = db.execute("SELECT id FROM users WHERE email = ?", (phone,)).fetchone()
            if existing:
                error = "이미 등록된 전화번호입니다. 로그인 해 주세요."
            else:
                db.execute(
                    "INSERT INTO users (role, name, email, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                    (
                        "worker",
                        name,
                        phone,
                        generate_password_hash(password),
                        datetime.utcnow().isoformat(timespec="seconds"),
                    ),
                )
                db.commit()
                user = db.execute("SELECT * FROM users WHERE email = ?", (phone,)).fetchone()
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
        user=get_current_user(),
        common_css=COMMON_CSS,
    )


@app.route("/worker/login", methods=["GET", "POST"])
def worker_login():
    error = None
    if request.method == "POST":
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE email = ? AND role = 'worker'", (phone,)
        ).fetchone()
        if not user or not check_password_hash(user["password_hash"], password):
            error = "전화번호 또는 비밀번호가 올바르지 않습니다."
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
        user=get_current_user(),
        common_css=COMMON_CSS,
    )


# ----- 사업주 인증 -----
@app.route("/owner/register", methods=["GET", "POST"])
def owner_register():
    error = None
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        if not name or not phone or not password:
            error = "모든 필드를 입력해 주세요."
        else:
            db = get_db()
            existing = db.execute("SELECT id FROM users WHERE email = ?", (phone,)).fetchone()
            if existing:
                error = "이미 등록된 전화번호입니다. 로그인 해 주세요."
            else:
                db.execute(
                    "INSERT INTO users (role, name, email, password_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                    (
                        "owner",
                        name,
                        phone,
                        generate_password_hash(password),
                        datetime.utcnow().isoformat(timespec="seconds"),
                    ),
                )
                db.commit()
                user = db.execute("SELECT * FROM users WHERE email = ?", (phone,)).fetchone()
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
        user=get_current_user(),
        common_css=COMMON_CSS,
    )


@app.route("/owner/login", methods=["GET", "POST"])
def owner_login():
    error = None
    if request.method == "POST":
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE email = ? AND role = 'owner'", (phone,)
        ).fetchone()
        if not user or not check_password_hash(user["password_hash"], password):
            error = "전화번호 또는 비밀번호가 올바르지 않습니다."
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
        user=get_current_user(),
        common_css=COMMON_CSS,
    )


# ----- 기사 대시보드 -----
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
            mileage = calculate_mileage(shift_date, start_time, end_time)
            db.execute(
                """
                INSERT INTO shifts (user_id, shift_date, start_time, end_time, note, created_at, mileage)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user["id"],
                    shift_date,
                    start_time,
                    end_time,
                    note,
                    datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
                    mileage,
                ),
            )
            db.commit()

    # 전체 출퇴근 계획: 최근 N개 + 전체 보기 토글
    shift_limit = 50
    show_all_shifts = request.args.get("all_shifts") == "1"
    shifts = load_all_shifts(user, limit=None if show_all_shifts else shift_limit)

    today = datetime.utcnow().strftime("%Y-%m-%d")
    auto_m, manual_m, total_m = get_user_mileage(user["id"])
    pending_row = db.execute(
        "SELECT COUNT(*) AS c FROM payout_requests WHERE user_id = ? AND status = 'pending'",
        (user["id"],),
    ).fetchone()
    pending_payout = pending_row["c"] > 0 if pending_row else False

    return render_template_string(
        DASHBOARD_HTML,
        title="기사 출퇴근 계획",
        user=user,
        shifts=shifts,
        today=today,
        filter_start=None,
        filter_end=None,
        workers=[],
        owner_adjustments=[],
        payout_requests=[],
        total_mileage=total_m,
        pending_payout=pending_payout,
        show_all_shifts=show_all_shifts,
        shift_limit=shift_limit,
        common_css=COMMON_CSS,
    )


# ----- 사업주 대시보드 -----
@app.route("/owner/dashboard")
def owner_dashboard():
    user, resp = require_login("owner")
    if resp:
        return resp

    db = get_db()
    start = request.args.get("start") or None
    end = request.args.get("end") or None

    # 기간이 지정되지 않았다면 오늘 ~ 7일 후 기본 범위
    if not start and not end:
        today_date = datetime.utcnow().date()
        start = today_date.strftime("%Y-%m-%d")
        end = (today_date + timedelta(days=7)).strftime("%Y-%m-%d")

    shift_limit = 50
    show_all_shifts = request.args.get("all_shifts") == "1"

    shifts = load_all_shifts(user, start, end, limit=None if show_all_shifts else shift_limit)
    today = datetime.utcnow().strftime("%Y-%m-%d")
    workers = db.execute("SELECT id, name FROM users WHERE role='worker' ORDER BY name").fetchall()
    owner_adjustments = db.execute(
        """
        SELECT m.*, u.name
        FROM mileage_adjustments m
        JOIN users u ON m.user_id = u.id
        ORDER BY m.created_at DESC
        LIMIT 50
        """
    ).fetchall()
    payout_requests = db.execute(
        """
        SELECT p.*, u.name
        FROM payout_requests p
        JOIN users u ON p.user_id = u.id
        ORDER BY p.created_at DESC
        LIMIT 50
        """
    ).fetchall()
    return render_template_string(
        DASHBOARD_HTML,
        title="사업주 대시보드",
        user=user,
        shifts=shifts,
        today=today,
        filter_start=start,
        filter_end=end,
        workers=workers,
        owner_adjustments=owner_adjustments,
        payout_requests=payout_requests,
        total_mileage=0,
        pending_payout=False,
        show_all_shifts=show_all_shifts,
        shift_limit=shift_limit,
        common_css=COMMON_CSS,
    )


# ----- 출퇴근 기록 수정/삭제 -----
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
            mileage = calculate_mileage(shift_date, start_time, end_time)
            db.execute(
                """
                UPDATE shifts
                SET shift_date = ?, start_time = ?, end_time = ?, note = ?, mileage = ?
                WHERE id = ?
                """,
                (shift_date, start_time, end_time, note, mileage, shift_id),
            )
            db.commit()
            if user["role"] == "worker":
                return redirect(url_for("worker_dashboard"))
            else:
                return redirect(url_for("owner_dashboard"))

    back_url = url_for("worker_dashboard") if user["role"] == "worker" else url_for("owner_dashboard")
    return render_template_string(
        EDIT_SHIFT_HTML,
        user=user,
        shift=shift,
        back_url=back_url,
        common_css=COMMON_CSS,
    )


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


# ----- 마일리지 수동 조정 (사업주) -----
@app.route("/owner/mileage/add", methods=["POST"])
def add_mileage():
    user, resp = require_login("owner")
    if resp:
        return resp

    db = get_db()
    user_id = request.form.get("user_id")
    amount_raw = request.form.get("amount", "0").strip()
    note = request.form.get("note", "").strip()
    try:
        amount = int(amount_raw)
    except ValueError:
        amount = 0

    if user_id and amount != 0:
        db.execute(
            """
            INSERT INTO mileage_adjustments (user_id, amount, note, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                int(user_id),
                amount,
                note,
                datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
            ),
        )
        db.commit()

    return redirect(url_for("owner_dashboard"))


@app.route("/owner/mileage/<int:adj_id>/delete", methods=["POST"])
def delete_mileage(adj_id):
    user, resp = require_login("owner")
    if resp:
        return resp

    db = get_db()
    db.execute("DELETE FROM mileage_adjustments WHERE id = ?", (adj_id,))
    db.commit()
    return redirect(url_for("owner_dashboard"))


# ----- 마일리지 출납 요청 / 처리 -----
@app.route("/worker/payout/request", methods=["POST"])
def request_payout():
    user, resp = require_login("worker")
    if resp:
        return resp

    db = get_db()
    # 이미 대기 중인 요청이 있으면 새로 만들지 않음
    pending = db.execute(
        "SELECT 1 FROM payout_requests WHERE user_id = ? AND status = 'pending' LIMIT 1",
        (user["id"],),
    ).fetchone()
    if pending:
        return redirect(url_for("worker_dashboard"))

    _, _, total_m = get_user_mileage(user["id"])
    if total_m <= 0:
        return redirect(url_for("worker_dashboard"))

    db.execute(
        """
        INSERT INTO payout_requests (user_id, amount, status, note, created_at, completed_at)
        VALUES (?, ?, 'pending', ?, ?, NULL)
        """,
        (
            user["id"],
            total_m,
            "마일리지 출납요청",
            datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
        ),
    )
    db.commit()
    return redirect(url_for("worker_dashboard"))


@app.route("/owner/payout/<int:req_id>/complete", methods=["POST"])
def complete_payout(req_id):
    user, resp = require_login("owner")
    if resp:
        return resp

    db = get_db()
    req = db.execute("SELECT * FROM payout_requests WHERE id = ?", (req_id,)).fetchone()
    if not req or req["status"] == "completed":
        return redirect(url_for("owner_dashboard"))

    # 상태 변경
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    db.execute(
        "UPDATE payout_requests SET status = 'completed', completed_at = ? WHERE id = ?",
        (now_str, req_id),
    )
    # 마일리지 차감 기록 추가
    db.execute(
        """
        INSERT INTO mileage_adjustments (user_id, amount, note, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            req["user_id"],
            -req["amount"],
            "출납완료 차감",
            now_str,
        ),
    )
    db.commit()
    return redirect(url_for("owner_dashboard"))


# ----- 내 정보 페이지 -----
@app.route("/me")
def profile():
    user, resp = require_login()
    if resp:
        return resp

    db = get_db()
    auto_mileage, manual_mileage, total_mileage = get_user_mileage(user["id"])

    all_mode = request.args.get("all") == "1"
    recent_limit = 20

    if all_mode:
        recent_shifts = db.execute(
            """
            SELECT shift_date, start_time, end_time, note, mileage, created_at
            FROM shifts
            WHERE user_id = ?
            ORDER BY shift_date DESC, start_time DESC
            """,
            (user["id"],),
        ).fetchall()

        my_adjustments = db.execute(
            """
            SELECT amount, note, created_at
            FROM mileage_adjustments
            WHERE user_id = ?
            ORDER BY created_at DESC
            """,
            (user["id"],),
        ).fetchall()
    else:
        recent_shifts = db.execute(
            """
            SELECT shift_date, start_time, end_time, note, mileage, created_at
            FROM shifts
            WHERE user_id = ?
            ORDER BY shift_date DESC, start_time DESC
            LIMIT ?
            """,
            (user["id"], recent_limit),
        ).fetchall()

        my_adjustments = db.execute(
            """
            SELECT amount, note, created_at
            FROM mileage_adjustments
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user["id"], recent_limit),
        ).fetchall()

    return render_template_string(
        PROFILE_HTML,
        user=user,
        auto_mileage=auto_mileage,
        manual_mileage=manual_mileage,
        total_mileage=total_mileage,
        recent_shifts=recent_shifts,
        my_adjustments=my_adjustments,
        all_mode=all_mode,
        recent_limit=recent_limit,
        common_css=COMMON_CSS,
    )


if __name__ == "__main__":
    app.run(debug=True)
