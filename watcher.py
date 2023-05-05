# -*- coding: utf8 -*-
import configparser
import copy
import datetime
import json
import os
import time

from telegram import Bot
from paho.mqtt import client as MQTT_Client

from logger import get_logger


# Load environment variable
config = configparser.ConfigParser()
config.read(f"{os.path.dirname(os.path.abspath(__file__))}/config.ini")
MAINTAINER_USER_ID = config["TELEGRAM"].getint("DEV_USER_ID")


# Init connect
logger = get_logger(__file__)
bot = Bot(config["TELEGRAM"]["ACCESS_TOKEN"])
client = MQTT_Client.Client()


# Public variable
tz = datetime.timezone(datetime.timedelta(hours=8))
run = True
watch_topic_list = [
    "DL303/TC",
    "DL303/RH",
    "DL303/DC",
    "DL303/CO",
    "DL303/CO2",
    "UPS_Monitor",
    "UPS/A/Monitor",
    "UPS/B/Monitor",
    "current",
    "waterTank",
    "air_condiction/A",
    "air_condiction/B"
]
watch_topic = {k: {"alert": True, "count": 0} for k in watch_topic_list}
last_alert_topic = list()
exception_topic = ["ET7044/write"]
others_topic = dict()
last_others_topic = dict()


# Set the connect action
@client.connect_callback()
def on_connect(client, userdata, flags_dict, reason):
    print(f"========== {'Start Connect':^15s} ==========")

    client.subscribe('#')


# On disconnect action
@client.disconnect_callback()
def on_disconnect(self, userdata, result_code):
    print(f"========== {'End Connect':^15s} ==========")


# Set the receive message action
@client.message_callback()
def on_message(self, userdata, msg):
    data = msg.payload.decode('utf-8')
    if msg.topic in watch_topic_list and watch_topic[msg.topic]["alert"]:
        watch_topic[msg.topic]["alert"] = False
        watch_topic[msg.topic]["count"] -= 1
    elif msg.topic not in watch_topic_list and msg.topic not in exception_topic:
        others_topic.update(
            {msg.topic: {"datetime": datetime.datetime.now(tz), "payload": data}})


# Set connect info
client.connect(config["MQTT"]["BROKER_IP"],
               config["MQTT"].getint("BROKER_PORT"), 60)
while run:
    try:
        watch_topic = {
            k: {"alert": True, "count": v["count"] + 1} for k, v in watch_topic.items()}

        # Start connect
        client.loop_start()
        time.sleep(20)
        client.loop_stop()
    except KeyboardInterrupt:
        client.disconnect()
        run = False
    except Exception as e:
        print(e)
    else:
        # Send notice alert
        send_alert_notice_topic = {
            k: v["count"]//3 for k, v in watch_topic.items() if v["alert"] and v["count"] % 3 == 0}
        if send_alert_notice_topic:
            logger.warning(
                f"Alert topic: {json.dumps(send_alert_notice_topic)}")
            text = "\n" + "\n".join(
                [f"{k:<20s}\t{v}" for k, v in send_alert_notice_topic.items()])
            bot.send_message(chat_id=MAINTAINER_USER_ID,
                             text=f'Alert topic:{text}')

        # Send fixed topic
        send_fixed_topic = [
            k for k, v in watch_topic.items() if v["alert"] is False and v["count"] >= 3]
        if send_fixed_topic:
            logger.info(f"Fixed topic: {json.dumps(send_fixed_topic)}")
            text = "\n" + "\n".join(send_fixed_topic)
            bot.send_message(chat_id=MAINTAINER_USER_ID,
                             text=f'Fixed topic:{text}')

        # new other topic
        new_other_topic = list(set(others_topic.keys()) -
                               set(last_others_topic.keys()))
        if new_other_topic:
            logger.info(f"Other topic: {json.dumps(new_other_topic)}")
            text = "\n" + "\n".join(new_other_topic)
            bot.send_message(chat_id=MAINTAINER_USER_ID,
                             text=f'Other topic:{text}')

        # New alert topic
        alert_topic = [k for k, v in watch_topic.items() if v["alert"]]

        # New fixed topic
        fixed_topic = list(set(last_alert_topic) - set(alert_topic))
        for k in fixed_topic:
            watch_topic[k]["count"] = 0

        # expired other topic
        for k, v in others_topic.items():
            if v["datetime"] < datetime.datetime.now(tz) - datetime.timedelta(minutes=3):
                others_topic.pop(k)

        last_alert_topic = copy.deepcopy(alert_topic)
        last_others_topic = copy.deepcopy(others_topic)
