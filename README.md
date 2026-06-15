# elevision-device 🐘

> Raspberry Pi edge detection unit for the **Elevision** wildlife early warning system.
> Detects elephants in real time using a custom ONNX model, sends SMS alerts via GSM,
> uploads evidence images to Cloudinary, and writes structured alerts to Firestore —
> instantly visible on the Flutter mobile app and Next.js web dashboard.

---

## What it does

When an elephant is detected for 2 consecutive frames the system runs a full alert pipeline:

```
[A] SMS  →  SIM800L GSM module sends immediate text to the emergency number
[B] Image →  Captured frame uploaded to Cloudinary, returns a public HTTPS URL
[C] Alert →  Firestore document written with imageUrl, confidence, GPS, timestamp
[D] Push  →  FCM notification sent to Flutter mobile app
[E] Web   →  FCM topic notification triggers real-time update on web dashboard
```

If internet is unavailable, SMS still fires and the alert is saved to an offline queue and retried automatically when connectivity is restored.

---

## Related repositories

| Repo | Description |
|---|---|
| [`elevision-device`](https://github.com/PabasaraIlankoon/elevision-device) | This repo — Raspberry Pi detection unit |
| [`elevision-web`](https://github.com/PabasaraIlankoon/elevision-web) | Next.js web dashboard |
| [`elevision-app`](https://github.com/PabasaraIlankoon/elevision-app) | Flutter mobile app |

---

## Hardware

| Component | Details |
|---|---|
| Board | Raspberry Pi 4 (aarch64, Debian Bookworm) |
| Camera | USB or CSI camera (auto-detected at indices 1, 0, 2, 3) |
| GSM module | SIM800L — GPIO14 (RX), GPIO15 (TX), GPIO27 (RST) |
| LED indicator | GPIO17 — ON when elephant present |
| Power | Pi via USB-C, SIM800L via separate 4V regulated supply |

---

## File structure

```
elevision/
├── security.py           # main entry point — camera loop, inference, alert pipeline
├── detection_config.py   # all config constants loaded from .env
├── firebase_helper.py    # Cloudinary upload + Firestore writes + FCM notifications
├── gsm_controller.py     # SIM800L serial driver (AT commands)
├── led_controller.py     # GPIO LED control
├── onnx_detector.py      # ONNX model wrapper — preprocessing + inference + parsing
├── offline_queue.py      # persists alerts to disk when offline, retries later
├── elevision.service     # systemd service file — auto-starts on boot
├── requirements.txt      # Python dependencies
├── .env.example          # environment variable template (copy to .env and fill in)
└── .gitignore
```

> `firebase-key.json`, `.env`, `models/`, `alerts_images/`, and `logs/` are not committed.

---

## Setup

### 1. Clone and create virtual environment

```bash
git clone https://github.com/PabasaraIlankoon/elevision-device.git /home/pi/elevision
cd /home/pi/elevision
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment variables

```bash
cp .env.example .env
nano .env
```

Fill in all values — see the environment variables table below.

### 3. Add Firebase service account key

Download `firebase-key.json` from:
**Firebase Console → Project Settings → Service Accounts → Generate new private key**

Place it at `/home/pi/elevision/firebase-key.json`.

### 4. Add the ONNX model

Place your trained model at:
```
/home/pi/elevision/models/elephant_model.onnx
```

> The model is not committed to Git due to its size. Back it up to Google Drive after every training run.

### 5. Create required directories

```bash
mkdir -p /home/pi/elevision/logs
mkdir -p /home/pi/elevision/alerts_images
```

### 6. Install the systemd service

```bash
sudo cp elevision.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable elevision
sudo systemctl start elevision
```

The system will now start automatically on every boot.

---

## Environment variables

| Variable | Description | Default |
|---|---|---|
| `FIREBASE_PROJECT_ID` | Firebase project ID | `elevision-606a9` |
| `FIREBASE_KEY_PATH` | Path to service account key | `/home/pi/elevision/firebase-key.json` |
| `DEVICE_ID` | Unique device identifier | `RW-001` |
| `DEVICE_NAME` | Human readable location name | `Palugaswewa Railway Section` |
| `DEVICE_LAT` | GPS latitude | `8.0475` |
| `DEVICE_LNG` | GPS longitude | `80.6932` |
| `CONFIDENCE_THRESHOLD` | Minimum detection confidence (0–1) | `0.55` |
| `ALERT_COOLDOWN_SECONDS` | Minimum seconds between alerts | `300` |
| `CAMERA_INDEX` | OpenCV camera index | `0` |
| `MODEL_PATH` | Path to ONNX model | `/home/pi/elevision/models/elephant_model.onnx` |
| `EMERGENCY_SMS_NUMBER` | SMS recipient (international format) | `+94XXXXXXXXX` |
| `CLOUDINARY_CLOUD_NAME` | Cloudinary cloud name | — |
| `CLOUDINARY_API_KEY` | Cloudinary API key | — |
| `CLOUDINARY_API_SECRET` | Cloudinary API secret | — |
| `GSM_PORT` | Serial port for SIM800L | `/dev/ttyS0` |
| `GSM_BAUD` | GSM baud rate | `9600` |
| `GSM_RST_PIN` | GPIO BCM pin for GSM reset | `27` |
| `LED_PIN` | GPIO BCM pin for LED | `17` |

---

## Running manually (for testing)

Stop the service first, then run manually so you can see output directly:

```bash
sudo systemctl stop elevision
cd /home/pi/elevision
source venv/bin/activate
python3 security.py
```

Watch live logs in a second terminal:

```bash
tail -f /home/pi/elevision/logs/elevision.log
```

When done testing, hand back to systemd:

```bash
sudo systemctl start elevision
```

---

## Useful commands

```bash
# check service status
sudo systemctl status elevision

# restart after a code change
sudo systemctl restart elevision

# stop the service
sudo systemctl stop elevision

# view live logs
tail -f logs/elevision.log

# view last 100 log lines
tail -100 logs/elevision.log

# check GSM signal (run while service is stopped)
source venv/bin/activate
python3 -c "from gsm_controller import GSMController; g = GSMController(); print(g.check_module())"
```

---

## Firestore alert document structure

Each detected elephant writes a document to the `alerts` collection:

```json
{
  "timestampMs": 1781542891083,
  "imageUrl": "https://res.cloudinary.com/...",
  "confidence": 0.928,
  "deviceId": "RW-001",
  "locationName": "Palugaswewa Railway Section",
  "latitude": 8.0475,
  "longitude": 80.6932,
  "status": "new"
}
```

---

## Third-party services

| Service | Purpose | Free tier |
|---|---|---|
| [Firebase Firestore](https://firebase.google.com) | Real-time alert database | 1GB storage, 50k reads/day |
| [Firebase FCM](https://firebase.google.com) | Push notifications | Free |
| [Cloudinary](https://cloudinary.com) | Alert image hosting | 25GB storage |

---

## Project context

This device is part of **Elevision** — an elephant detection and early warning system developed as a final year Individual Design Project (IDP). The system aims to reduce human-elephant conflict along railway sections in Sri Lanka by alerting railway operators and nearby communities in real time.

---

## License

Academic project — all rights reserved.
