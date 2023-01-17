import csv
import os
import random
import requests
import time
import uuid

from datetime import datetime

uno = os.environ.get('UNO')
acc = os.environ.get('ACC')
password = os.environ.get('PASSWORD')

now = datetime.now().date().strftime('%Y%m%d')
absolutepath = os.path.abspath(__file__)

def get_new_token():
    """Get new token."""
    url = 'https://pro.104.com.tw/prohrm/api/login/token'
    data = {
        "uno": uno,
        "acc": acc,
        "pwd": password,
        "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzb3VyY2UiOiJhcHAtcHJvZCIsImNpZCI6MCwiaWF0IjoxNTUzNzUzMTQwfQ.ieJiJtNsseSO5fxNH1XTa6bqHZ0zUyoPVUYPNtOj4TM"
    }
    resp = requests.post(url, data=data)
    auth_token = resp.json()['data']['access']
    return auth_token

def punch(auth_token):
    """Punch with gps."""
    url = 'https://pro.104.com.tw/prohrm/api/app/card/gps'
    lat, lon = get_location()
    data = {
        "deviceId": gen_device_id(),
        "latitude": lat,
        "longitude": lon
    }
    headers = {'Authorization': 'Bearer ' + auth_token}
    resp = requests.post(url, data=data, headers=headers)
    if resp.status_code != 200:
        print(resp.text)
        punch(get_new_token())
    else:
        print(resp.text)

def gen_device_id():
    """Generate deveice id."""
    device_id = uuid.uuid5(uuid.NAMESPACE_DNS, acc)
    return str(device_id).upper()

def get_location():
    """Get random location."""
    # base_lat = 25.0581384
    # base_lon = 121.534577
    # max_lat = 0.00044*0.7
    # max_lon = 0.000495*0.7
    lat = random.uniform(25.0578304,25.0584464)
    lon = random.uniform(121.5342305,121.5349235)
    return lat, lon

def get_workday():
    """Get workday."""
    pat = os.path.dirname(absolutepath)
    workday = {}
    with open(f'{pat}/112年中華民國政府行政機關辦公日曆表.csv', newline='', encoding='big5') as f:
        reader = csv.reader(f)
        for row in reader:
            workday[row[0]] = row[2]
    return workday

def main():
    workday = get_workday()
    if workday[now] == '0':
        time.sleep(random.randint(1,5))
        punch(get_new_token())

if __name__ == "__main__":
    main()
