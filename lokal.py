# yolo_firebase_threaded.py

import cv2
import time
import numpy as np
import pandas as pd
import firebase_admin
from firebase_admin import credentials, db
from ultralytics import YOLO
from telegram import Bot
from datetime import datetime
import threading
import subprocess
import joblib

# === KONFIGURASI === #
RTSP_URL = 'rtsp://100534764:sKXYx6ry@192.168.0.157:554/stream1'
RTMP_URL = "rtmp://a.rtmp.youtube.com/live2/sbws-b74x-4q5z-4yhw-b3pe"
WIDTH, HEIGHT, FPS = 640, 480, 25
TELEGRAM_TOKEN = "7363881175:AAGgpqsQV7-AErp1O2ejfF0Wx2i3a4VIH4Q"
CHAT_ID = "-4918338351"
CRED_PATH = "securitydata-c84bb-firebase-adminsdk-fbsvc-3c16182d19.json"
LGBM_PATH = "LGBM/model_lightgbm.pkl"

# === INISIALISASI === #
cred = credentials.Certificate(CRED_PATH)
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://securitydata-c84bb-default-rtdb.asia-southeast1.firebasedatabase.app'
    })

human_model = YOLO("human.pt")
object_model = YOLO("object.pt")
try:
    yolo_model.to('cuda')
except:
    print("[WARNING] CUDA tidak tersedia, jalan di CPU")
lgbm_model = joblib.load(LGBM_PATH)
bot = Bot(token=TELEGRAM_TOKEN)
last_frame_tele = None
last_prediction = None

# === BANTUAN === #
def get_datetime_keys():
    now = datetime.now()
    return now.strftime("%Y_%m_%d"), now.strftime("%H_%M_%S")

def get_feature_value(data, key, default=0):
    try:
        return data.get(key, default)
    except:
        return default

def push_lgbm_to_firebase(pred, date_key, time_key):
    db.reference(f'/Dataset/{date_key}/{time_key}').update({'Kelas': pred})

    kelas_map = {
        'Bahaya': 0,
        'Dobrak': 1,
        'Kosong': 2,
        'Orang masuk': 3,
        'Pembobolan': 4,
        'Pencurian': 5,
        'Tamu depan': 6,
        'Waspada': 7
    }

    predInt = kelas_map.get(pred, -1)
    db.reference('/KelasEsp').set(predInt)

def push_yolo_to_firebase(date_key, time_key, manusia, jlh_barang, jlh_bahaya, mean_barang, mean_bahaya, posisi):
    db.reference(f'/Dataset/{date_key}/{time_key}').set({
        'Jumlah manusia': manusia,
        'Jlh grup barang': jlh_barang,
        'Jlh grup bahaya': jlh_bahaya,
        'Mean grup barang': float(mean_barang),
        'Mean grup bahaya': float(mean_bahaya),
        'Luar': posisi
    })
    db.reference('/LuarESP').set(posisi)

def kirim_notifikasi_telegram(kelas, frame):
    pesan_dict = {
        "Bahaya": "Deteksi: Ada manusia dengan objek berbahaya",
        "Dobrak": "⚠️ Deteksi: Ada upaya pendobrakan!",
        "Orang masuk": "ℹ️ Deteksi: Seseorang memasuki rumah!",
        "Pembobolan": "🚨 Deteksi: Telah terjadi pembobolan!",
        "Pencurian": "🚨 Deteksi: Telah terjadi pencurian",
        "Tamu depan": "📡 Deteksi: Ada tamu di depan rumah!",
        "Waspada": "📡 Deteksi: Ada manusia membawa benda!"
    }
    pesan = pesan_dict.get(kelas, "Deteksi tidak diketahui")
    try:
        bot.send_message(chat_id=CHAT_ID, text=pesan)
        if frame is not None:
            _, buffer = cv2.imencode('.jpg', frame)
            bot.send_photo(chat_id=CHAT_ID, photo=buffer.tobytes())
    except Exception as e:
        print(f"[TELEGRAM ERROR] {e}")

# === VIDEO STREAM === #
class VideoCaptureThreaded:
    def __init__(self, src):
        self.stream = cv2.VideoCapture(src, cv2.CAP_FFMPEG)
        self.ret, self.frame = self.stream.read()
        self.stopped = False
        threading.Thread(target=self.update, daemon=True).start()

    def update(self):
        while not self.stopped:
            self.stream.grab()
            self.ret, self.frame = self.stream.read()

    def read(self):
        return self.ret, self.frame

    def stop(self):
        self.stopped = True
        self.stream.release()

# === KLASIFIKASI THREAD === #
def klasifikasi_loop():
    global last_prediction, last_frame_tele
    while True:
        try:
            date_key, _ = get_datetime_keys()
            data_ref = db.reference(f'/Dataset/{date_key}').get()
            if not data_ref:
                time.sleep(1)
                continue

            latest_key = sorted(data_ref.keys())[-1]
            latest_data = data_ref[latest_key]

            feature_names = [
                'Getar', 'Suara', 'X', 'Y', 'Z',
                'Jumlah manusia', 'Jlh grup barang', 'Jlh grup bahaya',
                'Mean grup barang', 'Mean grup bahaya'
            ]

            features = pd.DataFrame([[
                get_feature_value(latest_data, 'Getar'),
                get_feature_value(latest_data, 'Suara'),
                get_feature_value(latest_data, 'X'),
                get_feature_value(latest_data, 'Y'),
                get_feature_value(latest_data, 'Z'),
                get_feature_value(latest_data, 'Jumlah manusia'),
                get_feature_value(latest_data, 'Jlh grup barang'),
                get_feature_value(latest_data, 'Jlh grup bahaya'),
                get_feature_value(latest_data, 'Mean grup barang'),
                get_feature_value(latest_data, 'Mean grup bahaya')
            ]], columns=feature_names)

            prediction = lgbm_model.predict(features)[0]
            if prediction != last_prediction:
                last_prediction = prediction
                kirim_notifikasi_telegram(prediction, last_frame_tele)
            push_lgbm_to_firebase(prediction, date_key, latest_key)
        except Exception as e:
            print(f"[LGBM THREAD ERROR] {e}")
        time.sleep(1)
