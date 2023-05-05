# -*- coding: utf8 -*-
import configparser
import json
import os

from paho.mqtt import client as MQTT_Client


# Load config data from config.ini file
config = configparser.ConfigParser()
config.read(f"{os.path.dirname(os.path.abspath(__file__))}/config.ini")


# Public variable
countA = False
countB = False
sendData = dict()


# Init connect
client = MQTT_Client.Client()


# Set the connect action
@client.connect_callback()
def on_connect(client, userdata, flags, reason_code):
    print(f"Connected with result code {reason_code}")

    # client.subscribe("UPS_Monitor")
    client.subscribe("UPS/A/Monitor")
    client.subscribe("UPS/B/Monitor")


# Set the receive message action
@client.message_callback()
def on_message(client, userdata, msg):
    global countA, countB, sendData

    payload = json.loads(msg.payload.decode('UTF-8'))

    if msg.topic == "UPS/A/Monitor":
        countA = True
        device = "A"
        connect = "/dev/ttyUSB0 (牆壁)"
    else:  # msg.topic == "UPS/B/Monitor"
        countB = True
        device = "B"
        connect = "/dev/ttyUSB1 (窗戶)"

    sendData.update({
        f"connect_{device}": connect,
        f"ups_Life_{device}": "onLine(在線)",
        f"input_{device}": {
            f"inputLine_{device}": payload["input"]["line"],
            f"inputFreq_{device}": payload["input"]["freq"],
            f"inputVolt_{device}": payload["input"]["volt"]
        },
        f"output_{device}": {
            f"systemMode_{device}": payload["output"]["mode"].split(" ")[0],
            f"outputLine_{device}": payload["output"]["line"],
            f"outputFreq_{device}": payload["output"]["freq"],
            f"outputVolt_{device}": payload["output"]["volt"],
            f"outputAmp_{device}": payload["output"]["amp"],
            f"outputPercent_{device}": payload["output"]["percent"],
            f"outputWatt_{device}": payload["output"]["watt"]
        },
        f"battery_{device}": {
            "status": {
                f"batteryHealth_{device}": payload["battery"]["status"]["health"],
                f"batteryStatus_{device}": payload["battery"]["status"]["status"],
                f"batteryCharge_Mode_{device}": payload["battery"]["status"]["chargeMode"],
                f"batteryVolt_{device}": payload["battery"]["status"]["volt"],
                f"batteryTemp_{device}": payload["temp"],
                f"batteryRemain_Percent_{device}": payload["battery"]["status"]["remainPercent"],
                f"batteryRemain_Min_{device}": "None By Charging (充電中)",
                f"batteryRemain_Sec_{device}": "None By Charging (充電中)"
            },
            "lastChange": {
                f"lastBattery_Year_{device}": payload["battery"]["lastChange"]["year"],
                f"lastBattery_Mon_{device}": payload["battery"]["lastChange"]["month"],
                f"lastBattery_Day_{device}": payload["battery"]["lastChange"]["day"]
            },
            "nextChange": {
                f"nextBattery_Year_{device}": payload["battery"]["nextChange"]["year"],
                f"nextBattery_Mon_{device}": payload["battery"]["nextChange"]["month"],
                f"nextBattery_Day_{device}": payload["battery"]["nextChange"]["day"]
            }
        }
    })

    if countA and countB:
        client.publish("UPS_Monitor", json.dumps(sendData))
        countA = False
        countB = False
        sendData = dict()


# Set connect info
client.connect(config["MQTT"]["BROKER_IP"],
               config["MQTT"].getint("BROKER_PORT"))


# Start connect
client.loop_forever()
