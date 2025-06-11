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
    ref = db.reference("/KelasEsp").get()
    mapping = {
        0: "Bahaya",
        1: "Dobrak",
        2: "Kosong",
        3: "Orang masuk",
        4: "Pembobolan",
        5: "Pencurian",
        6: "Tamu depan",
        7: "Waspada"
    }
    return mapping.get(ref,"Kosong")

# Ambil data terbaru dari /Dataset
def ambil_data_terbaru(limit=5):    
    ref_tgl = db.reference("/Dataset")
    tgl_dict = ref_tgl.order_by_key().limit_to_last(1).get()
    if not tgl_dict:
        return

    tgl = list(tgl_dict.keys())[0]
    ref_wkt = db.reference(f"/Dataset/{tgl}")
    wkt_dict = ref_wkt.order_by_key().limit_to_last(limit).get()
    if not wkt_dict:
        return

    # Buat dataframe dari data waktu terbaru
    new_rows = []
    for wkt in sorted(wkt_dict.keys()):
        data = wkt_dict[wkt]
        new_rows.append({
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
        })

    df = pd.DataFrame(new_rows)
    # Tambah data yang belum ada di session state
    df_old = st.session_state.sensor_df
    merged = pd.concat([df_old, df]).drop_duplicates(subset=["Tanggal", "Waktu"], keep="last")
    st.session_state.sensor_df = merged.tail(100).reset_index(drop=True)


# Main Page After Login
def main_page():
    latest_kelas = load_latest_kelas()

    st.markdown("<h1 style='text-align: center; color: black;'>Sistem Cerdas Keamanan Rumah</h1>", unsafe_allow_html=True)
    try:
        firebase_url = db.reference("/streaming").get()
        video_id = extract_video_id(firebase_url) if firebase_url else "kpbzVG_lBY4"
    except Exception as e:
        st.warning(f"Gagal mengambil video dari Firebase: {e}")
        video_id = "kpbzVG_lBY4"

    st.markdown(f"""
        <div style="position: relative; padding-bottom: 56.25%; height: 0; overflow: hidden;">
            <iframe src="https://www.youtube.com/embed/Wj-t1-leK2c"
                    style="position: absolute; top: 0; left: 0; width: 100%; height: 100%;"
                    frameborder="0"
                    allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                    allowfullscreen>
            </iframe>
        </div>
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
