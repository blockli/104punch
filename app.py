import csv
import json
import os
import random
import uuid
from datetime import datetime
from functools import wraps

import requests
from flask import Flask, jsonify, render_template, request, session

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24))

# 環境變數設定 (可選，用於預設值)
DEFAULT_TEL_TOKEN = os.environ.get("TEL_TOKEN")
DEFAULT_CHAT_ID = os.environ.get("CHAT_ID")

absolutepath = os.path.abspath(__file__)
SKIP_DATES_FILE = os.path.join(os.path.dirname(absolutepath), "skip_dates.json")
PUNCH_HISTORY_FILE = os.path.join(os.path.dirname(absolutepath), "punch_history.json")


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
    """取得工作日曆表"""
    pat = os.path.dirname(absolutepath)
    workday = {}
    try:
        with open(f"{pat}/114年中華民國政府行政機關辦公日曆表.csv", newline="") as f:
            reader = csv.reader(f)
            for row in reader:
                workday[row[0]] = row[2]
    except FileNotFoundError:
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


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5001)
