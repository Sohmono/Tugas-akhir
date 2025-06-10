# yolo_firebase_threaded.py

import cv2
import time
import numpy as np
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

yolo_model = YOLO("detection.pt")
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
    db.reference('/KelasEsp').set(pred)

def kirim_notifikasi_telegram(kelas, frame):
    pesan_dict = {
        0: "Deteksi: Ada manusia dengan objek berbahaya",
        1: "⚠️ Deteksi: Ada upaya pendobrakan!",
        3: "ℹ️ Deteksi: Seseorang memasuki rumah!",
        4: "🚨 Deteksi: Telah terjadi pembobolan!",
        5: "🚨 Deteksi: Telah terjadi pencurian",
        6: "📡 Deteksi: Ada tamu di depan rumah!",
        7: "📡 Deteksi: Ada manusia membawa benda!"
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

            features = np.array([[
                get_feature_value(latest_data, 'Getar'),
                get_feature_value(latest_data, 'Suara'),
                get_feature_value(latest_data, 'X'),
                get_feature_value(latest_data, 'Y'),
                get_feature_value(latest_data, 'Z'),
                get_feature_value(latest_data, 'Jumlah manusia'),
                get_feature_value(latest_data, 'Jlh manusiaxbarang'),
                get_feature_value(latest_data, 'Jlh manusiaxbahaya'),
                get_feature_value(latest_data, 'Mean barang'),
                get_feature_value(latest_data, 'Mean bahaya')
            ]])

            prediction = lgbm_model.predict(features)[0]
            if prediction != last_prediction:
                last_prediction = prediction
                kirim_notifikasi_telegram(prediction, last_frame_tele)
            push_lgbm_to_firebase(prediction, date_key, latest_key)
        except Exception as e:
            print(f"[LGBM THREAD ERROR] {e}")
        time.sleep(1)

# === YOLO DEBUG VISUALIZATION === #
def debug_yolo_only(frame):
    results = yolo_model(frame, conf=0.3)[0]
    print(f"[YOLO] Detections: {len(results.boxes)}")
    for box in results.boxes:
        x1, y1, x2, y2 = map(int, box.xyxy[0])
        cv2.rectangle(frame, (x1, y1), (x2, y2), (0,255,0), 2)
    return frame

# === MAIN === #
def main():
    global last_frame_tele
    print("[INFO] Starting...")

    cap = VideoCaptureThreaded(RTSP_URL)
    process = subprocess.Popen([
        "C:/ffmpeg/bin/ffmpeg.exe",
        '-loglevel', 'info', '-y',
        '-f', 'rawvideo', '-vcodec', 'rawvideo',
        '-pix_fmt', 'bgr24', '-s', f'{WIDTH}x{HEIGHT}', '-r', str(FPS), '-i', '-',
        '-f', 'lavfi', '-i', 'anullsrc=channel_layout=stereo:sample_rate=44100',
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-preset', 'veryfast',
        '-c:a', 'aac', '-b:a', '128k', '-shortest', '-f', 'flv', RTMP_URL
    ], stdin=subprocess.PIPE)

    threading.Thread(target=klasifikasi_loop, daemon=True).start()

    while True:
        ret, frame = cap.read()
        if not ret:
            print("[RTSP] Frame kosong, reconnect...")
            cap.stop()
            time.sleep(2)
            cap = VideoCaptureThreaded(RTSP_URL)
            continue

        frame = cv2.resize(frame, (WIDTH, HEIGHT))
        last_frame_tele = frame.copy()

        # TEMPORARY DEBUG YOLO VISUAL
        frame = debug_yolo_only(frame)

        cv2.imshow("YOLOv8 + Firebase + YouTube", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

        try:
            process.stdin.write(frame.tobytes())
        except Exception as e:
            print(f"[FFMPEG ERROR] {e}")
            continue

    cap.stop()
    process.stdin.close()
    process.wait()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
