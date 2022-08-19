import csv
import os
import random
import requests
import time

from datetime import datetime

deviceid = os.environ.get('DEVICEID')
uno = os.environ.get('UNO')
acc = os.environ.get('ACC')
password = os.environ.get('PASSWORD')
token = os.environ.get('TOKEN')
# XXX: test different account for token

now = datetime.now().date().strftime('%Y%m%d')
absolutepath = os.path.abspath(__file__)

def get_new_token():
    """Get new token."""
    url = 'https://pro.104.com.tw/prohrm/api/login/token'
    data = {
        "uno": uno,
        "acc": acc,
        "pwd": password,
        "token": token
    }
    resp = requests.post(url, data=data)
    auth_token = resp.json()['data']['access']
    return auth_token

def punch(auth_token):
    """Punch with gps."""
    url = 'https://pro.104.com.tw/prohrm/api/app/card/gps'
    lat, lon = get_location()
    data = {
        "deviceId": deviceid,
        "latitude": lat,
        "longitude": lon
    }
    header = {'Authorization': 'Bearer ' + auth_token}
    resp = requests.post(url, data=data, headers=header)
    if resp.status_code != 200:
        print(resp.text)
        punch(get_new_token())
    else:
        print(resp.text)

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
    with open(f'{pat}/111年中華民國政府行政機關辦公日曆表.csv', newline='', encoding='big5') as f:
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
