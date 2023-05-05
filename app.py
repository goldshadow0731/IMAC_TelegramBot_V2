# -*- coding: utf8 -*-
import configparser
import datetime
import json
import logging
import os
import requests

from flask import Flask, request
from flask_restx import Api, Namespace, Resource, fields
from telegram import Bot, Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import Dispatcher, Filters, CommandHandler, MessageHandler, CallbackQueryHandler, CallbackContext
from pymongo import MongoClient
from werkzeug.utils import secure_filename


# Load data from config.ini file
config = configparser.ConfigParser()
config.read('config.ini')


# Pubilc variable
with open("./resource/device.json", encoding="UTF-8") as fp:
    all_device = json.load(fp)
    # 懶人遙控器 Emoji 定義
    keyboard_emoji_list = all_device["keyboard_emoji_list"]
    # 懶人遙控器鍵盤定義
    keyboard_list = all_device["keyboard_list"]
    # 設定機房資訊定義
    element_list = all_device["element_list"]
    element_json_list = all_device["element_json_list"]
    element_unit_list = all_device["element_unit_list"]
    # ET7044 設備定義
    et7044_device_name_list = all_device["et7044_device_name_list"]
    et7044_device_sw_list = all_device["et7044_device_sw_list"]
# Timezone
tz_delta = datetime.timedelta(hours=8)
tz = datetime.timezone(tz_delta)
split_line = "----------------------------------"
alert_minutes = config["BACKEND"].getint("ALERT_MINUTE")


# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)


# Initial Flask app
app = Flask(__name__)
app.config.update({
    "SWAGGER_UI_DOC_EXPANSION": 'list'
})
api = Api(app, version='2.0.0', title='IMAC_Telegram Cloud APIs', doc='/api/doc')
api_ns = Namespace("apis", "Cloud service", path="/")
api.add_namespace(api_ns)


# Initial bot by Telegram access token telegram
bot = Bot(token=config['TELEGRAM']['ACCESS_TOKEN'])


# LineBot Sync
linebot_server = f"{config['LINE']['SERVER_PROTOCOL']}://{config['LINE']['SERVER']}"


# Setup user & group id for reply specify message
group_id = config['TELEGRAM'].getint('GROUP_ID')
devUser_id = config['TELEGRAM'].getint('DEV_USER_ID')
camera_power_owner = config['DEVICE'].getint('CAMERA_POWER_OWNER')
dl303_owner = config['DEVICE'].getint('DL303_OWNER')
et7044_owner = config['DEVICE'].getint('ET7044_OWNER')
ups_owner = config['DEVICE'].getint('UPS_OWNER')
air_condiction_owner = config['DEVICE'].getint('AIR_CONDICTION_OWNER')
water_tank_owner = config['DEVICE'].getint('WATER_TANK_OWNER')


# Setup Mongodb info
mongodb = MongoClient(
    f'{config["MONGODB"]["SERVER_PROTOCOL"]}://{config["MONGODB"]["USER"]}:{config["MONGODB"]["PASSWORD"]}@{config["MONGODB"]["SERVER"]}')[config["MONGODB"]["DATABASE"]]
dbDl303TC = mongodb["dl303/tc"]
dbDl303RH = mongodb["dl303/rh"]
dbDl303CO2 = mongodb["dl303/co2"]
dbDl303DC = mongodb["dl303/dc"]
dbEt7044 = mongodb["et7044"]
dbUps = mongodb["ups"]
dbAirCondiction = mongodb["air_condiction"]
dbAirCondictionCurrent = mongodb["air_condiction_current"]
dbPowerBox = mongodb["power_box"]
dbDailyReport = mongodb["dailyReport"]
dbServiceCheck = mongodb["serviceCheck"]
dbServiceList = mongodb["serviceList"]
dbRotationUser = mongodb["rotationUser"]
dbDeviceCount = mongodb['deviceCount']
dbWaterTank = mongodb['waterTank']
dbCameraPower = mongodb['cameraPower']


""" ========== Public function ========== """
# collect the dl303 data (temperature/humidity/co2/dew-point) in mLab db.
def get_dl303(info):
    # info: tc, rh, co2, dc, temp/humi, all
    brokenTime = datetime.datetime.now(tz) - datetime.timedelta(minutes=alert_minutes)
    failList = list()
    data = "*[DL303 設備狀態回報]*" if info == "all" else "*[DL303 工業監測器]*"
    if info in ["tc", "temp/humi", "all"]:
        tc_data = dbDl303TC.find_one()
        tc = f"{tc_data['tc']:>5.1f}" if tc_data else None
        data = "\n".join([
            data,
            f"`即時環境溫度: {tc} 度`"
        ])
        if tc_data is None or tc_data['date'].replace(tzinfo=datetime.timezone.utc).astimezone(tz) < brokenTime:
            failList.append('tc')
    if info in ["rh", "temp/humi", "all"]:
        rh_data = dbDl303RH.find_one()
        rh = f"{rh_data['rh']:>5.1f}" if rh_data else None
        data = "\n".join([
            data,
            f"`即時環境濕度: {rh} %`"
        ])
        if rh_data is None or rh_data["date"].replace(tzinfo=datetime.timezone.utc).astimezone(tz) < brokenTime:
            failList.append('rh')
    if info in ["co2", "all"]:
        co2_data = dbDl303CO2.find_one()
        co2 = f"{co2_data['co2']:>5.0f}" if co2_data else None
        data = "\n".join([
            data,
            f"`二氧化碳濃度: {co2} ppm`"
        ])
        if co2_data is None or co2_data["date"].replace(tzinfo=datetime.timezone.utc).astimezone(tz) < brokenTime:
            failList.append('co2')
    if info in ["dc", "all"]:
        dc_data = dbDl303DC.find_one()
        dc = f"{dc_data['dc']:>5.1f}" if dc_data else None
        data = "\n".join([
            data,
            f"`環境露點溫度: {dc} 度`"
        ])
        if dc_data is None or dc_data["date"].replace(tzinfo=datetime.timezone.utc).astimezone(tz) < brokenTime:
            failList.append('dc')
    if failList:
        data = "\n".join([
            data,
            split_line,
            f"*[設備資料超時!]*\t[維護人員](tg://user?id={dl303_owner})",
            f"*異常模組:* _{json.dumps(failList)}_",
        ])
    return data


# collect the et-7044 status in mLab.
def get_et7044(info):
    # all, 進風風扇, 加濕器, 排風風扇
    brokenTime = datetime.datetime.now(tz) - datetime.timedelta(minutes=alert_minutes)
    et7044_data = dbEt7044.find_one()
    if info == "all":
        data = "*[ET7044 設備狀態回報]*"
        for name, sw in zip(et7044_device_name_list, et7044_device_sw_list):
            if et7044_data is None:
                sw_n_status = "未知"
            else:
                sw_n_status = "開啟" if et7044_data[sw] else "關閉"
            data = "\n".join([
                data,
                f"`{name} 狀態:\t{sw_n_status}`"
            ])
    else:
        data = f"*[{info} 設備狀態回報]*"
        if et7044_data is None:
            sw_n_status = "未知"
        else:
            sw_n_status = "開啟" if et7044_data[et7044_device_sw_list[
                et7044_device_name_list.index(info)]] else "關閉"
        data = "\n".join([
            data,
            f"`{info} 狀態:\t{sw_n_status}`"
        ])

    if et7044_data is None or et7044_data['date'].replace(tzinfo=datetime.timezone.utc).astimezone(tz) < brokenTime:
        data = "\n".join([
            data,
            split_line,
            f"*[設備資料超時!]*[維護人員](tg://user?id={et7044_owner})"
        ])
    return data


# collect the UPS (status/input/output/battery/temperature) status in mLab.
def get_ups(device_id, info):
    # device_id: a, b
    # info: all, temp, current, input, output, battery
    brokenTime = datetime.datetime.now(tz) - datetime.timedelta(minutes=alert_minutes)
    data = f"*[不斷電系統狀態回報-UPS_{device_id.upper()}]*" if info == "all" else f"*[UPS_{device_id.upper()}]*"
    ups_data = dbUps.find_one({"sequence": device_id})
    if info not in ['temp', 'current']:
        data = "\n".join([
            data,
            f"`UPS 狀態: {ups_data['output']['mode'] if ups_data else '未知'}`"
        ])
    if info in ['temp', 'all']:
        data = "\n".join([
            data,
            f"`機箱內部溫度: {int(ups_data['temp']) if ups_data else 'None'} 度`"
        ])
    if info not in ['temp', 'current']:
        data = "\n".join([
            data,
            split_line
        ])
    if info in ["input", "all"]:
        input_freq = f"{ups_data['input']['freq']:>5.1f}" if ups_data else 'None'
        input_volt = f"{ups_data['input']['volt']:>5.1f}" if ups_data else 'None'
        data = "\n".join([
            data,
            "[[輸入狀態]]",
            f"`頻率: {input_freq} HZ`",
            f"`電壓: {input_volt} V`"
        ])
    if info in ["output", "all"]:
        output_freq = f"{ups_data['output']['freq']:>5.1f}" if ups_data else 'None'
        output_volt = f"{ups_data['output']['volt']:>5.1f}" if ups_data else 'None'
        data = "\n".join([
            data,
            "[[輸出狀態]]",
            f"`頻率: {output_freq} HZ`",
            f"`電壓: {output_volt} V`"
        ])
    if info in ["output", "current", "all"]:
        output_amp = f"{ups_data['output']['amp']:>5.2f}" if ups_data else 'None'
        data = "\n".join([
            data,
            f"`電流: {output_amp} A`"
        ])
    if info in ["output", "all"]:
        output_watt = f"{ups_data['output']['watt']:>5.3f}" if ups_data else 'None'
        output_percent = f"{ups_data['output']['percent']:>2d}" if ups_data else 'None'
        data = "\n".join([
            data,
            f"`瓦數: {output_watt} kw`",
            f"`負載比例: {output_percent} %`"
        ])
    if info in ["battery", "all"]:
        battery_status = f"{ups_data['battery']['status']['status']}" if ups_data else '未知'
        battery_chargeMode = f"{ups_data['battery']['status']['chargeMode'].split('(')[1].split(')')[0]}" if ups_data else '未知'
        battery_volt = f"{ups_data['battery']['status']['volt']:>5.1f}" if ups_data else 'None'
        battery_remainPercent = f"{ups_data['battery']['status']['remainPercent']:>3d}" if ups_data else 'None'
        battery_health = f"{ups_data['battery']['status']['health']}" if ups_data else '未知'
        battery_lastChange = f"{ups_data['battery']['lastChange']['year']}/{ups_data['battery']['lastChange']['month']}/{ups_data['battery']['lastChange']['day']}" if ups_data else '未知'
        battery_nextChange = f"{ups_data['battery']['nextChange']['year']}/{ups_data['battery']['nextChange']['month']}/{ups_data['battery']['nextChange']['day']}" if ups_data else '未知'
        data = "\n".join([
            data,
            "[[電池狀態]]",
            f"`電池狀態: {battery_status}`",
            f"`充電模式: {battery_chargeMode}`",
            f"`電池電壓: {battery_volt} V`",
            f"`剩餘比例: {battery_remainPercent} %`",
            f"`電池健康: {battery_health}`",
            f"`上次更換時間: {battery_lastChange}`",
            f"`下次更換時間: {battery_nextChange}`"
        ])
    if ups_data is None or ups_data['date'].replace(tzinfo=datetime.timezone.utc).astimezone(tz) < brokenTime:
        data = "\n".join([
            data,
            split_line,
            f"*[設備資料超時!]*\t[維護人員](tg://user?id={ups_owner})"
        ])
    return data


# collect the Air-Condiction (current/temperature/humidity) status in mLab.
def get_air_condiction(device_id, info):
    # device_id: a, b
    # info: all, temp, humi, temp/humi, current
    brokenTime = datetime.datetime.now(tz) - datetime.timedelta(minutes=alert_minutes)
    failList = list()
    data = f"*[冷氣監控狀態回報-冷氣_{device_id.upper()}]*" if info == "all" else f"*[冷氣_{device_id.upper()}]*"
    envoriment_data = dbAirCondiction.find_one({"sequence": device_id})
    current_data = dbAirCondictionCurrent.find_one({"sequence": device_id})

    if info in ["temp", "temp/humi", "all"]:
        temp = f"{envoriment_data['temp']:>5.1f}" if envoriment_data else 'None'
        data = "\n".join([
            data,
            f"`出風口溫度: {temp} 度`"
        ])
    if info in ["humi", "temp/humi", "all"]:
        humi = f"{envoriment_data['humi']:>5.1f}" if envoriment_data else 'None'
        data = "\n".join([
            data,
            f"`出風口濕度: {humi} %`"
        ])
    if info in ["temp", "humi", "temp/humi", "all"] and (envoriment_data is None or envoriment_data['date'].replace(tzinfo=datetime.timezone.utc).astimezone(tz) < brokenTime):
        failList.append('temp/humi')
    if info in ["current", "all"]:
        current = f"{current_data['current']:>5.1f}" if current_data else 'None'
        data = "\n".join([
            data,
            f"`冷氣耗電流: {current} A`"
        ])
        if current_data['date'].replace(tzinfo=datetime.timezone.utc).astimezone(tz) < brokenTime:
            failList.append('current')
    if failList:
        data = "\n".join([
            data,
            split_line,
            f"*[設備資料超時!]*\t[維護人員](tg://user?id={air_condiction_owner})",
            f"*異常模組:* _{json.dumps(failList)}_"
        ])
    return data


# collect the water tank current in mLab
def get_water_tank(info):
    # info: all, current
    brokenTime = datetime.datetime.now(tz) - datetime.timedelta(minutes=alert_minutes)
    water_tank_data = dbWaterTank.find_one()
    water_tank_current = f"{round(water_tank_data['current'], 2):>6.2f}" if water_tank_data else "None"
    data = "\n".join([
        "*[冷氣水塔 設備狀態回報]*" if info == "all" else "*[冷氣水塔]*",
        f"`電流: {water_tank_current} A`"
    ])
    if water_tank_data is None or water_tank_data['date'].replace(tzinfo=datetime.timezone.utc).astimezone(tz) < brokenTime:
        data = "\n".join([
            data,
            split_line,
            f"*[設備資料超時!]*\t[維護人員](tg://user?id={water_tank_owner})"
        ])
    return data


# collect the AI CV Image recognition
def get_camera_power():
    brokenTime = datetime.datetime.now(tz) - datetime.timedelta(days=2)
    camera_power = dbCameraPower.find_one()
    today_power = f"{round(camera_power['today']['power'], 2):>10.2f}" if camera_power else "None"
    today_date = f"{camera_power['today']['date'].replace(tzinfo=datetime.timezone.utc).astimezone(tz).strftime('%Y-%m-%d %H:%M:%S'):>20s}" if camera_power else '未知'
    yesterday_power = f"{round(camera_power['yesterday']['power'], 2):>10.2f}" if camera_power else "None"
    yesterday_date = f"{camera_power['yesterday']['date'].replace(tzinfo=datetime.timezone.utc).astimezone(tz).strftime('%Y-%m-%d %H:%M:%S'):>20s}" if camera_power else '未知'
    used_power = f"{round(camera_power['today']['power'] - camera_power['yesterday']['power'], 2):>10.2f}" if camera_power else "None"
    data = "\n".join([
        "*[AI 辨識電錶 狀態回報]*",
        "[[今日辨識結果]]",
        f"`辨識度數: {today_power} 度`",
        f"`更新時間: {today_date}`",
        "[[上次辨識結果]]",
        f"`辨識度數: {yesterday_power} 度`",
        f"`更新時間: {yesterday_date}`",
        "[[消耗度數統計]]",
        f"`統計度數: {used_power} 度`"
    ])
    if camera_power is None or camera_power['today']['date'].replace(tzinfo=datetime.timezone.utc).astimezone(tz) < brokenTime:
        data = "\n".join([
            data,
            split_line,
            f"*[設備資料超時!]*\t[維護人員](tg://user?id={water_tank_owner})"
        ])
    return data


# collect the daily report data (weather / power usage) in mLab db.
def get_daily_report():
    brokenTime = datetime.datetime.now(tz).date()
    dailyReport = dbDailyReport.find_one()
    cameraPower = dbCameraPower.find_one()
    data = "\n".join([
        "*[機房監控每日通報]*",
        "[[今日天氣預測]]"
    ])
    if dailyReport is None or dailyReport["date"].replace(tzinfo=datetime.timezone.utc).astimezone(tz).date() != brokenTime:
        data = "\n".join([
            data,
            "`資料快取失敗`",
            "[[昨日功耗統計]]",
            "`資料快取失敗`"
        ])
    else:
        if "weather" in dailyReport["error"]:
            data = "\n".join([
                data,
                "`快取失敗`"
            ])
        else:
            data = "\n".join(filter(None, [
                data,
                f'`天氣狀態:\t{dailyReport["Wx"]}`',
                f'`舒適指數:\t{dailyReport["CI"]}`',
                f'`降雨機率:{dailyReport["PoP12h"]:>5d} %`',
                None,  # '`陣風風向:\t{dailyReport["WD"]}`'
                None,  # f'`平均風速:{dailyReport["WS"]:>5d} 公尺/秒`'
                f'`室外溫度:{dailyReport["T"]:>5.1f} 度`',
                f'`體感溫度:{dailyReport["AT"]:>5.1f} 度`',
                f'`室外濕度:{dailyReport["RH"]:>5d} %`'
            ]))
        data = "\n".join([
            data,
            "[[昨日設備功耗統計]]"
        ])
        if "power" in dailyReport["error"]:
            data = "\n".join([
                data,
                "`快取失敗`"
            ])
        else:
            air_condiction_a_watt = f'{dailyReport["air_condiction_a"]:>6.2f} 度 ({dailyReport["air_condiction_a"]/dailyReport["total"]:4.1%})' if "air_condiction_a" not in dailyReport["error"] else "0.0 度"
            air_condiction_b_watt = f'{dailyReport["air_condiction_b"]:>6.2f} 度 ({dailyReport["air_condiction_b"]/dailyReport["total"]:4.1%})' if "air_condiction_b" not in dailyReport["error"] else "0.0 度"
            ups_a_watt = f'{dailyReport["ups_a"]:>6.2f} 度 ({dailyReport["ups_a"]/dailyReport["total"]:4.1%})' if "ups_a" not in dailyReport["error"] else "0.0 度"
            ups_b_watt = f'{dailyReport["ups_b"]:>6.2f} 度 ({dailyReport["ups_b"]/dailyReport["total"]:4.1%})' if "ups_b" not in dailyReport["error"] else "0.0 度"
            water_tank_watt = f'{dailyReport["water_tank"]:>6.2f} 度 ({dailyReport["water_tank"]/dailyReport["total"]:4.1%})' if "water_tank" not in dailyReport["error"] else "0.0 度"
            data = "\n".join([
                data,
                f"`冷氣_A 功耗: {air_condiction_a_watt}`",
                f"`冷氣_B 功耗: {air_condiction_b_watt}`",
                f"`UPS_A 功耗: {ups_a_watt}`",
                f"`UPS_B 功耗: {ups_b_watt}`",
                f"`冷氣水塔 功耗: {water_tank_watt}`",
                f'`機房功耗加總: {dailyReport["total"]:>6.2f} 度`',
                "[[昨日電錶功耗統計]]",
                f"`電錶功耗統計: {cameraPower['today']['power']-cameraPower['yesterday']['power']:>6.2f} 度`",
                "`電錶統計區間: `",
                f"`{cameraPower['yesterday']['date'].replace(tzinfo=datetime.timezone.utc).astimezone(tz).date()} ~ {cameraPower['today']['date'].replace(tzinfo=datetime.timezone.utc).astimezone(tz).date()}`"
            ])

    if len(dailyReport["error"]) != 0:
        data = "\n".join([
            data,
            split_line,
            f"*[每日通報資料異常!]*\t[維護人員](tg://user?id={devUser_id})",
            f'*異常模組:* _{json.dumps(dailyReport["error"]).replace("_", "-")}_'
        ])
    return data


# collect the smart-data-center number of the device
def get_device_count():
    deviceCount = dbDeviceCount.find_one()
    if deviceCount == None:
        data = {x: 0 for x in element_json_list}
        data.update({
            "setting": False,
            "settingObject": ""
        })
        dbDeviceCount.insert_one(data)
    data = ["*[機房設備資訊]*"]
    data.extend([f'`{name}:\t{deviceCount[count]}\t{unit}`' for name, count, unit in zip(
        element_list, element_json_list, element_unit_list)])
    data = "\n".join(data)
    return data


# collect the day of matainer in mLab db.
def get_rotation_user():
    rotationUser = dbRotationUser.find_one()
    todayWeekDay = datetime.datetime.now(tz).weekday()
    tomorrowWeekDay = (datetime.datetime.now(
        tz) + datetime.timedelta(days=1)).weekday()
    data = "*[本日輪值人員公告]*"
    if rotationUser is None:
        data = "\n".join([
            data,
            "`資料庫快取失敗`"
        ])
    else:
        today_user = ", ".join(
            [x for x in rotationUser["rotation"][todayWeekDay]["user"]])
        tomorrow_user = ", ".join(
            [x for x in rotationUser["rotation"][tomorrowWeekDay]["user"]])
        data = "\n".join([
            data,
            "[[今日輪值人員]]",
            today_user,
            "[[今日交接人員]]",
            tomorrow_user
        ])
    return data


# collect the smart-data-center website url & login info in mLab db.
def get_service_list():
    brokenTime = datetime.datetime.now(tz).date()
    serviceList = dbServiceList.find_one()
    if serviceList is None or serviceList["date"].replace(tzinfo=datetime.timezone.utc).astimezone(tz).date() < brokenTime:
        data = "`資料庫快取失敗`"
    else:
        data = serviceList if "輪播 Dashboard" not in serviceList["error"] else "`輪播 DashBoard 資料快取失敗`"
    return data


# collect the smart-data-center website dashboard service status in mLab db.
def get_service_check():
    brokenTime = datetime.datetime.now(tz) - datetime.timedelta(minutes=alert_minutes)
    serviceStatus = dbServiceCheck.find_one()
    data = "*[機房交接服務檢測]*"
    if serviceStatus is None or serviceStatus["date"].replace(tzinfo=datetime.timezone.utc).astimezone(tz) < brokenTime:
        data = "\n".join([
            data,
            "`資料快取失敗`",
            split_line,
            "*[交接服務檢測資料異常!]*",
            f'*異常服務:* _{serviceStatus["error"]}_'
        ])
    elif "輪播 Dashboard" in serviceStatus["error"]:
        data = "\n".join([
            data,
            "`輪播 DashBoard 資料快取失敗`",
            split_line,
            "*[交接服務檢測資料異常!]*"
        ])
    else:
        for service in serviceStatus["service"]:
            data = "\n".join([
                data,
                f'[[{service["name"]}]]',
                f'`服務輪播: {service["enabled"]}`',
                f'`服務狀態: {service["status"]}`'
            ])
        if serviceStatus["error"]:
            data = "\n".join(filter(None, [
                data,
                split_line,
                "*[交接服務檢測資料異常!]*",
                f'*異常服務:* _{serviceStatus["error"]}_'
            ]))
    return data


""" ========== Public route ========== """
# test api function, can test the ("message", "photo", "audio", "gif") reply to develope user.
@api_ns.route('/test/<mode>')
class Test(Resource):
    def get(self, mode):
        "測試 API"
        user_id = request.values.get("id", devUser_id)
        if mode == 'message':
            bot.send_message(chat_id=user_id, text="telegramBot 服務測試訊息")
        elif mode == 'localPhoto':
            with open('./resource/test.png', 'rb') as fp:
                bot.send_photo(chat_id=user_id, photo=fp)
        elif mode == 'localAudio':
            with open('./resource/test.mp3', 'rb') as fp:
                bot.send_audio(chat_id=user_id, audio=fp)
        elif mode == 'localGif':
            with open('./resource/test.gif', 'rb') as fp:
                bot.send_animation(chat_id=user_id, animation=fp)
        elif mode == 'onlinePhoto':
            bot.send_photo(chat_id=user_id,
                           photo='https://i.imgur.com/ajMBl1b.jpg')
        elif mode == 'onlineAudio':
            bot.send_audio(chat_id=user_id,
                           audio='http://s80.youtaker.com/other/2015/10-6/mp31614001370a913212b795478095673a25cebc651a080.mp3')
        elif mode == 'onlineGif':
            bot.send_animation(chat_id=user_id,
                               animation='http://d21p91le50s4xn.cloudfront.net/wp-content/uploads/2015/08/giphy.gif')
        return "OK"


# LineBot 暫時廢棄
@api.deprecated
@api_ns.route('/linebot')
class LintBot(Resource):
    linebot_input_payload = api_ns.model("LineBot 輸入", {
        "disk": fields.Float(required=True, example=67.5),
        "pc": fields.Integer(required=True, example=65),
        "ram": fields.Integer(required=True, example=448),
        "sdnSwitch": fields.Integer(required=True, example=5),
        "server": fields.Integer(required=True, example=22),
        "switch": fields.Integer(required=True, example=24),
        "vcpu": fields.Integer(required=True, example=1012)
    })

    linebot_output_payload = api_ns.model("LineBot 輸出", {
        "linebot": fields.String(example="data_success")
    })

    @api_ns.expect(linebot_input_payload)
    @api_ns.marshal_with(linebot_output_payload)
    @api_ns.response(400, "Error Data", linebot_output_payload)
    def post(self):
        "更新機房資訊"
        try:
            payload = api_ns.payload
            data = {
                "storage": payload["disk"],
                "pc": payload["pc"],
                "ram": payload["ram"],
                "sdn": payload["sdnSwitch"],
                "server": payload["server"],
                "switch": payload["switch"],
                "cpu": payload["vcpu"]
            }
            dbDeviceCount.update_one({}, {'$set': data})
        except:
            return {"linebot": "data_fail"}, 400
        else:
            return {"linebot": "data_success"}


# rotationUser api function, send smart-data-center maintainer in this day.
@api_ns.route('/rotation-user')
class RotationUser(Resource):
    rotation_user_output_payload = api_ns.model("RotationUser 輸出", {
        "rotationUser": fields.String(example="data_ok")
    })

    @api_ns.marshal_with(rotation_user_output_payload)
    def get(self):
        "取得輪值人員"
        respText = get_rotation_user()
        bot.send_message(
            chat_id=group_id,
            text=respText,
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove()
        )
        return {"rotationUser": "data_ok"}


# service check api function, check the smart-data-center website dashboard service.
@api_ns.route('/service-check')
class ServiceCheck(Resource):
    service_check_output_payload = api_ns.model("ServiceCheck 輸出", {
        "serviceCheck": fields.String("data_ok")
    })

    @api_ns.marshal_with(service_check_output_payload)
    def get(self):
        "機房服務檢測"
        respText = get_service_check()
        bot.send_message(
            chat_id=group_id,
            text=respText,
            parse_mode="Markdown"
        )
        return {"serviceCheck": "data_ok"}


# daily report api function, will notice the daily report to specify group or user.
@api_ns.route('/daily-report')
class DailyReport(Resource):
    daily_report_output_payload = api_ns.model("DailyReport 輸出", {
        "dailyReport": fields.String(example="data_ok")
    })

    @api_ns.marshal_with(daily_report_output_payload)
    def get(self):
        "每日通報"
        respText = get_daily_report()
        bot.send_message(
            chat_id=group_id,
            text=respText,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("功能列表", callback_data="daily")]
            ]),
            parse_mode="Markdown"
        )
        return {"dailyReport": "data_ok"}


# alert notification api, auto notice the notifaiction to telegram specify user / group.
@api_ns.route('/alert/<model>')
class Alert(Resource):
    alert_input_payload = api_ns.model("Alert 輸入", {
        "message": fields.String(default="test")
    })

    @api_ns.expect(alert_input_payload)
    def post(self, model):
        "發送警告"
        try:
            if model == 'librenms':
                model = "LibreNMS"
            elif model == "icinga":
                model = "IcingaWeb2"
            elif model == "ups":
                model = "UPS"
            else:
                raise ValueError("api_model_fail")
            if api_ns.payload.get("message") is None:
                raise ValueError("data_fail")
            respText = "\n".join([
                f"[{model} 監控服務異常告警]",
                api_ns.payload["message"]
            ])
            bot.send_message(chat_id=group_id, text=respText)
        except Exception as e:
            error_class = e.__class__.__name__  # 錯誤類型
            detail = e.args[0]  # 詳細內容
            print(f"/alert [{error_class}] {detail}")
            return {"/alert": detail}, 400
        else:
            return {"alert": "data_ok"}


# Stream of People
@api_ns.route('/induced-abortion-recognization')
class People(Resource):
    # people_input_payload = api_ns.model("人流 輸入", {
    #     "message": fields.String(default="test"),
    #     "file": fields.F
    # })

    # @api_ns.expect(people_input_payload)
    def post(self):
        "發送人流警告"
        try:
            # Message
            print(api_ns.payload)
            # Image
            f = request.files['image']
            filename = secure_filename(f.filename)
            os.makedirs("./Image", exist_ok=True)
            f.save(os.path.join("./Image", filename))
            bot.send_photo(chat_id=devUser_id, photo=request.files['image'])
            bot.send_message(chat_id=devUser_id, text=api_ns.payload["message"])
        except Exception as e:
            error_class = e.__class__.__name__  # 錯誤類型
            detail = e.args[0]  # 詳細內容
            print(f"/people [{error_class}] {detail}")
            return {"/people": detail}, 400
        else:
            return {"people": "data_ok"}


# telegram bot data reciver.
@app.route('/hook', methods=['POST'])
def webhook_handler():
    """Set route /hook with POST method will trigger this method."""
    # telegram
    update = Update.de_json(request.get_json(force=True), bot)
    # Update dispatcher process that handler to process this message
    dispatcher.process_update(update)
    return "OK"


""" ========== Telegram function ========== """
# Command "/satrt" callback.
def add_bot(update: Update, context: CallbackContext):
    respText = "\n".join([
        "*[歡迎加入 NUTC-IMAC 機房監控機器人]*",
        "[[快速使用]]\t`請輸入 \"輔助鍵盤\"。`",
        "[[進階指令]]\t`請輸入 \"/command\"。`"
    ])
    context.bot.send_message(
        chat_id=update.message.chat_id, text=respText, parse_mode="Markdown")


# Command "/command" callback.
def list_command(update: Update, context: CallbackContext):
    respText = "\n".join([
        "*[輔助指令列表]*",
        "`命名規則: A (靠牆) / B (靠窗)`",
        "[[快速鍵盤]]",
        "`1. 輔助鍵盤`",
        "`2. 關閉鍵盤`",
        "[[每日通報]]",
        "`1. 每日通報`",
        "[[機房輪值]]",
        "`1. 機房輪值`",
        "[[機房服務檢視]]",
        "`1. 服務列表`",
        "`2. 服務狀態、服務檢測`",
        "[[所有環控設備]]",
        "`1. 環控設備`",
        "[[AI 智慧辨識 電錶]]",
        "`1. 電錶、電錶度數、電錶狀態、智慧電錶`",
        "`2. 電表、電表度數、電表狀態、智慧電表`",
        "[[DL303 工業監測器]]",
        "`1. DL303`",
        "`1. 溫度、溫濕度、濕度、CO2、露點溫度`",
        "[[ET7044 工業控制器]]",
        "`1. ET7044`",
        "`2. 遠端控制`",
        "`3. 進風扇狀態、加濕器狀態、排風扇狀態`",
        "[[冷氣 空調主機 (A/B)]]",
        "`1. 冷氣、冷氣狀態、水塔、水塔狀態`",
        "`2. 電流、溫度、濕度、溫濕度`",
        "`3. 冷氣_A、冷氣_a、冷氣A、冷氣a`",
        "`4. 冷氣a狀態、冷氣A狀態`",
        "[[機房 瞬間功耗電流]]",
        "`1. 電流`",
        "[[UPS 不斷電系統 (A/B)]]",
        "`1. 溫度、電流`",
        "`2. UPS、Ups、ups`",
        "`3. 電源狀態、UPS狀態、ups狀態`",
        "`4. UPSA、upsa、UpsA、Upsa`",
        "`5. UPS_A、UPSA狀態、upsa狀態`"
    ])
    context.bot.send_message(
        chat_id=update.message.chat_id, text=respText, parse_mode="Markdown")


# recive the all of the user/group message handler.
def reply_handler(update: Update, context: CallbackContext):
    """Reply message."""
    text = update.message.text
    in_group_or_is_dev_user = update.message.chat_id == devUser_id or update.message.chat_id == group_id

    try:
        device_count = dbDeviceCount.find_one()
        setting_mode = device_count['setting']
        settingObject = device_count['settingObject']
    except:
        setting_mode = False

    # 機房資訊設定
    if setting_mode == True and in_group_or_is_dev_user:
        if text in element_list[:-1]:
            dbDeviceCount.update_one({}, {'$set': {'settingObject': text}})
            respText = f"`請輸入{text}數量~`"
            context.bot.send_message(
                chat_id=update.message.chat_id,
                text=respText, parse_mode="Markdown")
        elif text in element_list[-1]:
            respText = "\n".join([
                get_device_count(),
                split_line,
                "`您已離開機房資訊設定模式~`"
            ])
            dbDeviceCount.update_one({}, {'$set': {'setting': False}})
            context.bot.send_message(
                chat_id=update.message.chat_id, text=respText,
                parse_mode="Markdown",
                reply_markup=ReplyKeyboardRemove(remove_keyboard=True))
        elif settingObject != "":
            try:
                if settingObject == "Storage (TB)":
                    float(text)
                else:
                    int(text)
                respText = "\n".join([
                    "*[請確認機房設備數量]*",
                    f"`設定項目:\t{settingObject}`",
                    f"`設定數量:\t{text}\t{element_unit_list[element_list.index(settingObject)]}`"
                ])
                context.bot.send_message(
                    chat_id=update.message.chat_id, text=respText,
                    parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton(
                                '正確', callback_data=f"setting:{settingObject}_{text}"),
                            InlineKeyboardButton(
                                '錯誤', callback_data=f"setting:{settingObject}")
                        ]
                    ]))
            except:
                respText = f"{settingObject}\t數值輸入錯誤～, 請重新輸入！"
                context.bot.send_message(
                    chat_id=update.message.chat_id, text=respText, parse_mode="Markdown")
        else:
            respText = "\n".join([
                "`機房資訊設定中, 若需查詢其他服務, 請先關閉設定模式。`",
                "`關閉設定模式，請輸入 \"離開設定狀態\"`"
            ])
            context.bot.send_message(
                chat_id=update.message.chat_id, text=respText, parse_mode="Markdown")
    # 開啟 懶人遙控器鍵盤
    elif text == '輔助鍵盤':
        respText = '輔助鍵盤功能已開啟～'
        with open('./resource/keyboard.jpg', 'rb') as fp:
            context.bot.send_photo(
                chat_id=update.message.chat_id, photo=fp, caption=respText,
                reply_markup=ReplyKeyboardMarkup([
                    [f"{emoji}{str_}" for emoji, str_ in zip(
                        keyboard_emoji_list[0:4], keyboard_list[0:4])],
                    [f"{emoji}{str_}" for emoji, str_ in zip(
                        keyboard_emoji_list[4:8], keyboard_list[4:8])],
                    [f"{emoji}\n{str_}" for emoji, str_ in zip(
                        keyboard_emoji_list[8:12], keyboard_list[8:12])],
                    [f"{emoji}\n{str_}" for emoji, str_ in zip(
                        keyboard_emoji_list[12:16], keyboard_list[12:16])]
                ], resize_keyboard=True),
                parse_mode="Markdown"
            )
    # 關閉 懶人遙控器鍵盤
    elif text == '關閉鍵盤':
        respText = '輔助鍵盤功能已關閉～'
        context.bot.send_message(
            chat_id=update.message.chat_id, text=respText, parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(remove_keyboard=True))
    # 溫度
    elif text in ["溫度", "\U0001F321溫度"]:
        respText = '請選擇 監測節點～'
        context.bot.send_message(
            chat_id=update.message.chat_id, text=respText, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    'DL303 工業監測器', callback_data="temp:DL303")],
                [InlineKeyboardButton('冷氣_A 出風口', callback_data="temp:冷氣_A")],
                [InlineKeyboardButton('冷氣_B 出風口', callback_data="temp:冷氣_B")],
                [InlineKeyboardButton(
                    'UPS_A 機箱內部', callback_data="temp:UPS_A")],
                [InlineKeyboardButton(
                    'UPS_B 機箱內部', callback_data="temp:UPS_B")],
                [InlineKeyboardButton('全部列出', callback_data="temp:全部列出")]
            ])
        )
    # 濕度
    elif text in ["濕度", "\U0001F4A7濕度"]:
        respText = '請選擇 監測節點～'
        context.bot.send_message(
            chat_id=update.message.chat_id, text=respText, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    'DL303 工業監測器', callback_data="humi:DL303")],
                [InlineKeyboardButton('冷氣_A 出風口', callback_data="humi:冷氣_A")],
                [InlineKeyboardButton('冷氣_B 出風口', callback_data="humi:冷氣_B")],
                [InlineKeyboardButton('全部列出', callback_data="humi:全部列出")]
            ])
        )
    # CO2
    elif text in ["CO2", "\U00002601CO2"]:
        respText = get_dl303("co2")
        context.bot.send_message(
            chat_id=update.message.chat_id, text=respText, parse_mode="Markdown")
    # Power Meter + UPS 電流 回覆
    elif text in ["電流", "\U000026A1電流"]:
        respText = '請選擇 監測節點～'
        context.bot.send_message(
            chat_id=update.message.chat_id, text=respText, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    '冷氣空調主機_A', callback_data="current:冷氣_A")],
                [InlineKeyboardButton(
                    '冷氣空調主機_B', callback_data="current:冷氣_B")],
                [InlineKeyboardButton(
                    '冷氣空調-冷卻水塔', callback_data="current:水塔")],
                [InlineKeyboardButton(
                    'UPS不斷電系統_A', callback_data="current:UPS_A")],
                [InlineKeyboardButton(
                    'UPS不斷電系統_B', callback_data="current:UPS_B")],
                [InlineKeyboardButton('全部列出', callback_data="current:全部列出")]
            ])
        )
    # DL303 + 環境監測 回復
    elif text in ['DL303', 'dl303']:
        respText = get_dl303("all")
        context.bot.send_message(
            chat_id=update.message.chat_id, text=respText, parse_mode="Markdown")
    # ET7044 狀態 回復
    elif text in ['ET7044', 'et7044']:
        respText = get_et7044("all")
        context.bot.send_message(
            chat_id=update.message.chat_id, text=respText, parse_mode="Markdown")
    # ET7044 進風扇狀態 回復
    elif text in ['進風扇狀態', '進風風扇狀態']:
        respText = get_et7044("進風風扇")
        context.bot.send_message(
            chat_id=update.message.chat_id, text=respText, parse_mode="Markdown")
    # ET7044 加濕器狀態 回復
    elif text == '加濕器狀態':
        respText = get_et7044("加濕器")
        context.bot.send_message(
            chat_id=update.message.chat_id, text=respText, parse_mode="Markdown")
    # ET7044 排風扇狀態 回復
    elif text in ['排風扇狀態', '排風風扇狀態']:
        respText = get_et7044("排風風扇")
        context.bot.send_message(
            chat_id=update.message.chat_id, text=respText, parse_mode="Markdown")
    # UPS 功能 回覆
    elif text in ['UPS狀態', 'ups狀態', 'UPS', "\U0001F50BUPS", 'ups', "電源狀態", 'Ups']:
        respText = '請選擇 UPS～'
        context.bot.send_message(
            chat_id=update.message.chat_id, text=respText, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('UPS_A', callback_data="UPS:UPS_A")],
                [InlineKeyboardButton('UPS_B', callback_data="UPS:UPS_B")],
                [InlineKeyboardButton('全部列出', callback_data="UPS:全部列出")]
            ])
        )
    # UPS A 功能 回覆
    elif text in ['UPS_A', 'UPSA狀態', 'upsa狀態', 'UPSA', 'upsa', 'UpsA', 'Upsa']:
        respText = get_ups("a", "all")
        context.bot.send_message(
            chat_id=update.message.chat_id, text=respText, parse_mode="Markdown")
    # UPS B 功能 回覆
    elif text in ['UPS_B', 'UPSB狀態', 'upsb狀態', 'UPSB', 'upsb', 'UpsB', 'Upsb']:
        respText = get_ups("b", "all")
        context.bot.send_message(
            chat_id=update.message.chat_id, text=respText, parse_mode="Markdown")
    # 冷氣 功能 回覆
    elif text in ['冷氣狀態', '冷氣', '\U00002744冷氣']:
        respText = '請選擇 冷氣～'
        context.bot.send_message(
            chat_id=update.message.chat_id, text=respText, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton('冷氣_A', callback_data="冷氣:冷氣_A")],
                [InlineKeyboardButton('冷氣_B', callback_data="冷氣:冷氣_B")],
                [InlineKeyboardButton('冷氣-水塔', callback_data="冷氣:水塔")],
                [InlineKeyboardButton('全部列出', callback_data="冷氣:全部列出")]
            ])
        )
    # 冷氣 A 功能 回覆
    elif text in ['冷氣_A', '冷氣_a', '冷氣A狀態', '冷氣a狀態', '冷氣a', '冷氣A']:
        respText = get_air_condiction("a", "all")
        context.bot.send_message(
            chat_id=update.message.chat_id, text=respText, parse_mode="Markdown")
    # 冷氣 B 功能 回覆
    elif text in ['冷氣_B', '冷氣_b', '冷氣B狀態', '冷氣b狀態', '冷氣b', '冷氣B']:
        respText = get_air_condiction("b", "all")
        context.bot.send_message(
            chat_id=update.message.chat_id, text=respText, parse_mode="Markdown")
    # 冷氣水塔 回覆
    elif text in ["水塔", "水塔狀態"]:
        respText = get_water_tank("all")
        context.bot.send_message(
            chat_id=update.message.chat_id, text=respText, parse_mode="Markdown")
    # 所有設備
    elif text in ["環控設備", "\U0001F39B\n環控設備"]:
        respText = '請選擇 監測設備～'
        context.bot.send_message(
            chat_id=update.message.chat_id, text=respText, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    'DL303 工業監測器', callback_data="device:DL303")],
                [InlineKeyboardButton(
                    'ET7044 工業控制器', callback_data="device:ET7044")],
                [InlineKeyboardButton(
                    '冷氣空調主機_A', callback_data="device:冷氣_A")],
                [InlineKeyboardButton(
                    '冷氣空調主機_B', callback_data="device:冷氣_B")],
                [InlineKeyboardButton(
                    '冷氣空調-冷卻水塔', callback_data="device:水塔")],
                [InlineKeyboardButton(
                    'UPS不斷電系統_A', callback_data="device:UPS_B")],
                [InlineKeyboardButton(
                    'UPS不斷電系統_B', callback_data="device:UPS_B")],
                [InlineKeyboardButton(
                    'AI 辨識智慧電表', callback_data="device:電錶")],
                [InlineKeyboardButton(
                    '全部列出', callback_data="device:全部列出")]
            ])
        )
    # 遠端控制 私密指令處理, 僅限制目前機房管理群 & 開發者使用
    elif text in ["遠端控制", "\U0001F579\n遠端控制", "機房輪值", "\U0001F46C\n機房輪值", "輪值", "服務列表", "\U0001F4CB\n服務列表", "設定機房", "\U00002699\n設定機房"] and in_group_or_is_dev_user:
        # 遠端控制
        if text in ['遠端控制', "\U0001F579\n遠端控制"]:
            respText = '請選擇所需控制設備～'
            context.bot.send_message(
                chat_id=update.message.chat_id, text=respText, parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton('進風風扇', callback_data="控制:進風風扇")],
                    [InlineKeyboardButton('加濕器', callback_data="控制:加濕器")],
                    [InlineKeyboardButton('排風風扇', callback_data="控制:排風風扇")]
                ])
            )
        # 機房 Dashboard 服務列表
        elif text in ['服務列表', "\U0001F4CB\n服務列表"]:
            respText = "*[機房服務列表]*"
            try:
                serviceList = get_service_list()["service"]
                for unit_service in serviceList:
                    if (unit_service.get("user") != None and unit_service.get("pass") != None):
                        respText = "\n".join([
                            respText,
                            f'[[{unit_service["name"]}]]',
                            f'帳號:{unit_service["user"]}',
                            f'密碼:{unit_service["pass"]}'
                        ])
                context.bot.send_message(
                    chat_id=update.message.chat_id, text=respText,
                    parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton(
                                unit_service["name"],
                                callback_data=f'service{unit_service["name"]}',
                                url=unit_service["url"]
                            )
                        ] for unit_service in serviceList
                    ])
                )
            except:
                respText = "\n".join([
                    respText,
                    get_service_list()
                ])
                context.bot.send_message(
                    chat_id=update.message.chat_id, text=respText, parse_mode="Markdown")
        # 機房輪值
        elif text in ["機房輪值", "\U0001F46C\n機房輪值"]:
            respText = get_rotation_user()
            context.bot.send_message(
                chat_id=update.message.chat_id, text=respText, parse_mode="Markdown")
        # 設定機房資訊
        elif text in ["設定機房", "\U00002699\n設定機房"]:
            respText = "\n".join([
                get_device_count(),
                "----------------------------------",
                '`機房資訊 設定模式開啟～`'
            ])
            dbDeviceCount.update_one({}, {'$set': {'setting': True}})
            with open('./resource/keyboard.jpg', 'rb') as fp:
                context.bot.send_photo(
                    chat_id=update.message.chat_id, photo=fp, caption=respText,
                    reply_markup=ReplyKeyboardMarkup([
                        [str_ for str_ in element_list[0:3]],
                        [str_ for str_ in element_list[3:6]],
                        [str_ for str_ in element_list[6:9]]
                    ], resize_keyboard=True),
                    parse_mode="Markdown"
                )
    # 遠端控制
    elif text in ["遠端控制", "\U0001F579\n遠端控制", "機房輪值", "\U0001F46C\n機房輪值", "\U0001F4CB\n服務列表", "設定機房", "\U00002699\n設定機房"]:
        respText = '您的權限不足～, 請在機器人群組內使用。'
        context.bot.send_message(
            chat_id=update.message.chat_id, text=respText, parse_mode="Markdown")
    # 每日通報
    elif text in ['每日通報', '\U0001F4C6\n每日通報']:
        respText = get_daily_report()
        context.bot.send_message(
            chat_id=update.message.chat_id, text=respText, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("功能列表", callback_data="daily")]
            ])
        )
    # 機房 Dashboard 服務狀態檢測
    elif text in ['服務狀態', '\U0001F468\U0000200D\U0001F4BB\n服務狀態', '服務檢測']:
        respText = get_service_check()
        context.bot.send_message(
            chat_id=update.message.chat_id, text=respText, parse_mode="Markdown")
    # 機房資訊
    elif text in ["機房資訊", "\U0001F5A5\n機房資訊"]:
        respText = get_device_count()
        context.bot.send_message(
            chat_id=update.message.chat_id, text=respText, parse_mode="Markdown")
    # 溫濕度
    elif text == '溫濕度':
        respText = "\n".join([
            get_dl303("temp/humi"),
            get_air_condiction("a", "temp/humi"),
            get_air_condiction("b", "temp/humi"),
            get_ups("a", "temp"),
            get_ups("b", "temp")
        ])
        context.bot.send_message(
            chat_id=update.message.chat_id, text=respText, parse_mode="Markdown")
    # 露點溫度
    elif text == '露點溫度':
        respText = get_dl303("dc")
        context.bot.send_message(
            chat_id=update.message.chat_id, text=respText, parse_mode="Markdown")
    # AI 辨識點錶度數
    elif text in ["電表", "電錶", "電表度數", "電錶度數", "電表狀態", "電錶狀態", "智慧電表", "智慧電錶"]:
        respText = get_camera_power()
        context.bot.send_message(
            chat_id=update.message.chat_id, text=respText, parse_mode="Markdown")


# 溫度 按鈕鍵盤 callback
def temp_select(update: Update, context: CallbackContext):
    device = update.callback_query.data.split(':')[1]
    respText = "\n".join(filter(lambda str_: str_ is not None, [
        get_dl303("tc") if device in ["DL303", "全部列出"] else None,
        "",
        get_air_condiction("a", "temp") if device in [
            "冷氣_A", "全部列出"] else None,
        "",
        get_air_condiction("b", "temp") if device in [
            "冷氣_B", "全部列出"] else None,
        "",
        get_ups("a", "temp") if device in ["UPS_A", "全部列出"] else None,
        "",
        get_ups("b", "temp") if device in ["UPS_B", "全部列出"] else None
    ]))
    context.bot.send_message(
        chat_id=update.callback_query.message.chat_id, text=respText, parse_mode="Markdown")


# 濕度 按鈕鍵盤 callback
def humi_select(update: Update, context: CallbackContext):
    device = update.callback_query.data.split(':')[1]
    respText = "\n".join(filter(lambda str_: str_ is not None, [
        get_dl303("rh") if device in ["DL303", "全部列出"] else None,
        "",
        get_air_condiction("a", "humi") if device in [
            "冷氣_A", "全部列出"] else None,
        "",
        get_air_condiction("b", "humi") if device in [
            "冷氣_B", "全部列出"] else None
    ]))
    context.bot.send_message(
        chat_id=update.callback_query.message.chat_id, text=respText, parse_mode="Markdown")


# 電流 按鈕鍵盤 callback
def current_select(update: Update, context: CallbackContext):
    device = update.callback_query.data.split(':')[1]
    respText = "\n".join(filter(lambda str_: str_ is not None, [
        get_air_condiction("a", "current") if device in [
            "冷氣_A", "全部列出"] else None,
        "",
        get_air_condiction("b", "current") if device in [
            "冷氣_B", "全部列出"] else None,
        "",
        get_water_tank("current") if device in ["水塔", "全部列出"] else None,
        "",
        get_ups("a", "current") if device in ["UPS_A", "全部列出"] else None,
        "",
        get_ups("b", "current") if device in ["UPS_B", "全部列出"] else None
    ]))
    context.bot.send_message(
        chat_id=update.callback_query.message.chat_id, text=respText, parse_mode="Markdown")


# ET-7044 (選設備) 按鈕鍵盤 callback
def et7044_select(update: Update, context: CallbackContext):
    device = update.callback_query.data.split(':')[1]
    data = get_et7044(device).split("\n")[1:]  # 更改 Title
    data.insert(0, f"*[{device} 狀態控制]*")  # 更新 Title
    respText = "\n".join(data)
    if split_line in respText:
        context.bot.send_message(
            chat_id=update.callback_query.message.chat_id, text=respText, parse_mode="Markdown")
    else:
        context.bot.send_message(
            chat_id=update.callback_query.message.chat_id, text=respText, parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "開啟", callback_data=f"開關:{device}_開啟"),
                    InlineKeyboardButton("關閉", callback_data=f"開關:{device}_關閉")
                ]
            ])
        )


# ET-7044 (開關) 按鈕鍵盤 callback
def et7044_control(update: Update, context: CallbackContext):
    msg = update.callback_query.data.split(':')[1]
    device = msg.split('_')[0]
    status = msg.split('_')[1]
    respText = "\n".join([
        f"*[{device} 狀態更新]*",
        f"`{device} 狀態: \t{status}`"
    ])
    chargeStatus = True if status == "開啟" else False
    dbEt7044.update_one({}, {'$set': {
        et7044_device_sw_list[et7044_device_name_list.index(device)]: chargeStatus}})
    context.bot.send_message(
        chat_id=update.callback_query.message.chat_id, text=respText, parse_mode="Markdown")


# UPS 按鈕鍵盤 callback
def ups_select(update: Update, context: CallbackContext):
    device = update.callback_query.data.split(':')[1]
    respText = "\n".join(filter(lambda str_: str_ is not None, [
        get_ups("a", "all") if device in ["UPS_A", "全部列出"] else None,
        "",
        get_ups("b", "all") if device in ["UPS_B", "全部列出"] else None
    ]))
    context.bot.send_message(
        chat_id=update.callback_query.message.chat_id, text=respText,
        parse_mode="Markdown")


# 冷氣 按鈕鍵盤 callback
def air_condiction_select(update: Update, context: CallbackContext):
    device = update.callback_query.data.split(':')[1]
    respText = "\n".join(filter(lambda str_: str_ is not None, [
        get_air_condiction("a", "all") if device in [
            "冷氣_A", "全部列出"] else None,
        "",
        get_air_condiction("b", "all") if device in [
            "冷氣_B", "全部列出"] else None,
        "",
        get_water_tank("all") if device in ["水塔", "全部列出"] else None
    ]))
    context.bot.send_message(
        chat_id=update.callback_query.message.chat_id, text=respText,
        parse_mode="Markdown")


# 環控裝置 按鈕鍵盤 callback
def device_select(update: Update, context: CallbackContext):
    device = update.callback_query.data.split(':')[1]
    respText = "\n".join(filter(lambda str_: str_ is not None, [
        get_dl303("all") if device in ["DL303", "全部列出"] else None,
        "",
        get_et7044("all") if device in ["ET7044", "全部列出"] else None,
        "",
        get_air_condiction("a", "all") if device in ["冷氣_A", "全部列出"] else None,
        "",
        get_air_condiction("b", "all") if device in ["冷氣_B", "全部列出"] else None,
        "",
        get_water_tank("all") if device in ["水塔", "全部列出"] else None,
        "",
        get_ups("a", "all") if device in ["UPS_A", "全部列出"] else None,
        "",
        get_ups("b", "all") if device in ["UPS_B", "全部列出"] else None,
        "",
        get_camera_power() if device in ["電錶", "全部列出"] else None
    ]))
    context.bot.send_message(
        chat_id=update.callback_query.message.chat_id, text=respText, parse_mode="Markdown")


# 每日通報 按鈕鍵盤 callback
def daily_select(update: Update, context: CallbackContext):
    respText = '輔助鍵盤功能已開啟～'
    with open('./resource/keyboard.jpg', 'rb') as fp:
        context.bot.send_photo(
            chat_id=update.callback_query.message.chat_id, photo=fp, caption=respText,
            reply_markup=ReplyKeyboardMarkup([
                [f"{emoji}{str_}" for emoji, str_ in zip(
                    keyboard_emoji_list[0:4], keyboard_list[0:4])],
                [f"{emoji}{str_}" for emoji, str_ in zip(
                    keyboard_emoji_list[4:8], keyboard_list[4:8])],
                [f"{emoji}\n{str_}" for emoji, str_ in zip(
                    keyboard_emoji_list[8:12], keyboard_list[8:12])],
                [f"{emoji}\n{str_}" for emoji, str_ in zip(
                    keyboard_emoji_list[12:16], keyboard_list[12:16])]
            ], resize_keyboard=True),
            parse_mode="Markdown"
        )


#  機房資訊確認 按鈕鍵盤 callback
def device_setting(update: Update, context: CallbackContext):
    payload = update.callback_query.data.split(':')[1].split('_')
    device = payload[0]
    if len(payload) == 1:
        dbDeviceCount.update_one({}, {'$set': {'settingObject': ""}})
        respText = f"{device}\t資料已重設"
    else:
        if device == "Storage (TB)":
            count = float(payload[1])
        else:
            count = int(payload[1])
        dbDeviceCount.update_one({}, {'$set': {
            'settingObject': "", element_json_list[element_list.index(device)]: count}})
        # linbot sync device count
        if device == "cpu":
            device = "vcpu"
        elif device == "sdn":
            device = "sdnSwitch"
        elif device == "storage":
            device = "disk"
        requests.get(f"{linebot_server}/telegram/{device}/{str(count)}")  # ???
        respText = f"{device}\t設定成功"
    context.bot.send_message(
        chat_id=update.callback_query.message.chat_id, text=respText,
        parse_mode="Markdown", reply_markup=None)


""" ========== Telegram setting ========== """
# New a dispatcher for bot
dispatcher = Dispatcher(bot, None)


# Add handler for handling message, there are many kinds of message. For this handler, it particular handle text message.
dispatcher.add_handler(CommandHandler('start', add_bot))
dispatcher.add_handler(CommandHandler('command', list_command))
dispatcher.add_handler(MessageHandler((Filters.text and ~Filters.command),
                                      reply_handler))
dispatcher.add_handler(CallbackQueryHandler(temp_select,
                                            pattern=r'temp'))
dispatcher.add_handler(CallbackQueryHandler(humi_select,
                                            pattern=r'humi'))
dispatcher.add_handler(CallbackQueryHandler(current_select,
                                            pattern=r'current'))
dispatcher.add_handler(CallbackQueryHandler(et7044_select,
                                            pattern=r'控制'))
dispatcher.add_handler(CallbackQueryHandler(et7044_control,
                                            pattern=r'開關'))
dispatcher.add_handler(CallbackQueryHandler(ups_select,
                                            pattern=r'UPS'))
dispatcher.add_handler(CallbackQueryHandler(air_condiction_select,
                                            pattern=r'冷氣'))
dispatcher.add_handler(CallbackQueryHandler(device_select,
                                            pattern=r'device'))
dispatcher.add_handler(CallbackQueryHandler(daily_select,
                                            pattern=r'daily'))
dispatcher.add_handler(CallbackQueryHandler(device_setting,
                                            pattern=r'setting'))


# Init
get_device_count()


if __name__ == "__main__":
    # Running server
    app.run(host="0.0.0.0", port=8443, debug=True)
