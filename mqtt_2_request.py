# -*- coding: utf8 -*-
import configparser
import json
import os
from requests import request, Response
from typing import Text

from paho.mqtt import client as MQTT_Client

from logger import get_logger


# Load config data from config.ini file
config = configparser.ConfigParser()
config.read(f"{os.path.dirname(os.path.abspath(__file__))}/config.ini")


# Log
logger = get_logger(__file__)
record_path = f"{os.path.dirname(os.path.abspath(__file__))}/MQTT_message"
os.makedirs(record_path, exist_ok=True)


# Init connect
client = MQTT_Client.Client()


# Send request to flask backend
def request_to_backend(url_path: Text, method: Text = "POST", *args, **kwargs) -> Response:
    try:
        url = f'{config["BACKEND"]["SERVER_PROTOCOL"]}://{config["BACKEND"]["SERVER_IP"]}:{config["BACKEND"]["SERVER_PORT"]}/{url_path.lstrip("/")}'
        response = request(method.upper(), url, *args, **kwargs)
        if method.upper() == "POST":
            logger.info(
                f'{method.upper()} {url_path.lstrip("/")} {json.dumps(response.json())}')
        else:
            logger.info(f'{method.upper()} {url_path.lstrip("/")}')
    except Exception as e:
        logger.warning(f'{method.upper()} {url_path.lstrip("/")} {e}')
    else:
        return response


# Set the connect action
@client.connect_callback()
def on_connect(client, userdata, flags, reason_code):
    print("Connected with result code "+str(reason_code))

    # DL-303
    # client.subscribe("DL303/#")
    client.subscribe("DL303/TC")
    client.subscribe("DL303/RH")
    client.subscribe("DL303/DC")
    # client.subscribe('DL303/CO')
    client.subscribe("DL303/CO2")

    # ET7044
    client.subscribe("ET7044/DOstatus")

    # UPS
    # client.subscribe("UPS_Monitor")
    client.subscribe("UPS/A/Monitor")
    client.subscribe("UPS/B/Monitor")

    # Air conditioner and water tank current
    client.subscribe("waterTank")
    client.subscribe("current")

    # Air conditioner Temperature and Humidity
    # client.subscribe("air_condiction/#")
    client.subscribe("air_condiction/A")
    client.subscribe("air_condiction/B")


# Set the receive message action
@client.message_callback()
def on_message(client, userdata, msg):
    data = msg.payload.decode('utf-8')

    if msg.topic in ["DL303/TC", "DL303/RH", "DL303/DC", "DL303/CO2"]:
        request_to_backend(msg.topic.lower(),
                           json={msg.topic.lower().split("/")[1]: float(data)})
    elif msg.topic == "ET7044/DOstatus":  # Not Sure  # Notice
        # Signal path: device -> here -> mLab
        # Control path: mLab -> here -> device
        change_status = False
        device_et7044_status = {f"sw{i}": v for i, v in enumerate(
            json.loads(data))}  # device status
        mLab_et7044_status = request_to_backend("et7044",
                                                method="GET").json()  # mLab status
        for k in device_et7044_status.keys():
            if mLab_et7044_status.get(k, False) != device_et7044_status[k]:
                change_status = True  # mLab want to change et7044 status
        if change_status:
            client.publish("ET7044/write",
                           str([mLab_et7044_status[f"sw{i}"] for i in range(len(mLab_et7044_status))]).lower())
        else:
            request_to_backend("et7044", json=device_et7044_status)
    elif msg.topic in ["UPS/A/Monitor", "UPS/B/Monitor"]:
        request_to_backend(msg.topic.rstrip("/Monitor").lower(),
                           json=json.loads(data))
    elif msg.topic == "waterTank":
        request_to_backend("water-tank",
                           json=json.loads(data))
    elif msg.topic == "current":
        data = json.loads(data)
        request_to_backend("power-box",
                           json={"temp": data["Temperature"], "humi": data["Humidity"]})
        request_to_backend("air-conditioner/current/a",
                           json={"current": data['current_a']})
        request_to_backend("air-conditioner/current/b",
                           json={"current": data['current_b']})
    elif msg.topic in ["air_condiction/A", "air_condiction/B"]:
        request_to_backend(f"air-conditioner/environment/{msg.topic.lower().split('/')[1]}",
                           json=json.loads(data))

    # with open(f'{record_path}/{msg.topic.replace("/", "_")}.json', "w", encoding='utf-8') as fp:
    #     json.dump(json.loads(data), fp, ensure_ascii=True, indent=4)


# Set connect info
client.connect(config["MQTT"]["BROKER_IP"],
               config["MQTT"].getint("BROKER_PORT"))


# Start connect
client.loop_forever()
