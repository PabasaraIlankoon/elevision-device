import os
from dotenv import load_dotenv

load_dotenv('/home/pi/elevision/.env')

FIREBASE_PROJECT_ID       = os.getenv('FIREBASE_PROJECT_ID', 'elevision-606a9')
FIREBASE_STORAGE_BUCKET   = os.getenv('FIREBASE_STORAGE_BUCKET', 'elevision-606a9.firebasestorage.app')
FIREBASE_KEY_PATH         = os.getenv('FIREBASE_KEY_PATH', '/home/pi/elevision/firebase-key.json')

DEVICE_ID   = os.getenv('DEVICE_ID', 'RW-001')
DEVICE_NAME = os.getenv('DEVICE_NAME', 'Palugaswewa Railway Section')
DEVICE_LAT  = float(os.getenv('DEVICE_LAT', '8.0475'))
DEVICE_LNG  = float(os.getenv('DEVICE_LNG', '80.6932'))

CONFIDENCE_THRESHOLD       = float(os.getenv('CONFIDENCE_THRESHOLD', '0.55'))
ALERT_COOLDOWN_SECONDS     = int(os.getenv('ALERT_COOLDOWN_SECONDS', '300'))
CAMERA_INDEX               = int(os.getenv('CAMERA_INDEX', '0'))
DETECTION_INTERVAL_SECONDS = int(os.getenv('DETECTION_INTERVAL_SECONDS', '1'))

MODEL_PATH           = os.getenv('MODEL_PATH', '/home/pi/elevision/models/elephant_model.onnx')
EMERGENCY_SMS_NUMBER = os.getenv('EMERGENCY_SMS_NUMBER', '+94119')

LED_PIN     = int(os.getenv('LED_PIN', '17'))
GSM_TX_PIN  = int(os.getenv('GSM_TX_PIN', '15'))
GSM_RX_PIN  = int(os.getenv('GSM_RX_PIN', '14'))
GSM_RST_PIN = int(os.getenv('GSM_RST_PIN', '27'))
GSM_PORT    = os.getenv('GSM_PORT', '/dev/ttyS0')
GSM_BAUD    = int(os.getenv('GSM_BAUD', '9600'))
