import csv
import json
import os
import random
import threading
import time
import uuid
from datetime import datetime
from functools import wraps

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from cryptography.fernet import Fernet
from flask import Flask, jsonify, render_template, request, session

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24))

# 環境變數設定 (可選，用於預設值)
DEFAULT_TEL_TOKEN = os.environ.get("TEL_TOKEN")
DEFAULT_CHAT_ID = os.environ.get("CHAT_ID")

absolutepath = os.path.abspath(__file__)
SKIP_DATES_FILE = os.path.join(os.path.dirname(absolutepath), "skip_dates.json")
PUNCH_HISTORY_FILE = os.path.join(os.path.dirname(absolutepath), "punch_history.json")
USERS_FILE = os.path.join(os.path.dirname(absolutepath), "users.json")
ENCRYPTION_KEY_FILE = os.path.join(os.path.dirname(absolutepath), ".encryption_key")


# ============ 加密相關 ============
def get_or_create_encryption_key():
    """取得或建立加密金鑰"""
    if os.path.exists(ENCRYPTION_KEY_FILE):
        with open(ENCRYPTION_KEY_FILE, "rb") as f:
            return f.read()
    else:
        key = Fernet.generate_key()
        with open(ENCRYPTION_KEY_FILE, "wb") as f:
            f.write(key)
        return key


def encrypt_password(password):
    """加密密碼"""
    key = get_or_create_encryption_key()
    f = Fernet(key)
    return f.encrypt(password.encode()).decode()


def decrypt_password(encrypted_password):
    """解密密碼"""
    key = get_or_create_encryption_key()
    f = Fernet(key)
    return f.decrypt(encrypted_password.encode()).decode()


# ============ 用戶管理 ============
def load_users():
    """載入所有用戶設定"""
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_users(users):
    """儲存用戶設定"""
    with open(USERS_FILE, "w") as f:
        json.dump(users, f, ensure_ascii=False, indent=2)


def get_user(acc):
    """取得單一用戶"""
    users = load_users()
    return users.get(acc)


def save_user(acc, user_data):
    """儲存單一用戶"""
    users = load_users()
    users[acc] = user_data
    save_users(users)


def load_skip_dates():
    """載入不打卡日期"""
    if os.path.exists(SKIP_DATES_FILE):
        try:
            with open(SKIP_DATES_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_skip_dates(dates):
    """儲存不打卡日期"""
    with open(SKIP_DATES_FILE, "w") as f:
        json.dump(dates, f, ensure_ascii=False, indent=2)


def load_punch_history():
    """載入打卡紀錄"""
    if os.path.exists(PUNCH_HISTORY_FILE):
        try:
            with open(PUNCH_HISTORY_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_punch_history(history):
    """儲存打卡紀錄"""
    with open(PUNCH_HISTORY_FILE, "w") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def add_punch_record(success, message):
    """新增一筆打卡紀錄"""
    history = load_punch_history()
    now = datetime.now()
    record = {
        "date": now.strftime("%Y%m%d"),
        "time": now.strftime("%H:%M:%S"),
        "datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "success": success,
        "message": message
    }
    history.append(record)
    # 只保留最近 100 筆
    history = history[-100:]
    save_punch_history(history)
    return record


def login_required(f):
    """檢查是否已登入的裝飾器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "auth_token" not in session:
            return jsonify({"success": False, "message": "請先登入"}), 401
        return f(*args, **kwargs)
    return decorated_function


def get_new_token(uno, acc, password):
    """取得 104 登入 token"""
    url = "https://pro.104.com.tw/prohrm/api/login/token"
    data = {
        "uno": uno,
        "acc": acc,
        "pwd": password,
        "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzb3VyY2UiOiJhcHAtcHJvZCIsImNpZCI6MCwiaWF0IjoxNTUzNzUzMTQwfQ.ieJiJtNsseSO5fxNH1XTa6bqHZ0zUyoPVUYPNtOj4TM",
    }
    try:
        resp = requests.post(url, data=data, timeout=10)
        if resp.status_code == 200 and resp.json().get("data"):
            return resp.json()["data"]["access"], None
        return None, "登入失敗，請檢查帳號密碼"
    except Exception as e:
        return None, f"連線錯誤: {str(e)}"


def gen_device_id(acc):
    """產生裝置 ID"""
    device_id = uuid.uuid5(uuid.NAMESPACE_DNS, acc)
    return str(device_id).upper()


def get_location():
    """取得隨機 GPS 位置"""
    lat = random.uniform(25.0578304, 25.0584464)
    lon = random.uniform(121.5342305, 121.5349235)
    return lat, lon


def get_workday():
    """取得工作日曆表（自動讀取所有年份）"""
    import glob
    pat = os.path.dirname(absolutepath)
    workday = {}
    # 自動讀取所有行事曆 CSV 檔案
    for filepath in glob.glob(f"{pat}/*辦公日曆表*.csv"):
        try:
            with open(filepath, newline="") as f:
                reader = csv.reader(f)
                for row in reader:
                    if row and len(row) >= 3:
                        workday[row[0]] = row[2]
        except Exception:
            pass
    return workday


def send_telegram_notify(tel_token, chat_id, message):
    """發送 Telegram 通知"""
    if not tel_token or not chat_id:
        return False
    try:
        data = {"chat_id": chat_id, "text": message}
        requests.post(
            f"https://api.telegram.org/bot{tel_token}/sendMessage",
            data=data,
            timeout=10
        )
        return True
    except Exception:
        return False


def do_punch(auth_token, acc):
    """執行打卡"""
    url = "https://pro.104.com.tw/prohrm/api/app/card/gps"
    lat, lon = get_location()
    data = {"deviceId": gen_device_id(acc), "latitude": lat, "longitude": lon}
    headers = {"Authorization": "Bearer " + auth_token}

    try:
        resp = requests.post(url, data=data, headers=headers, timeout=10)
        if resp.status_code == 200:
            return True, "打卡成功！"
        return False, f"打卡失敗: {resp.text}"
    except Exception as e:
        return False, f"連線錯誤: {str(e)}"


# ============ 排程器相關 ============
scheduler = BackgroundScheduler()
scheduler_status = {"running": False, "last_check": None, "next_jobs": []}


def is_within_punch_window(current_time, punch_time, delay_max):
    """檢查當前時間是否在打卡時間窗口內"""
    try:
        current_h, current_m = map(int, current_time.split(":"))
        punch_h, punch_m = map(int, punch_time.split(":"))

        current_minutes = current_h * 60 + current_m
        punch_start = punch_h * 60 + punch_m
        punch_end = punch_start + delay_max

        return punch_start <= current_minutes <= punch_end
    except Exception:
        return False


def migrate_user_to_schedules(user):
    """將舊格式用戶資料轉換為新的多排程格式"""
    if "schedules" in user:
        return user  # 已經是新格式

    # 轉換舊格式到新格式
    schedules = []
    if user.get("punch_time"):
        schedules.append({
            "id": "schedule_1",
            "name": "上班",
            "time": user.get("punch_time", "09:00"),
            "enabled": user.get("enabled", False),
            "random_delay_min": user.get("random_delay_min", 0),
            "random_delay_max": user.get("random_delay_max", 15),
            "last_punch_date": user.get("last_punch_date", "")
        })

    user["schedules"] = schedules
    # 保留舊欄位以便相容，但主要使用 schedules
    return user


def execute_scheduled_punch(user_data, schedule):
    """執行排程打卡（帶隨機延遲）"""
    acc = user_data.get("acc")
    schedule_name = schedule.get("name", "排程")
    schedule_id = schedule.get("id")
    delay_min = schedule.get("random_delay_min", 0)
    delay_max = schedule.get("random_delay_max", 15)

    # 隨機延遲（秒）
    delay_seconds = random.randint(delay_min * 60, delay_max * 60)
    if delay_seconds > 0:
        time.sleep(delay_seconds)

    try:
        # 解密密碼並取得 token
        password = decrypt_password(user_data.get("password", ""))
        auth_token, error = get_new_token(user_data.get("uno"), acc, password)

        if not auth_token:
            message = f"[自動打卡-{schedule_name}] {acc} - 登入失敗: {error}"
            print(message)
            return

        # 執行打卡
        success, punch_message = do_punch(auth_token, acc)
        now = datetime.now()

        # 記錄打卡歷史
        add_punch_record(success, f"[自動-{schedule_name}] {punch_message}")

        # 更新該排程的最後打卡日期
        users = load_users()
        if acc in users:
            user = users[acc]
            user = migrate_user_to_schedules(user)
            for s in user.get("schedules", []):
                if s.get("id") == schedule_id:
                    s["last_punch_date"] = now.strftime("%Y%m%d")
                    break
            save_user(acc, user)

        # 發送 Telegram 通知
        tel_token = user_data.get("telegram_token") or DEFAULT_TEL_TOKEN
        chat_id = user_data.get("telegram_chat_id") or DEFAULT_CHAT_ID
        if tel_token and chat_id:
            notify_msg = f"[自動打卡-{schedule_name}] {now.strftime('%Y-%m-%d %H:%M:%S')} - {punch_message}"
            send_telegram_notify(tel_token, chat_id, notify_msg)

        print(f"[自動打卡-{schedule_name}] {now.strftime('%H:%M:%S')} {acc} - {punch_message}")

    except Exception as e:
        print(f"[自動打卡-{schedule_name}] {acc} - 錯誤: {str(e)}")


def check_and_punch():
    """每分鐘檢查是否有用戶需要打卡"""
    now = datetime.now()
    today = now.strftime("%Y%m%d")
    current_time = now.strftime("%H:%M")

    scheduler_status["last_check"] = now.strftime("%Y-%m-%d %H:%M:%S")

    workday = get_workday()
    skip_dates = load_skip_dates()
    users = load_users()

    for acc, user in users.items():
        # 轉換為新格式
        user = migrate_user_to_schedules(user)

        # 檢查是否為工作日
        if workday.get(today) != "0":
            continue

        # 檢查是否為跳過日
        if today in skip_dates:
            continue

        # 遍歷每個排程
        for schedule in user.get("schedules", []):
            # 檢查該排程是否啟用
            if not schedule.get("enabled"):
                continue

            # 檢查該排程今天是否已打卡
            if schedule.get("last_punch_date") == today:
                continue

            # 檢查時間窗口
            punch_time = schedule.get("time", "09:00")
            delay_max = schedule.get("random_delay_max", 15)

            if is_within_punch_window(current_time, punch_time, delay_max):
                # 在背景執行打卡
                threading.Thread(
                    target=execute_scheduled_punch,
                    args=(user.copy(), schedule.copy())
                ).start()


def start_scheduler():
    """啟動排程器"""
    if not scheduler.running:
        scheduler.add_job(check_and_punch, 'interval', minutes=1, id='punch_checker')
        scheduler.start()
        scheduler_status["running"] = True
        print("[排程器] 已啟動，每分鐘檢查一次")


@app.route("/")
def index():
    """首頁"""
    return render_template("index.html")


@app.route("/api/login", methods=["POST"])
def login():
    """登入 API"""
    data = request.get_json()
    uno = data.get("uno", "").strip()
    acc = data.get("acc", "").strip()
    password = data.get("password", "")

    if not uno or not acc or not password:
        return jsonify({"success": False, "message": "請填寫所有欄位"})

    auth_token, error = get_new_token(uno, acc, password)

    if auth_token:
        session["auth_token"] = auth_token
        session["uno"] = uno
        session["acc"] = acc
        session["password"] = password
        return jsonify({"success": True, "message": "登入成功"})

    return jsonify({"success": False, "message": error})


@app.route("/api/logout", methods=["POST"])
def logout():
    """登出 API"""
    session.clear()
    return jsonify({"success": True, "message": "已登出"})


@app.route("/api/punch", methods=["POST"])
@login_required
def punch():
    """手動打卡 API"""
    auth_token = session.get("auth_token")
    acc = session.get("acc")

    # 重新取得 token (確保 token 有效)
    uno = session.get("uno")
    password = session.get("password")
    new_token, error = get_new_token(uno, acc, password)

    if not new_token:
        session.clear()
        return jsonify({"success": False, "message": "Token 已過期，請重新登入"})

    session["auth_token"] = new_token

    success, message = do_punch(new_token, acc)

    # 記錄打卡歷史
    record = add_punch_record(success, message)

    # 發送 Telegram 通知 (如果有設定)
    tel_token = DEFAULT_TEL_TOKEN
    chat_id = DEFAULT_CHAT_ID
    if tel_token and chat_id:
        notify_msg = f"[手動打卡] {record['datetime']} - {message}"
        send_telegram_notify(tel_token, chat_id, notify_msg)

    return jsonify({
        "success": success,
        "message": message,
        "timestamp": record['datetime']
    })


@app.route("/api/status")
def status():
    """取得目前狀態"""
    logged_in = "auth_token" in session
    now = datetime.now()
    today = now.strftime("%Y%m%d")

    workday = get_workday()
    skip_dates = load_skip_dates()
    is_workday = workday.get(today, "0") == "0"
    is_skip_date = today in skip_dates

    return jsonify({
        "logged_in": logged_in,
        "acc": session.get("acc") if logged_in else None,
        "current_time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "today": today,
        "is_workday": is_workday,
        "is_skip_date": is_skip_date,
        "workday_text": "不打卡日" if is_skip_date else ("工作日" if is_workday else "假日")
    })


@app.route("/api/skip-dates", methods=["GET"])
@login_required
def get_skip_dates():
    """取得不打卡日期列表"""
    skip_dates = load_skip_dates()
    # 轉換格式方便前端顯示
    formatted = []
    for d in skip_dates:
        try:
            dt = datetime.strptime(d, "%Y%m%d")
            formatted.append({
                "date": d,
                "display": dt.strftime("%Y-%m-%d"),
                "weekday": ["一", "二", "三", "四", "五", "六", "日"][dt.weekday()]
            })
        except Exception:
            formatted.append({"date": d, "display": d, "weekday": ""})
    return jsonify({"success": True, "dates": formatted})


@app.route("/api/skip-dates", methods=["POST"])
@login_required
def add_skip_date():
    """新增不打卡日期"""
    data = request.get_json()
    date = data.get("date", "").strip()

    if not date:
        return jsonify({"success": False, "message": "請選擇日期"})

    # 轉換日期格式 (YYYY-MM-DD -> YYYYMMDD)
    try:
        dt = datetime.strptime(date, "%Y-%m-%d")
        date_key = dt.strftime("%Y%m%d")
    except ValueError:
        return jsonify({"success": False, "message": "日期格式錯誤"})

    skip_dates = load_skip_dates()

    if date_key in skip_dates:
        return jsonify({"success": False, "message": "此日期已存在"})

    skip_dates.append(date_key)
    skip_dates.sort()
    save_skip_dates(skip_dates)

    return jsonify({"success": True, "message": f"已新增 {date}"})


@app.route("/api/skip-dates/<date>", methods=["DELETE"])
@login_required
def delete_skip_date(date):
    """刪除不打卡日期"""
    skip_dates = load_skip_dates()

    if date not in skip_dates:
        return jsonify({"success": False, "message": "日期不存在"})

    skip_dates.remove(date)
    save_skip_dates(skip_dates)

    return jsonify({"success": True, "message": "已刪除"})


@app.route("/api/punch-history")
@login_required
def get_punch_history():
    """取得打卡紀錄"""
    history = load_punch_history()
    # 反轉順序，最新的在前面
    return jsonify({"success": True, "history": list(reversed(history))})


@app.route("/api/calendar/<year_month>")
@login_required
def get_calendar_data(year_month):
    """取得月曆資料"""
    try:
        year = int(year_month[:4])
        month = int(year_month[4:])
    except (ValueError, IndexError):
        return jsonify({"success": False, "message": "日期格式錯誤"})

    # 取得該月所有日期
    import calendar
    cal = calendar.Calendar(firstweekday=6)  # 週日開始
    month_days = cal.monthdayscalendar(year, month)

    # 載入資料
    workday = get_workday()
    skip_dates = load_skip_dates()
    punch_history = load_punch_history()

    # 建立打卡日期對照表
    punch_dates = {}
    for record in punch_history:
        date = record.get("date")
        if date:
            if date not in punch_dates:
                punch_dates[date] = []
            punch_dates[date].append(record)

    # 建立月曆資料
    calendar_data = []
    for week in month_days:
        week_data = []
        for day in week:
            if day == 0:
                week_data.append(None)
            else:
                date_str = f"{year}{month:02d}{day:02d}"
                day_info = {
                    "day": day,
                    "date": date_str,
                    "is_workday": workday.get(date_str, "0") == "0",
                    "is_skip": date_str in skip_dates,
                    "punch_records": punch_dates.get(date_str, [])
                }
                week_data.append(day_info)
        calendar_data.append(week_data)

    return jsonify({
        "success": True,
        "year": year,
        "month": month,
        "calendar": calendar_data
    })


# ============ 自動打卡設定 API ============
@app.route("/api/user/settings", methods=["GET"])
@login_required
def get_user_settings():
    """取得當前用戶的自動打卡設定"""
    acc = session.get("acc")
    user = get_user(acc)

    if not user:
        return jsonify({
            "success": True,
            "settings": {
                "schedules": [],
                "telegram_token": "",
                "telegram_chat_id": ""
            }
        })

    # 轉換為新格式
    user = migrate_user_to_schedules(user)

    return jsonify({
        "success": True,
        "settings": {
            "schedules": user.get("schedules", []),
            "telegram_token": user.get("telegram_token", ""),
            "telegram_chat_id": user.get("telegram_chat_id", "")
        }
    })


@app.route("/api/user/settings", methods=["POST"])
@login_required
def save_user_settings():
    """儲存自動打卡設定"""
    data = request.get_json()
    acc = session.get("acc")
    uno = session.get("uno")
    password = session.get("password")

    schedules = data.get("schedules", [])

    # 驗證每個排程
    for schedule in schedules:
        # 驗證打卡時間格式
        punch_time = schedule.get("time", "09:00")
        try:
            datetime.strptime(punch_time, "%H:%M")
        except ValueError:
            return jsonify({"success": False, "message": f"排程「{schedule.get('name', '')}」的時間格式錯誤"})

        # 驗證延遲範圍
        delay_min = int(schedule.get("random_delay_min", 0))
        delay_max = int(schedule.get("random_delay_max", 15))
        if delay_min < 0 or delay_max < 0 or delay_min > delay_max:
            return jsonify({"success": False, "message": f"排程「{schedule.get('name', '')}」的延遲時間設定錯誤"})
        if delay_max > 60:
            return jsonify({"success": False, "message": "最大延遲不能超過 60 分鐘"})

    # 取得或建立用戶資料
    user = get_user(acc) or {}
    user = migrate_user_to_schedules(user)

    # 保留每個排程的 last_punch_date
    existing_schedules = {s.get("id"): s for s in user.get("schedules", [])}
    for schedule in schedules:
        if schedule.get("id") in existing_schedules:
            schedule["last_punch_date"] = existing_schedules[schedule["id"]].get("last_punch_date", "")
        elif "last_punch_date" not in schedule:
            schedule["last_punch_date"] = ""

    # 更新用戶資料
    user.update({
        "uno": uno,
        "acc": acc,
        "password": encrypt_password(password),
        "schedules": schedules,
        "telegram_token": data.get("telegram_token", ""),
        "telegram_chat_id": data.get("telegram_chat_id", "")
    })

    save_user(acc, user)

    enabled_count = sum(1 for s in schedules if s.get("enabled"))
    return jsonify({
        "success": True,
        "message": f"設定已儲存，{enabled_count} 個排程已啟用" if enabled_count > 0 else "設定已儲存"
    })


@app.route("/api/user/schedule", methods=["POST"])
@login_required
def add_schedule():
    """新增排程"""
    data = request.get_json()
    acc = session.get("acc")
    uno = session.get("uno")
    password = session.get("password")

    # 驗證打卡時間格式
    punch_time = data.get("time", "09:00")
    try:
        datetime.strptime(punch_time, "%H:%M")
    except ValueError:
        return jsonify({"success": False, "message": "時間格式錯誤"})

    # 取得或建立用戶資料
    user = get_user(acc) or {
        "uno": uno,
        "acc": acc,
        "password": encrypt_password(password),
        "schedules": [],
        "telegram_token": "",
        "telegram_chat_id": ""
    }
    user = migrate_user_to_schedules(user)

    # 產生新的排程 ID
    existing_ids = [s.get("id", "") for s in user.get("schedules", [])]
    new_id = f"schedule_{len(existing_ids) + 1}"
    while new_id in existing_ids:
        new_id = f"schedule_{int(new_id.split('_')[1]) + 1}"

    new_schedule = {
        "id": new_id,
        "name": data.get("name", "新排程"),
        "time": punch_time,
        "enabled": data.get("enabled", True),
        "random_delay_min": int(data.get("random_delay_min", 0)),
        "random_delay_max": int(data.get("random_delay_max", 15)),
        "last_punch_date": ""
    }

    user["schedules"].append(new_schedule)
    user["uno"] = uno
    user["acc"] = acc
    user["password"] = encrypt_password(password)
    save_user(acc, user)

    return jsonify({
        "success": True,
        "message": f"已新增排程「{new_schedule['name']}」",
        "schedule": new_schedule
    })


@app.route("/api/user/schedule/<schedule_id>", methods=["PUT"])
@login_required
def update_schedule(schedule_id):
    """更新排程"""
    data = request.get_json()
    acc = session.get("acc")

    user = get_user(acc)
    if not user:
        return jsonify({"success": False, "message": "用戶不存在"})

    user = migrate_user_to_schedules(user)

    # 找到並更新排程
    found = False
    for schedule in user.get("schedules", []):
        if schedule.get("id") == schedule_id:
            if "name" in data:
                schedule["name"] = data["name"]
            if "time" in data:
                try:
                    datetime.strptime(data["time"], "%H:%M")
                    schedule["time"] = data["time"]
                except ValueError:
                    return jsonify({"success": False, "message": "時間格式錯誤"})
            if "enabled" in data:
                schedule["enabled"] = data["enabled"]
            if "random_delay_min" in data:
                schedule["random_delay_min"] = int(data["random_delay_min"])
            if "random_delay_max" in data:
                schedule["random_delay_max"] = int(data["random_delay_max"])
            found = True
            break

    if not found:
        return jsonify({"success": False, "message": "排程不存在"})

    save_user(acc, user)
    return jsonify({"success": True, "message": "排程已更新"})


@app.route("/api/user/schedule/<schedule_id>", methods=["DELETE"])
@login_required
def delete_schedule(schedule_id):
    """刪除排程"""
    acc = session.get("acc")

    user = get_user(acc)
    if not user:
        return jsonify({"success": False, "message": "用戶不存在"})

    user = migrate_user_to_schedules(user)

    # 找到並刪除排程
    schedules = user.get("schedules", [])
    original_len = len(schedules)
    user["schedules"] = [s for s in schedules if s.get("id") != schedule_id]

    if len(user["schedules"]) == original_len:
        return jsonify({"success": False, "message": "排程不存在"})

    save_user(acc, user)
    return jsonify({"success": True, "message": "排程已刪除"})


@app.route("/api/scheduler/status")
def get_scheduler_status():
    """取得排程器狀態"""
    users = load_users()
    enabled_schedules_count = 0
    for acc, user in users.items():
        user = migrate_user_to_schedules(user)
        for schedule in user.get("schedules", []):
            if schedule.get("enabled"):
                enabled_schedules_count += 1

    return jsonify({
        "success": True,
        "running": scheduler_status["running"],
        "last_check": scheduler_status["last_check"],
        "enabled_schedules_count": enabled_schedules_count
    })


if __name__ == "__main__":
    # 啟動排程器
    start_scheduler()
    app.run(debug=True, host="0.0.0.0", port=5001)
