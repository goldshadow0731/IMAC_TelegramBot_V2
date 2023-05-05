# -*- coding: utf8 -*-
import configparser
import datetime
import os
import requests
import json
import time

from logger import get_logger


# Load config data from config.ini file
config = configparser.ConfigParser()
config.read(f"{os.path.dirname(os.path.abspath(__file__))}/config.ini")


# Pubilc variable
logger = get_logger(__file__)
# Timezone
tz = datetime.timezone(datetime.timedelta(hours=8))


# Public variable
last_report_day = 0
send_report = False
backend_url = f'{config["BACKEND"]["SERVER_PROTOCOL"]}://{config["BACKEND"]["SERVER_IP"]}:{config["BACKEND"]["SERVER_PORT"]}'


while True:
    date_time = datetime.datetime.now(tz)

    if date_time.hour == config["BACKEND"].getint("REPORT_TIME") and send_report is False:
        try:
            response = requests.get(f"{backend_url}/daily-report").json()
            logger.info(f"/daily-report {json.dumps(response)}")
        except Exception as e:
            logger.warning(f"/daily-report {e}")
        try:
            response = requests.get(f"{backend_url}/service-list").json()
            logger.info(f"/service-list {json.dumps(response)}")
        except Exception as e:
            logger.warning(f"/service-list {e}")
        # try:
        #     response = requests.get(f"{backend_url}/service-check").json()
        #     logger.info(f"/service-check {json.dumps(response)}")
        # except Exception as e:
        #     logger.warning(f"/service-check {e}")
        try:
            response = requests.get(f"{backend_url}/rotation-user").json()
            logger.info(f"/rotation-user {json.dumps(response)}")
        except Exception as e:
            logger.warning(f"/rotation-user {e}")
        # try:
        #     response = requests.get(
        #         "https://yunyun-telegram-bot.herokuapp.com/dailyReport").json()
        #     logger.info(f"yunyun/dailyReport {json.dumps(response)}")
        # except Exception as e:
        #     logger.warning(f"yunyun/dailyReport {e}")

        send_report = True

    if date_time.day != last_report_day:
        last_report_day = date_time.day
        send_report = False
        logger.info(f"RotationDay {last_report_day}")

    time.sleep(60)
