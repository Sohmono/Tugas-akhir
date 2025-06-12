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
CRED_PATH = "backupta-4c28a-firebase-adminsdk-fbsvc-492d1a6b7a.json"
LGBM_PATH = "LGBM/model_lightgbm2.pkl"

# === INISIALISASI === #
cred = credentials.Certificate(CRED_PATH)
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://backupta-4c28a-default-rtdb.asia-southeast1.firebasedatabase.app'
    })

yolo_model = YOLO("yolov8s.pt")
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

def push_lgbm_to_firebase(pred):
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
        'Jlh manusiaxbahaya': jlh_bahaya,
        'Jlh manusiaxbarang': jlh_barang,
        'Mean bahaya': float(mean_bahaya),
        'Mean barang': float(mean_barang),
        'Luar': posisi
    })
    db.reference('/LuarESP').set(posisi)
    db.reference(f'/DataReal').set({
        'Jumlah manusia': manusia,
        'Jlh manusiaxbahaya': jlh_bahaya,
        'Jlh manusiaxbarang': jlh_barang,
        'Mean bahaya': float(mean_bahaya),
        'Mean barang': float(mean_barang),
    })

def kirim_notifikasi_telegram(kelas, frame):
    pesan_dict = {
        
        "Waspada": "🚨 Deteksi: Ada manusia dengan objek berbahaya",
        "Dobrak": "⚠️ Deteksi: Ada upaya pendobrakan!",
        "Orang masuk": "ℹ️ Deteksi: Seseorang memasuki rumah!",
        "Pembobolan": "🚨 Deteksi: Telah terjadi pembobolan!",
        "Pencurian": "🚨 Deteksi: Telah terjadi pencurian",
        "Tamu depan": "📡 Deteksi: Ada tamu di depan rumah!",
        "Bahaya": "📡 Deteksi: Ada manusia membawa benda!"
    }
    pesan = pesan_dict.get(kelas)
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
            # === AMBIL DATA TERBARU DARI /DataReal (langsung, bukan array child) ===
            latest_data = db.reference('/DataReal').get()
            if not latest_data:
                print("[INFO] Data /DataReal belum ada.")
                time.sleep(1)
                continue

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

            now = datetime.now()
            date_key = now.strftime("%Y_%m_%d")
            time_key = now.strftime("%H_%M_%S")
            db.reference(f'/Dataset/{date_key}/{time_key}/Kelas').set(str(prediction))

            if prediction != last_prediction:
                last_prediction = prediction
                kirim_notifikasi_telegram(prediction, last_frame_tele)
            push_lgbm_to_firebase(prediction)
        except Exception as e:
            print(f"[LGBM THREAD ERROR] {e}")
        time.sleep(1)

# === YOLO DETEKSI DAN VISUALISASI === #
def analisa_yolo(frame):
    results = yolo_model(frame, conf=0.5, verbose=False)[0]
    manusia, barang, bahaya = [], [], []
    posisi_luar = 0

    if not hasattr(results, "boxes") or results.boxes is None or len(results.boxes) == 0:
        print("[YOLO] Tidak ada deteksi.")
        return 0, 0, 0, 0, 0, posisi_luar

    for box in results.boxes:
        x1, y1, x2, y2 = map(int, box.xyxy[0])
        cls_id = int(box.cls[0])
        if cls_id == 0:
            label = "manusia"
            manusia.append((x1, y1, x2, y2))

            if y1 < frame.shape[0] * 0.2:
                posisi_luar = 1
            else:
                posisi_luar = 0

        elif cls_id in [3, 63, 67]:
            label = "grup barang"
            barang.append((x1, y1, x2, y2))
        elif cls_id in [34, 39, 42, 43, 44]:
            label = "grup bahaya"
            bahaya.append((x1, y1, x2, y2))
        else:
            continue

        color = (0, 255, 0) if cls_id == 0 else (255, 255, 0) if cls_id in [3, 63, 67] else (0, 0, 255)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        cv2.putText(frame, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

    def calc_iou(boxA, boxB):
        xi1, yi1 = max(boxA[0], boxB[0]), max(boxA[1], boxB[1])
        xi2, yi2 = min(boxA[2], boxB[2]), min(boxA[3], boxB[3])
        inter_area = max(0, xi2 - xi1) * max(0, yi2 - yi1)
        areaA = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
        areaB = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
        return inter_area / (areaA + areaB - inter_area + 1e-6)

    iou_barang, iou_bahaya = [], []
    for h in manusia:
        for b in barang:
            iou = calc_iou(h, b)
            if iou > 0.05:
                iou_barang.append(iou)
    for h in manusia:
        for z in bahaya:
            iou = calc_iou(h, z)
            if iou > 0.05:
                iou_bahaya.append(iou)

    return len(manusia), len(iou_barang), len(iou_bahaya), round(np.mean(iou_barang), 2) if iou_barang else 0, round(np.mean(iou_bahaya), 2) if iou_bahaya else 0, posisi_luar

# === MAIN === #
def main():
    global last_frame_tele
    print("[INFO] Starting...")

    cap = VideoCaptureThreaded(RTSP_URL)
    while True:
        ret, frame = cap.read()
        if ret and frame is not None and frame.size > 0:
            break
        print("[WAITING] Menunggu frame pertama...")
        time.sleep(0.5)

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
    last_sent = time.time()

    while True:
        ret, frame = cap.read()
        if not ret or frame is None:
            print("[RTSP] Frame kosong, reconnect...")
            cap.stop()
            time.sleep(2)
            cap = VideoCaptureThreaded(RTSP_URL)
            continue

        frame = cv2.resize(frame, (WIDTH, HEIGHT))
        last_frame_tele = frame.copy()

        manusia, jlh_barang, jlh_bahaya, mean_barang, mean_bahaya, posisi_luar = analisa_yolo(frame)

        if time.time() - last_sent >= 1:
            date_key, time_key = get_datetime_keys()
            push_yolo_to_firebase(date_key, time_key, manusia, jlh_barang, jlh_bahaya, mean_barang, mean_bahaya, posisi_luar)
            print(f"[FIREBASE] Upload: {manusia=} {jlh_barang=} {jlh_bahaya=} {mean_barang=} {mean_bahaya=} {posisi_luar=}")
            last_sent = time.time()

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
