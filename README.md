# IMAC_TelegramBot

## Telegram Backend Endpoint app.py

Webhook: \<Domain\>/hook  
Swagger: \<Domain\>/api/doc  

| Method | URL Path | Description | Note |
| - | - | - | - |
| GET | /test/\<mode\> | 測試用 API | mode: message, localPhoto, localAudio, localGif, onlinePhoto, onlineAudio, onlineGif |
| POST | /linebot | LineBot 設定機房資訊 | \* 目前 LineBot 廢棄中 |
| GET | /rotation-user | 服務列表 |  |
| GET | /service-check | 服務狀態 |  |
| GET | /daily-report | 每日通報 |  |
| POST | /alert/\<model\> | 發出警告 | model: librenms, icinga, ups |

## Flask Backend Endpoint api_server.py 

| Method | URL Path | Description | Note |
| - | - | - | - |
| GET | /api/doc | Swagger 測試頁面 |  |
| POST | /dl303/\<module\> | 傳送 DL-303 監測狀態 | module: tc, rh, dc, co2 |
| GET | ​/et7044 | 取得 ET-7044 狀態 |  |
| POST | ​/et7044 | 傳送 ET-7044 狀態 |  |
| POST | ​/ups​/\<sequence\> | 傳送 UPS 狀態 | sequence: a, b |
| POST | ​/water-tank | 水塔電流 |  |
| POST | ​/power-box | 電箱溫溼度 |  |
| POST | ​/air-conditioner​/current​/\<sequence\> | 冷氣電流 | sequence: a, b |
| POST | /air-conditioner/environment/\<sequence\> | 冷氣溫溼度 | sequence: a, b |
| POST | /camera-power | 智慧電表辨識 |  |
| GET | /daily-report | 每日通報 | \* request to app |
| GET | /service-list | 服務列表 |  |
| GET | /service-check | 服務狀態 | \* request to app |
| GET | /rotation-user | 取得輪值人員 | \* request to app |
| POST | /rotation-user/\<int:x\> | 更新輪值人員 | 1 <= x <= 7 \* Notice |

## MQTT Topic and Device

### DL-303

IP: 10.20.1.158  
https://www.verily.com.tw/products_detail/32.htm  

| Topic | Description | Message | Note |
| - | - | - | - |
| DL303/TC | 溫度 | -10 ~ +50 (°C) |  |
| DL303/RH | 相對溼度 | 0 ~ 100 (%) (non-condensing) |  |
| DL303/DC | 露點溫度 | 由溫度與相對溼度計算而得 |  |
| DL303/CO | 一氧化碳濃度 | 0 ~ 1000(ppm) (Electrochemical) |  |
| DL303/CO2 | 二氧化碳濃度 | 0 ~ 9999(ppm) (NDIR) |  |

### ET-7044

IP: 10.20.1.241  
https://www.verily.com.tw/products_detail/74.htm  

| Topic | Description | Message | Note |
| - | - | - | - |
| ET7044/DOstatus | ET-7044 狀態 | 參考 MQTT_message/UPS_X_Monitor_message.json |  |
| ET7044/write | ET-7044 控制 | 參考 MQTT_message/UPS_X_Monitor_message.json |  |

### Air-condition & WaterTank

IP: 10.0.0.172

| Topic | Description | Message | Note |
| - | - | - | - |
| waterTank | 水塔電流 | 參考 MQTT_message/waterTank.json |  |
| current | 冷氣電流 | 參考 MQTT_message/current.json |  |

### UPS A & B

IP: 10.0.0.195, 10.0.0.185

| Topic | Description | Message | Note |
| - | - | - | - |
| UPS/A/Monitor | UPS A 狀態 (牆壁) | 參考 MQTT_message/UPS_A_Monitor.json |  |
| UPS/B/Monitor | UPS B 狀態 (窗戶) | 參考 MQTT_message/UPS_B_Monitor.json |  |
| UPS_Monitor | UPS 資料合併 | 參考 MQTT_message/UPS_Monitor.json | from ups_split_mqtt.py |

### 冷氣溫溼度

IP: 192.168.0.11, 192.168.0.13  

| Topic | Description | Message | Note |
| - | - | - | - |
| air_condiction/A | 冷氣 A  (牆壁) 溫溼度 | 參考 MQTT_message/air_condiction_A.json |  |
| air_condiction/B | 冷氣 B  (窗戶) 溫溼度 | 參考 MQTT_message/air_condiction_B.json |  |
