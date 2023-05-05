# -*- coding: utf8 -*-
import configparser
import datetime
import json
import os

from flask import Flask
from flask_restx import Api, Namespace, Resource, fields
import MySQLdb
from pymongo import MongoClient
import requests

from logger import get_logger

# Load config data from config.ini file
config = configparser.ConfigParser()
config.read(f"{os.path.dirname(os.path.abspath(__file__))}/config.ini")


# Pubilc variable
# Log
logger = get_logger(__file__)
# Timezone
tz_delta = datetime.timedelta(hours=8)
tz = datetime.timezone(tz_delta)


# Initial Flask app
app = Flask(__name__)
app.config.update({
    "SWAGGER_UI_DOC_EXPANSION": 'list'
})
api = Api(app, version='2.0.0', title='IMAC_Telegram APIs', doc='/api/doc')
api_ns = Namespace("apis", "MQTT and other service", path="/")
api.add_namespace(api_ns)


# Setup mLab Mongodb info
mongodb = MongoClient(
    f'{config["MONGODB"]["SERVER_PROTOCOL"]}://{config["MONGODB"]["USER"]}:{config["MONGODB"]["PASSWORD"]}@{config["MONGODB"]["SERVER"]}')[config["MONGODB"]["DATABASE"]]

# Cloud Server Setup
cloud_server = f'{config["TELEGRAM"]["SERVER_PROTOCOL"]}://{config["TELEGRAM"]["SERVER_URL"]}'


@api_ns.route("/dl303/<module>")
class DL303(Resource):
    dl303_input_payload = api_ns.model("DL-303 輸入", {
        "tc": fields.Float(default=25.5),
        "rh": fields.Float(default=50.5),
        "co2": fields.Float(default=400),
        "dc": fields.Float(default=25.0)
    })

    dl303_output_payload = api_ns.model("DL-303 輸出", {
        "dl303": fields.String()
    })

    @api_ns.expect(dl303_input_payload, validate=True)
    @api_ns.marshal_with(dl303_output_payload)
    @api_ns.response(400, "Error Data", dl303_output_payload)
    def post(self, module):
        "DL-303 溫溼度感測器"
        try:
            if module not in ["tc", "rh", "co2", "dc"]:
                raise TypeError("api_module_fail")
            data = api_ns.payload
            if data.get(module) is None:
                raise ValueError(f"{module}_data_info_fail")
            dl303_data = {
                module: data.get(module),
                "date": datetime.datetime.now(tz)
            }
            dbDl303 = mongodb[f"dl303/{module}"]
            dbDl303.update_one({}, {'$set': dl303_data}, upsert=True)
        except Exception as e:
            error_class = e.__class__.__name__  # 錯誤類型
            detail = e.args[0]  # 詳細內容
            logger.warning(f"dl303 [{error_class}] {detail}")
            return {"dl303": detail}, 400
        else:
            logger.info(f"dl303 {module}_data_ok")
            return {"dl303": f"{module}_data_ok"}


@api_ns.route("/et7044")
class ET7044(Resource):
    dbEt7044 = mongodb["et7044"]

    et7044_input_payload = api_ns.model("ET-7044 輸入", {
        "sw0": fields.Boolean(default=False),
        "sw1": fields.Boolean(default=False),
        "sw2": fields.Boolean(default=False),
        "sw3": fields.Boolean(default=False),
        "sw4": fields.Boolean(default=False),
        "sw5": fields.Boolean(default=False),
        "sw6": fields.Boolean(default=False),
        "sw7": fields.Boolean(default=False)
    })

    et7044_output_payload_2 = api_ns.model("ET-7044 輸出", {
        "et7044": fields.String()
    })

    @api_ns.marshal_with(et7044_input_payload)
    @api_ns.response(400, "Error Data", et7044_output_payload_2)
    def get(self):
        "取得 ET-7044 狀態"
        data = self.dbEt7044.find_one()
        et7044_status = {f"sw{i}": data[f"sw{i}"] for i in range(len(data)-2)} if data else {
            f"sw{i}": False for i in range(8)}
        logger.info(json.dumps(et7044_status))
        return et7044_status

    @api_ns.expect(et7044_input_payload, validate=True)
    @api_ns.marshal_with(et7044_output_payload_2)
    @api_ns.response(400, "Error Data", et7044_output_payload_2)
    def post(self):
        "更新 ET-7044 狀態"
        try:
            et7044_status = api_ns.payload
            for row_data in et7044_status.values():
                if row_data not in [True, False]:
                    raise ValueError("data_fail")
            # et7044_status
            et7044_status["date"] = datetime.datetime.now(tz)
            self.dbEt7044.update_one({}, {'$set': et7044_status}, upsert=True)
        except Exception as e:
            error_class = e.__class__.__name__  # 錯誤類型
            detail = e.args[0]  # 詳細內容
            logger.warning(f"et7044 [{error_class}] {detail}")
            return {"et7044": detail}, 400
        else:
            logger.info("et7044 data_ok")
            return {"et7044": "data_ok"}


@api_ns.route("/ups/<sequence>")
class UPS(Resource):
    dbUps = mongodb["ups"]

    keys = {
        "input": ["line", "freq", "volt"],
        "output": ["watt", "percent", "mode", "line", "amp", "freq", "volt"],
        "battery": {
            "status": ["status", "health", "volt", "remainPercent", "chargeMode"],
            "lastChange": ["year", "month", "day"],
            "nextChange": ["year", "month", "day"]
        },
        "temp": None
    }

    ups_input_field_payload = api_ns.model("UPS input", {
        "line": fields.Integer(example=1),
        "freq": fields.Float(example=60.0),
        "volt": fields.Float(example=220.0)
    })

    ups_output_field_payload = api_ns.model("UPS output", {
        "mode": fields.String(example="Normal (市電輸入)"),
        "line": fields.Integer(example=1),
        "volt": fields.Float(example=220.0),
        "amp": fields.Float(example=10.0),
        "freq": fields.Float(example=60.0),
        "watt": fields.Float(example=2.2),
        "percent": fields.Integer(example=30)
    })

    ups_battery_status_field_payload = api_ns.model("UPS battery status", {
        "status": fields.String(example="OK (良好)"),
        "health": fields.String(example="Good (良好)"),
        "volt": fields.Float(example=220.0),
        "remainPercent": fields.Integer(example=100),
        "chargeMode": fields.String(example="Boost charging (快速充電)")
    })

    ups_battery_lastChange_field_payload = api_ns.model("UPS battery lastChange", {
        "year": fields.Integer(example=2020),
        "month": fields.Integer(example=1),
        "day": fields.Integer(example=1)
    })

    ups_battery_nextChange_field_payload = api_ns.model("UPS battery nextChange", {
        "year": fields.Integer(example=2020),
        "month": fields.Integer(example=1),
        "day": fields.Integer(example=1)
    })

    ups_battery_field_payload = api_ns.model("UPS battery", {
        "status": fields.Nested(ups_battery_status_field_payload),
        "lastChange": fields.Nested(ups_battery_lastChange_field_payload),
        "nextChange": fields.Nested(ups_battery_nextChange_field_payload)
    })

    ups_input_payload = api_ns.model("UPS 輸入", {
        "temp": fields.Integer(example=25),
        "input": fields.Nested(ups_input_field_payload),
        "output": fields.Nested(ups_output_field_payload),
        "battery": fields.Nested(ups_battery_field_payload)
    })

    ups_output_payload = api_ns.model("UPS 輸出", {
        "ups": fields.String(example="data_ok")
    })

    @classmethod
    def check_lack_key(cls, data, key):
        lack_key = False
        for k, v in key.items():
            if data.get(k) is None:
                lack_key = True
            elif isinstance(v, dict):
                lack_key = cls.check_lack_key(data[k], v)
            elif isinstance(v, list):
                for sub_k in v:
                    if data[k].get(sub_k) is None:
                        lack_key = True
        return lack_key

    @api_ns.expect(ups_input_payload)
    @api_ns.marshal_with(ups_output_payload)
    @api_ns.response(400, "Error Data", ups_output_payload)
    def post(self, sequence):
        "UPS 不斷電系統"
        try:
            if sequence not in ["a", "b"]:
                raise TypeError("api_sequence_fail")
            data = api_ns.payload
            if self.check_lack_key(data, self.keys):
                raise ValueError("data_fail")
            data["date"] = datetime.datetime.now(tz)
            data["sequence"] = sequence
            self.dbUps.update_one({'sequence': sequence}, {
                '$set': data}, upsert=True)
        except Exception as e:
            error_class = e.__class__.__name__  # 錯誤類型
            detail = e.args[0]  # 詳細內容
            logger.warning(f"ups [{error_class}] {detail}")
            return {"ups": detail}, 400
        else:
            logger.info(f"ups data_ok")
            return {"ups": "data_ok"}


@api_ns.route("/water-tank")
class WaterTank(Resource):
    dbWaterTank = mongodb['waterTank']

    water_tank_input_payload = api_ns.model("WaterTank 輸入", {
        "current": fields.Float(example=5.0)
    })

    water_tank_output_payload = api_ns.model("WaterTank 輸出", {
        "water_tank": fields.String(example="data_ok")
    })

    @api_ns.expect(water_tank_input_payload)
    @api_ns.marshal_with(water_tank_output_payload)
    @api_ns.response(400, "Error Data", water_tank_output_payload)
    def post(self):
        "WaterTank 水塔電流"
        try:
            data = api_ns.payload
            if data.get("current") is None:
                raise ValueError("data_fail")
            data["date"] = datetime.datetime.now(tz)
            self.dbWaterTank.update_one({}, {'$set': data}, upsert=True)
        except Exception as e:
            error_class = e.__class__.__name__  # 錯誤類型
            detail = e.args[0]  # 詳細內容
            logger.warning(f"water_tank [{error_class}] {detail}")
            return {"water_tank": "data_fail"}, 400
        else:
            logger.info(f"water_tank data_ok")
            return {"water_tank": "data_ok"}


@api_ns.route("/power-box")
class PowerBox(Resource):
    dbPowerBox = mongodb["power_box"]

    power_box_input_payload = api_ns.model("PowerBox 輸入", {
        "temp": fields.Float(example=25.0),
        "humi": fields.Float(example=50.0)
    })

    power_box_output_payload = api_ns.model("PowerBox 輸出", {
        "power_box": fields.String(example="data_ok")
    })

    @api_ns.expect(power_box_input_payload)
    @api_ns.marshal_with(power_box_output_payload)
    @api_ns.response(400, "Error Data", power_box_output_payload)
    def post(self):
        "PowerBox 電箱溫溼度"
        try:
            data = api_ns.payload
            if data.get("humi") is None or data.get("humi") is None:
                raise ValueError("data_fail")
            data["date"] = datetime.datetime.now(tz)
            self.dbPowerBox.update_one({}, {'$set': data}, upsert=True)
        except Exception as e:
            error_class = e.__class__.__name__  # 錯誤類型
            detail = e.args[0]  # 詳細內容
            logger.warning(f"power_box [{error_class}] {detail}")
            return {"power_box": detail}, 400
        else:
            logger.info("power_box data_ok")
            return {"power_box": "data_ok"}


@api_ns.route("/air-conditioner/current/<sequence>")
class AirConditionerCurrent(Resource):
    dbAirCondictionCurrent = mongodb["air_condiction_current"]

    air_conditioner_current_input_payload = api_ns.model("AirConditionerCurrent 輸入", {
        "current": fields.Float(example=5.0)
    })

    air_conditioner_current_output_payload = api_ns.model("AirConditionerCurrent 輸出", {
        "air_conditioner - current": fields.String(example="data_ok")
    })

    @api_ns.expect(air_conditioner_current_input_payload)
    @api_ns.marshal_with(air_conditioner_current_output_payload)
    @api_ns.response(400, "Error Data", air_conditioner_current_output_payload)
    def post(self, sequence):
        "AirConditionerCurrent 冷氣電流"
        try:
            if sequence not in ["a", "b"]:
                raise TypeError("api_sequence_fail")
            data = api_ns.payload
            if data.get("current") is None:
                raise ValueError("data_fail")
            data["sequence"] = sequence
            data["date"] = datetime.datetime.now(tz)
            self.dbAirCondictionCurrent.update_one(
                {"sequence": sequence}, {'$set': data}, upsert=True)
        except Exception as e:
            error_class = e.__class__.__name__  # 錯誤類型
            detail = e.args[0]  # 詳細內容
            logger.warning(f"air_conditioner - current [{error_class}] {detail}")
            return {"air_conditioner - current": detail}, 400
        else:
            logger.info("air_conditioner - current data_ok")
            return {"air_conditioner - current": "data_ok"}


@api_ns.route("/air-conditioner/environment/<sequence>")
class AirConditioner(Resource):
    dbAirCondiction = mongodb["air_condiction"]

    air_conditioner_input_payload = api_ns.model("AirConditioner 輸入", {
        "temp": fields.Float(example=25.0),
        "humi": fields.Float(example=50.0)
    })

    air_conditioner_output_payload = api_ns.model("AirConditioner 輸出", {
        "air_conditioner - environment": fields.String(example="data_ok")
    })

    @api_ns.expect(air_conditioner_input_payload)
    @api_ns.marshal_with(air_conditioner_output_payload, code=200)
    @api_ns.response(400, "Error Data", air_conditioner_output_payload)
    def post(self, sequence):
        "AirConditioner 冷氣溫溼度"
        try:
            if sequence not in ["a", "b"]:
                raise TypeError("api_sequence_fail")
            else:
                data = api_ns.payload
                if data.get("temp") is None or data.get("humi") is None:
                    raise ValueError("data_fail")
                data["sequence"] = sequence
                data["date"] = datetime.datetime.now(tz)
            self.dbAirCondiction.update_one(
                {"sequence": sequence}, {'$set': data}, upsert=True)
        except Exception as e:
            error_class = e.__class__.__name__  # 錯誤類型
            detail = e.args[0]  # 詳細內容
            logger.warning(f"air-condiction [{error_class}] {detail}")
            return {"air_conditioner - environment": detail}, 400
        else:
            logger.info("air_conditioner - environment data_ok")
            return {"air_conditioner - environment": "data_ok"}


@api_ns.route("/camera-power")
class CameraPower(Resource):
    dbCameraPower = mongodb["cameraPower"]

    camera_power_input_payload = api_ns.model("CameraPower 輸入", {
        "camera_power": fields.Float(example=300.5)
    })

    camera_power_output_payload = api_ns.model("CameraPower 輸出", {
        "camera_power": fields.String(example="data_ok")
    })

    @api_ns.expect(camera_power_input_payload)
    @api_ns.marshal_with(camera_power_output_payload, code=200)
    @api_ns.response(400, "Error Data", camera_power_output_payload)
    def post(self):
        "電表辨識"
        try:
            cameraPower = api_ns.payload.get("camera_power")
            if cameraPower is None:
                raise ValueError("data-format-fail")
            elif not isinstance(cameraPower, float):
                raise TypeError("data-type-fail")

            data = self.dbCameraPower.find_one()
            data["yesterday"] = data["today"] if data else {
                "power": 0.0,
                "date": datetime.datetime.now(tz) - datetime.timedelta(days=1)
            }
            data["today"] = {
                "power": cameraPower,
                "date": datetime.datetime.now(tz)
            }
            self.dbCameraPower.update_one({}, {'$set': data}, upsert=True)
        except Exception as e:
            error_class = e.__class__.__name__  # 錯誤類型
            detail = e.args[0]  # 詳細內容
            logger.warning(f"camera_power [{error_class}] {detail}")
            return {"camera_power": detail}, 400
        else:
            logger.info("camera_power data_ok")
            return {"camera_power": "data_ok"}


@api_ns.route("/daily-report")
class DailyReport(Resource):
    dbDailyReport = mongodb["dailyReport"]

    mysql_config = config["MYSQL"]

    get_weather_url = config["WEATHER"]["URL"]

    get_weather_base_params = {
        "Authorization": config["WEATHER"]["TOKEN"],
        "locationName": "北區",
        "startTime": ",".join([
            "{date}T06:00:00",
            "{date}T09:00:00",
            "{date}T12:00:00"
        ]),
        "dataTime": "{date}T09:00:00"
    }

    daily_report_output_data_payload = api_ns.model("每日通報 資料輸出", {
        "date": fields.String(example="2022-01-01"),
        "error": fields.List(fields.String()),
        "ups_a": fields.Float(example=72.542),
        "ups_b": fields.Float(example=75.4889),
        "air_condiction_a": fields.Float(example=31.1861),
        "air_condiction_b": fields.Float(example=37.7601),
        "water_tank": fields.Float(example=55.5403),
        "WeatherDescription": fields.String(example="短暫陣雨。降雨機率 60%。溫度攝氏26度。舒適。偏南風 平均風速2-3級(每秒4公尺)。相對濕度94%。"),
        "CI": fields.String(example="悶熱"),
        "Wx": fields.String(example="短暫陣雨"),
        "WD": fields.String(example="偏南風"),
        "PoP12h": fields.Integer(example=40),
        "AT": fields.Integer(example=34),
        "T": fields.Integer(example=30),
        "RH": fields.Integer(example=96),
        "PoP6h": fields.Integer(example=60),
        "WS": fields.Integer(example=4),
        "Td": fields.Integer(example=29)
    })

    def db_query(self, args):
        result_data = {
            "error": list()
        }
        sql = """
            SELECT {output} FROM {table} 
            WHERE Time_Stamp BETWEEN %(yesterday)s and %(today)s;
        """
        service_list = {
            "ups_a": {
                "table": "UPS_A",
                "output": "AVG(Output_Watt)*24+(220.0*1.5*24/1000)"
            },
            "ups_b": {
                "table": "UPS_B",
                "output": "AVG(Output_Watt)*24+(220.0*2.0*24/1000)"
            },
            "air_condiction_a": {
                "table": "Power_Meter",
                "output": "AVG(Current_A)*220*24*1.732/1000"
            },
            "air_condiction_b": {
                "table": "Power_Meter",
                "output": "AVG(Current_B)*220*24*1.732/1000"
            },
            "water_tank": {
                "table": "Water_Tank",
                "output": "AVG(Current)*220*24*1.732/1000"
            }
        }
        # Connect to MySQL
        try:
            cursor = MySQLdb.connect(
                host=self.mysql_config["SERVER_IP"],
                port=self.mysql_config.getint("SERVER_PORT"),
                user=self.mysql_config["USER"],
                passwd=self.mysql_config["PASSWORD"],
                db=self.mysql_config["DATABASE"]
            ).cursor()
        except:
            logger.warning("failed to get sursor")
            result_data["error"].append('power')

        # Get service data from MySQL
        for service_name, service_data in service_list.items():
            try:
                cursor.execute(sql.format(**service_data), args)
                result_data[service_name] = round(
                    float(cursor.fetchone()[0]), 4)
            except:
                logger.warning(f"failed to get {service_name}")
                result_data[service_name] = 0.0
                result_data["error"].append(service_name)

        return result_data

    def get(self):
        "每日通報"
        data = {
            "date": datetime.datetime.now(tz)
        }
        try:
            daily_report_data = self.dbDailyReport.find_one()
            if daily_report_data and daily_report_data.get("date", None).date() == data["date"].date():
                data = daily_report_data
                del data["_id"]
            else:
                # Get Service data
                data.update(self.db_query({
                    "yesterday": datetime.datetime.combine(
                        data["date"].date() + datetime.timedelta(days=-2),  # Date
                        datetime.time(hour=16)  # Time
                    ).strftime("%Y-%m-%d %H:%M:%S"),
                    "today": datetime.datetime.combine(
                        data["date"].date() + datetime.timedelta(days=-1),  # Date
                        datetime.time(hour=16)  # Time
                    ).strftime("%Y-%m-%d %H:%M:%S")
                }))
                data["total"] = round(data["air_condiction_a"] + data["air_condiction_b"] + data["ups_a"] + data["ups_b"] + data["water_tank"], 4)
                try:
                    # Get Weather data
                    url_params = "&".join(
                        [f"{k}={v}" for k, v in self.get_weather_base_params.items()]).format(date=data["date"].strftime("%Y-%m-%d"))
                    weather_dict = requests.get(
                        f"{self.get_weather_url}?{url_params}",
                        headers={"accept": "application/json"}
                    ).json()
                    weather_element = weather_dict["records"]["locations"][0]["location"][0]["weatherElement"]
                    for element in weather_element:
                        module = element["elementName"]
                        if module == "CI":
                            value = element["time"][0]["elementValue"][1]["value"]
                        else:
                            value = element["time"][0]["elementValue"][0]["value"]
                        if module not in ["WeatherDescription", "WD", "Wx", "CI"]:
                            value = int(value)
                        data[module] = value
                except Exception as e:
                    data["error"].append('weather')
                self.dbDailyReport.update_one({}, {'$set': data}, upsert=True)
                requests.get(f"{cloud_server}/daily-report")
        except Exception as e:
            error_class = e.__class__.__name__  # 錯誤類型
            detail = e.args[0]  # 詳細內容
            logger.warning(f"daily_report [{error_class}] {detail}")
            return {"daily_report": detail}, 400
        else:
            data["date"] = data["date"].strftime("%Y-%m-%d")
            logger.info(f'daily_report {data["date"]} - success, data: {json.dumps(data)}')
            return {"daily_report": f'{data["date"]} - success', "data": data}


@api_ns.route("/service-list")
class ServiceList(Resource):
    dbServiceList = mongodb["serviceList"]

    def get(self):
        update_service = True
        data = {
            "error": [],
            "date": datetime.datetime.now(tz)
        }
        try:  # Unusable
            data["service"] = json.loads(requests.get(
                "http://10.0.0.140:30010/").text)["res"]
        except:
            update_service = False
            data["error"].append("輪播 Dashboard")
        finally:
            if update_service:
                service = data["service"]
                for x in range(len(service)):
                    if service[x]["enabled"] == False:
                        service.pop(x)
                    elif [x].get("notice") != None:
                        if service[x]["notice"].find("帳") >= 0 and service[x]["notice"].find("密") >= 0:
                            service[x]["user"] = service[x]["notice"].split("帳")[
                                1].split(" ")[0]
                            service[x]["pass"] = service[x]["notice"].split("密")[
                                1]
                        service[x].pop("notice")
            self.dbServiceList.update_one({}, {'$set': data}, upsert=True)
            data["date"] = data["date"].strftime("%Y-%m-%d %H:%M:%S")
            logger.info(f'service_list {data["date"]} - success')
            return {"service_list": f'{data["date"]} - success', "data": data}


@api_ns.route("/service-check")
class ServiceCheck(Resource):
    dbServiceCheck = mongodb["serviceCheck"]

    def get(self):
        update_service = True
        data = {
            "error": [],
            "date": datetime.datetime.now(tz)
        }
        try:  # Unusable
            data["service"] = json.loads(requests.get(
                "http://10.0.0.140:30010/").text)["res"]
        except:
            update_service = False
            data["error"].append("輪播 Dashboard")
        else:
            if update_service:
                for x in range(len(data["service"])):
                    try:
                        if data["service"][x]["name"] != "Kubernetes Dashboard":
                            response = requests.get(data["service"][x]["url"])
                        else:
                            response = requests.get(
                                data["service"][x]["url"], verify=False)

                        if response.status_code == 200:
                            data["service"][x]["status"] = "正常"
                        else:
                            data["service"][x]["status"] = "異常"
                            data["error"].append(data["service"][x]["name"])
                    except:
                        data["service"][x]["status"] = "異常"
                        if data["service"][x]["enabled"] == True:
                            data["error"].append(data["service"][x]["name"])
                    if (data["service"][x].get("notice") != None):
                        data["service"][x].pop("notice", None)
        finally:
            self.dbServiceCheck.update_one({}, {'$set': data}, upsert=True)
            if data["date"].time() >= datetime.time(hour=12) and data["date"].time() <= datetime.time(hour=12, minute=1):
                try:
                    response = requests.get(f"{cloud_server}/service-check")
                except Exception as e:
                    logger.warning(f'service_check {data["date"]} - {e}')
                else:
                    logger.info(f'service_check {data["date"]} - success')
            data["date"] = data["date"].strftime("%Y-%m-%d %H:%M:%S")
            return {"service_check": f'{data["date"]} - success', "data": data}


@api_ns.route("/rotation-user")
class RotationUser(Resource):
    dbServiceList = mongodb["serviceList"]
    dbRotationUser = mongodb["rotationUser"]

    def get(self):
        if self.dbServiceList.find_one() != None:
            weekDay = 0
            if datetime.date.today().month % 6 == 3:
                weekDay = 0
            elif datetime.date.today().month % 6 == 4:
                weekDay = 1
            elif datetime.date.today().month % 6 == 5:
                weekDay = 2
            elif datetime.date.today().month % 6 == 6:  # ???
                weekDay = 3
            elif datetime.date.today().month % 6 == 7:  # ???
                weekDay = 4
            elif datetime.date.today().month % 6 == 8:  # ???
                weekDay = 5
            user = self.dbRotationUser.find_one()["rotation"][weekDay]['user']
            self.dbRotationUser.update_one(
                {}, {'$set': {"rotation." + str(6) + ".user": user}})
        try:
            requests.get(f"{cloud_server}/rotation-user")
        except Exception as e:
            logger.warning(f"rotation-user {e}")
        else:
            logger.info("rotation-user get-success")
        return {"rotation-user": "get-success"}


@api_ns.route("/rotation-user/<int:x>")
class RotationUser(Resource):
    dbServiceList = mongodb["serviceList"]
    dbRotationUser = mongodb["rotationUser"]

    rotation_user_input_payload = api_ns.model("rotationUser 輸入", {
        "user": fields.List(fields.String(example=""))
    })

    @api_ns.expect(rotation_user_input_payload)
    def post(self, x):
        try:
            if x < 1 or x > 7:
                raise ValueError("weekDay-fail")
            user_list = api_ns.payload.get("user")
            if user_list is None:
                raise ValueError("data-format-fail")
            elif not isinstance(user_list, list):
                raise TypeError("data-type-fail")
            elif self.dbServiceList.find_one() == None:
                data = {
                    "rotation": list()
                }
                week_list = ["一", "二", "三", "四", "五", "六", "日"]
                for w in range(7):
                    week_user = {
                        "user": list()
                    }
                    if w + 2 == x:  # ???
                        for z in range(len(user_list)):
                            week_user["user"].append(user_list[z])  # ???
                    else:
                        week_user["user"].append(f"星期{week_list[w]}_人員_0")
                        week_user["user"].append(f"星期{week_list[w]}_人員_1")
                    data["rotation"].append(week_user)
                self.dbRotationUser.insert_one(data)
            else:
                self.dbRotationUser.update_one(
                    {}, {'$set': {f"rotation.{x-1}.user": user_list}}, upsert=True)
                data = self.dbRotationUser.find_one()
            del data["_id"]
        except Exception as e:
            error_class = e.__class__.__name__  # 錯誤類型
            detail = e.args[0]  # 詳細內容
            logger.warning(f"rotationUser [{error_class}] {detail}")
            return {"rotation_user": detail}, 400
        else:
            logger.info("rotation_user success")
            return {"rotation_user": "success", "data": data}


if __name__ == "__main__":
    # Running server
    app.run(host="0.0.0.0", port=config["BACKEND"]["SERVER_PORT"], debug=True)
