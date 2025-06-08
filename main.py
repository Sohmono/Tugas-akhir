import streamlit as st
import yaml
from passlib.hash import pbkdf2_sha256
import firebase_admin
from firebase_admin import credentials, db
from datetime import datetime
from io import StringIO
import re
import json
import pandas as pd
import time

# Firebase Init from secrets
if not firebase_admin._apps:
    cred_dict = json.loads(st.secrets["firebase_admin"])
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred, {
        'databaseURL': st.secrets["firebase_database_url"]
    })

# Load credentials
user_yaml = st.secrets["user_credentials"]
users = yaml.safe_load(StringIO(user_yaml))["credentials"]

# Session State Initialization
for k, v in {
    "login_success": False,
    "username": "",
    "name": "",
    "toggle_status": False,
    "toggle_initialized": False,
    "sensor_df": pd.DataFrame(columns=[
        "Tanggal", "Waktu", "Getar", "Suara", "X", "Y", "Z",
        "Jumlah Manusia", "Manusia x Bahaya", "Manusia x Barang",
        "Mean Bahaya", "Mean Barang"
    ]),
    "last_fetch": 0
}.items():
    st.session_state.setdefault(k, v)

# Login Page
def login_page():
    st.title("Login")
    with st.form("login_form"):
        username_input = st.text_input("Username")
        password_input = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login")

    if submitted:
        if username_input.strip() == "":
            popup("A")
        elif password_input.strip() == "":
            popup("B")
        elif username_input in users:
            if pbkdf2_sha256.verify(password_input, users[username_input]["password"]):
                st.session_state.login_success = True
                st.session_state.username = username_input
                st.session_state.name = users[username_input]["name"]
                st.success(f"Monitoring {st.session_state.name}!")
                st.rerun()
            else:
                popup("D")
        else:
            popup("C")

# Dialog popup
@st.dialog("Peringatan")
def popup(condition):
    pesan = {
        "A": "Mohon isi username",
        "B": "Mohon isi password",
        "C": "Username tidak ditemukan",
        "D": "Password salah"
    }
    st.write(pesan.get(condition, "Kesalahan tidak diketahui"))
    if st.button("OK"):
        st.rerun()

# Dialog konfirmasi toggle
@st.dialog("Konfirmasi Perubahan Sistem")
def konfirmasi_toggle_dialog(status_baru):
    teks = "AKTIFKAN" if status_baru else "NONAKTIFKAN"
    st.write(f"Anda yakin ingin **{teks}** sistem?")
    if st.button("✅ Oke"):
        st.session_state.toggle_status = status_baru
        toggle_ref = db.reference("/status_sistem")
        toggle_ref.update({
            "aktif": int(status_baru),
            "updated_at": datetime.now().strftime("%Y_%m_%d %H_%M_%S")
        })
        st.rerun()
    if st.button("❌ Batal"):
        st.rerun()

# Extract video ID from link
def extract_video_id(url):
    match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", url)
    return match.group(1) if match else None

# Load latest class from LGBM
def load_latest_kelas():
    ref = db.reference("/Dataset")
    data = ref.get()
    latest_dt = None
    latest_kelas = "Belum tersedia"
    if data:
        for tgl, w_dict in data.items():
            for wkt, detail in w_dict.items():
                try:
                    dt = datetime.strptime(f"{tgl} {wkt}", "%Y_%m_%d %H_%M_%S")
                    if not latest_dt or dt > latest_dt:
                        latest_dt = dt
                        latest_kelas = detail.get("Kelas")
                except:
                    continue
    return latest_kelas

# Ambil data terbaru dari /Dataset
def ambil_data_terbaru():
    dataset_ref = db.reference("/Dataset")
    dataset = dataset_ref.get()
    if not dataset:
        return

    tgl = sorted(dataset.keys())[-1]
    wkt = sorted(dataset[tgl].keys())[-1]
    data = dataset[tgl][wkt]

    new_row = {
        "Tanggal": tgl,
        "Waktu": wkt,
        "Getar": int(data.get("Getar", 0)),
        "Suara": int(data.get("Suara", 0)),
        "X": int(data.get("X", 0)),
        "Y": int(data.get("Y", 0)),
        "Z": int(data.get("Z", 0)),
        "Jumlah Manusia": int(data.get("Jumlah manusia", 0)),
        "Manusia x Bahaya": int(data.get("Jlh manusiaxbahaya", 0)),
        "Manusia x Barang": int(data.get("Jlh manusiaxbarang", 0)),
        "Mean Bahaya": float(data.get("Mean bahaya", 0.0)),
        "Mean Barang": float(data.get("Mean barang", 0.0)),
    }

    df = st.session_state.sensor_df
    if not ((df["Tanggal"] == tgl) & (df["Waktu"] == wkt)).any():
        df.loc[len(df)] = new_row
        st.session_state.sensor_df = df.tail(100).reset_index(drop=True)

# Main Page After Login
def main_page():
    latest_kelas = load_latest_kelas()

    st.markdown("<h1 style='text-align: center; color: black;'>Sistem Cerdas Keamanan Rumah</h1>", unsafe_allow_html=True)
    try:
        firebase_url = db.reference("/streaming/video_url").get()
        video_id = extract_video_id(firebase_url) if firebase_url else "kpbzVG_lBY4"
    except Exception as e:
        st.warning(f"Gagal mengambil video dari Firebase: {e}")
        video_id = "kpbzVG_lBY4"

    st.markdown(f"""
        <iframe width="800" height="450"
        src="https://www.youtube.com/embed/{video_id}?autoplay=1"
        frameborder="0"
        allow="accelerometer; autoplay; encrypted-media; gyroscope; picture-in-picture"
        allowfullscreen></iframe>
    """, unsafe_allow_html=True)
    st.markdown(f"<h1 style='text-align: center; color: black;'>Kelas Terbaru: {latest_kelas}</h1>", unsafe_allow_html=True)

    # Toggle status kontrol sistem
    toggle_ref = db.reference("/status_sistem")
    firebase_status = bool(toggle_ref.get().get("aktif", 0))
    if not st.session_state.toggle_initialized:
        st.session_state.toggle_status = firebase_status
        st.session_state.toggle_initialized = True

    st.markdown("### Kontrol Sistem")
    if st.toggle("Aktifkan Sistem", value=st.session_state.toggle_status, key="main_toggle") != st.session_state.toggle_status:
        konfirmasi_toggle_dialog(not st.session_state.toggle_status)

    if st.session_state.toggle_status:
        st.success("✅ Sistem AKTIF")
    else:
        st.error("⛔ Sistem NONAKTIF")

    # Polling data terbaru
    if time.time() - st.session_state.last_fetch >= 1:
        ambil_data_terbaru()
        st.session_state.last_fetch = time.time()

    st.markdown("### 📊 Data Sensor Realtime")
    st.dataframe(st.session_state.sensor_df.tail(50), use_container_width=True)

    if st.button("🔄 Reset Tabel"):
        st.session_state.sensor_df = st.session_state.sensor_df.iloc[0:0]

# Routing
if not st.session_state.login_success:
    login_page()
else:
    main_page()