#include <Arduino.h>
#include <WiFi.h>
#include <Wire.h>
#include <Firebase_ESP_Client.h>
#include <QMC5883LCompass.h>

#include "addons/TokenHelper.h"
#include "addons/RTDBHelper.h"

// WiFi & Firebase
#define WIFI_SSID "WIFI-2.4G-9019D5"
#define WIFI_PASSWORD "Sekolah037997"
#define API_KEY "AIzaSyDCnpbbLOaWsXOGxjQOI4T1xot4i_ReFgU"
#define DATABASE_URL "https://securitydata-c84bb-default-rtdb.asia-southeast1.firebasedatabase.app"
#define USER_EMAIL "sarutobitakashi@gmail.com"
#define USER_PASSWORD "Takashi@2004"

FirebaseData fbdo;
FirebaseAuth auth;
FirebaseConfig config;

unsigned long lastSendTime = 0;
const unsigned long sendInterval = 1000;
unsigned long lastBuzzTime = 0;
const unsigned long buzzInterval = 60000;
unsigned long lastSoundReadTime = 0;
const unsigned long soundReadInterval = 100;
int maxSound = 0;

// PIN
#define VIBRATION_PIN 15
#define SOUND_PIN 34
#define SDA_PIN 21
#define SCL_PIN 22
#define BUZZER_PIN 25

int vibrationCount = 0;
bool lastVibrationState = false;

// Kompas
QMC5883LCompass compass;
int prevX = 0, prevY = 0, prevZ = 0;
const int threshold = 300;

// Firebase value
int latestClass = 2;
int luar = 0;
int sistemAktif = 0;

void setup() {
  Serial.begin(115200);
  pinMode(VIBRATION_PIN, INPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);
  Wire.begin(SDA_PIN, SCL_PIN);
  compass.init();

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting to Wi-Fi");
  while (WiFi.status() != WL_CONNECTED) {
    Serial.print(".");
    delay(300);
  }
  Serial.println("\nWi-Fi connected");

  configTime(7 * 3600, 0, "pool.ntp.org", "time.nist.gov");
  Serial.println("Synchronizing time with NTP...");
  struct tm timeinfo;
  while (!getLocalTime(&timeinfo)) {
    Serial.print(".");
    delay(500);
  }
  Serial.println("\nTime synchronized.");

  config.api_key = API_KEY;
  config.database_url = DATABASE_URL;
  auth.user.email = USER_EMAIL;
  auth.user.password = USER_PASSWORD;
  Firebase.begin(&config, &auth);
  Firebase.reconnectWiFi(true);
}

void loop() {
  Firebase.ready();
  unsigned long currentTime = millis();

  // Deteksi getaran (rising edge)
  bool currentVibration = digitalRead(VIBRATION_PIN);
  if (currentVibration && !lastVibrationState) {
    vibrationCount++;
  }
  lastVibrationState = currentVibration;

  // Deteksi suara
  if (currentTime - lastSoundReadTime >= soundReadInterval) {
    lastSoundReadTime = currentTime;
    int currentSound = analogRead(SOUND_PIN);
    if (currentSound > maxSound) {
      maxSound = currentSound;
    }
  }

  // Deteksi kompas
  compass.read();
  int x = compass.getX();
  int y = compass.getY();
  int z = compass.getZ();

  int dx = abs(x - prevX);
  int dy = abs(y - prevY);
  int dz = abs(z - prevZ);
  if (dx > threshold || dy > threshold || dz > threshold) {
    Serial.println("GANGGUAN MEDAN MAGNET TERDETEKSI!");
  }
  prevX = x;
  prevY = y;
  prevZ = z;


    if (sistemAktif) {
      switch (latestClass) {
        case 0:
          for (int i = 0; i < 10; i++) {
            tone(BUZZER_PIN, 1000); delay(200);
            tone(BUZZER_PIN, 1500); delay(200);
            noTone(BUZZER_PIN); delay(100);
          }
          break;
        case 1:
          for (int i = 0; i < 10; i++) {
            tone(BUZZER_PIN, 900); delay(150);
            tone(BUZZER_PIN, 1800); delay(150);
            noTone(BUZZER_PIN); delay(100);
          }
          break;
        case 4:
          for (int i = 0; i < 10; i++) {
            tone(BUZZER_PIN, 1200); delay(300);
            noTone(BUZZER_PIN); delay(100);
          }
          break;
        case 5:
          for (int i = 0; i < 4; i++) {
            tone(BUZZER_PIN, 800); delay(200);
            tone(BUZZER_PIN, 1600); delay(200);
            noTone(BUZZER_PIN); delay(150);
          }
          break;
        case 3:
          if (luar == 1) {
            tone(BUZZER_PIN, 1047); delay(300);
            tone(BUZZER_PIN, 1319); delay(300);
            tone(BUZZER_PIN, 1568); delay(300);
          }
          break;
        case 6:
          tone(BUZZER_PIN, 1047); delay(300);
          tone(BUZZER_PIN, 1319); delay(300);
          tone(BUZZER_PIN, 1568); delay(300);
          noTone(BUZZER_PIN);
          break;
        default:
          noTone(BUZZER_PIN);
          break;
      }
    }

  // Upload data ke Firebase setiap detik
  if (currentTime - lastSendTime >= sendInterval) {
    lastSendTime = currentTime;

    // Ambil waktu sekarang
    struct tm timeinfo;
    if (!getLocalTime(&timeinfo)) {
      Serial.println("Failed to obtain time");
      return;
    }
    char timeStr[10];
    strftime(timeStr, sizeof(timeStr), "%H_%M_%S", &timeinfo);
    char dateStr[11];
    strftime(dateStr, sizeof(dateStr), "%Y_%m_%d", &timeinfo);

    // Baca status dari Firebase (hanya setiap 1 detik)
    if (Firebase.RTDB.getInt(&fbdo, "/status_sistem/aktif")) {
      sistemAktif = fbdo.intData();
    }
    if (Firebase.RTDB.getInt(&fbdo, "/KelasEsp")) {
      latestClass = fbdo.intData();
    }
    if (Firebase.RTDB.getInt(&fbdo, "/LuarEsp")) {
      luar = fbdo.intData();
    }

    // Siapkan data
    int sound = maxSound;
    maxSound = 0;

    compass.read();
    int x = compass.getX();
    int y = compass.getY();
    int z = compass.getZ();

    int dx = abs(x - prevX);
    int dy = abs(y - prevY);
    int dz = abs(z - prevZ);
    if (dx > threshold || dy > threshold || dz > threshold) {
      Serial.println("GANGGUAN MEDAN MAGNET TERDETEKSI!");
    }
    prevX = x;
    prevY = y;
    prevZ = z;

    String basePath = String("/Dataset/") + dateStr + "/" + timeStr;
    Firebase.RTDB.setInt(&fbdo, basePath + "/Getar", vibrationCount);
    Firebase.RTDB.setInt(&fbdo, basePath + "/Suara", sound);
    Firebase.RTDB.setInt(&fbdo, basePath + "/X", x);
    Firebase.RTDB.setInt(&fbdo, basePath + "/Y", y);
    Firebase.RTDB.setInt(&fbdo, basePath + "/Z", z);

    Serial.printf("Sent to Firebase at %s:\n", timeStr);
    Serial.printf("Getar: %d, Suara: %d, Magneto: (%d, %d, %d)\n", vibrationCount, sound, x, y, z);
    vibrationCount = 0;
  }
}
















