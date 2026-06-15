"""
Firebase Helper for Elevision RW-001

Handles:
- Image upload to Cloudinary (free, no credit card required)
- Alert document write to Firestore
- FCM push notifications
- Device status updates

Change log:
- Replaced Firebase Storage upload with Cloudinary
- All other functions (Firestore, FCM, device status) unchanged
- Rest of pipeline (security.py, web dashboard, Flutter app)
  consumes the URL the same way — no other changes needed
"""

import firebase_admin
from firebase_admin import credentials, firestore, messaging
import cloudinary
import cloudinary.uploader
import logging
import time
import os

log = logging.getLogger('elevision')

_initialized = False
_db = None


def initialize_firebase(key_path, storage_bucket):
    """
    Initialize Firebase (Firestore + FCM) and Cloudinary.
    storage_bucket param kept for compatibility — no longer used for uploads.
    """
    global _initialized, _db

    if _initialized:
        return _db, None  # second return value (bucket) no longer used

    # --- Firebase init ---
    if not os.path.exists(key_path):
        raise FileNotFoundError(
            f'Firebase key not found: {key_path}\n'
            'Download from Firebase Console > Project Settings > Service Accounts'
        )

    cred = credentials.Certificate(key_path)
    firebase_admin.initialize_app(cred, {'storageBucket': storage_bucket})
    _db = firestore.client()
    _initialized = True
    log.info('Firebase (Firestore + FCM) connected successfully')

    # --- Cloudinary init ---
    cloud_name  = os.getenv('CLOUDINARY_CLOUD_NAME')
    api_key     = os.getenv('CLOUDINARY_API_KEY')
    api_secret  = os.getenv('CLOUDINARY_API_SECRET')

    if not all([cloud_name, api_key, api_secret]):
        raise EnvironmentError(
            'Cloudinary credentials missing from .env\n'
            'Required: CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET'
        )

    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        secure=True
    )
    log.info(f'Cloudinary connected — cloud: {cloud_name}')

    return _db, None  # None = no bucket object needed anymore


def upload_image_to_storage(bucket, image_path, device_id, alert_id):
    """
    Upload alert image to Cloudinary.
    Returns the public HTTPS URL so Flutter app and web dashboard can display it.
    Returns empty string if upload fails.

    Note: 'bucket' param kept for compatibility with security.py call signature
    — it is not used here.
    """
    if not os.path.exists(image_path):
        log.error(f'Image file does not exist: {image_path}')
        return ''

    file_size = os.path.getsize(image_path)
    if file_size == 0:
        log.error(f'Image file is 0 bytes: {image_path}')
        return ''

    log.info(f'Uploading image ({file_size} bytes) to Cloudinary...')

    public_id = f'elevision/alerts/{device_id}/{alert_id}'
    log.info(f'Cloudinary public_id: {public_id}')

    try:
        result = cloudinary.uploader.upload(
            image_path,
            public_id=public_id,
            resource_type='image',
            format='jpg',
            overwrite=True
        )
        url = result.get('secure_url', '')
        if url:
            log.info('Cloudinary upload SUCCESS')
            log.info(f'Public URL: {url}')
            return url
        else:
            log.error('Cloudinary upload returned no URL')
            return ''
    except Exception as e:
        log.error(f'Cloudinary upload FAILED: {type(e).__name__}: {e}')
        return ''


def write_alert_to_firestore(db, alert_id, timestamp_ms, image_url,
                              confidence, device_id, device_name,
                              device_lat, device_lng):
    """
    Write alert to Firestore.
    Triggers instant real-time update in Flutter app and web dashboard.
    """
    data = {
        'timestampMs': timestamp_ms,
        'imageUrl': image_url,
        'confidence': float(confidence),
        'deviceId': device_id,
        'locationName': device_name,
        'latitude': float(device_lat),
        'longitude': float(device_lng),
        'status': 'new',
    }

    log.info('Writing alert to Firestore...')
    log.info(f'  alertId:      {alert_id[:8]}...')
    log.info(f'  confidence:   {confidence:.0%}')
    log.info(f'  imageUrl:     {"SET (" + str(len(image_url)) + " chars)" if image_url else "EMPTY — image upload may have failed"}')

    db.collection('alerts').document(alert_id).set(data)

    log.info('Firestore write SUCCESS')
    log.info('Flutter app StreamBuilder updating now')
    log.info('Web dashboard onSnapshot updating now')


def send_push_notification(fcm_token, alert_id, device_id, device_name,
                            confidence, device_lat, device_lng,
                            timestamp_ms, time_str):
    """Send FCM push notification to Flutter mobile app."""
    message = messaging.Message(
        notification=messaging.Notification(
            title='Elephant Alert!',
            body=f'Elephant at {device_name} at {time_str}',
        ),
        data={
            'alertId': alert_id,
            'deviceId': device_id,
            'confidence': str(round(confidence * 100)),
            'locationName': device_name,
            'latitude': str(device_lat),
            'longitude': str(device_lng),
            'timestamp': str(timestamp_ms),
        },
        android=messaging.AndroidConfig(
            priority='high',
            notification=messaging.AndroidNotification(
                channel_id='security_alerts',
                sound='default',
                icon='@mipmap/ic_launcher',
            ),
        ),
        token=fcm_token,
    )
    response = messaging.send(message)
    log.info(f'FCM push notification sent. Response: {response}')
    return response


def send_topic_notification(alert_id, device_id, device_name, confidence):
    """Send FCM topic notification to web dashboard."""
    message = messaging.Message(
        notification=messaging.Notification(
            title='Elephant Alert!',
            body=f'Elephant at {device_name} — {confidence:.0%}',
        ),
        data={
            'alertId': alert_id,
            'deviceId': device_id,
            'confidence': str(round(confidence * 100)),
            'locationName': device_name,
        },
        topic='elephant_alerts',
    )
    messaging.send(message)
    log.info('FCM topic notification sent to web dashboard')


def get_fcm_token(db):
    """Read Flutter app FCM token from Firestore."""
    try:
        doc = db.collection('system').document('device_tokens').get()
        if doc.exists:
            token = doc.to_dict().get('fcmToken')
            if token:
                log.info(f'FCM token found: {token[:30]}...')
                return token
        log.warning('No FCM token in Firestore')
        log.warning('Open Flutter app on phone to register the token')
    except Exception as e:
        log.warning(f'Could not read FCM token: {e}')
    return None


def update_device_status(db, device_id, device_name, lat, lng, status='online'):
    """Update device online/offline status in Firestore."""
    try:
        db.collection('system').document('devices').set({
            f'{device_id}_status': status,
            f'{device_id}_lat': lat,
            f'{device_id}_lng': lng,
            f'{device_id}_name': device_name,
            f'{device_id}_last_seen': int(time.time() * 1000),
        }, merge=True)
        log.info(f'Device status: {device_id} is {status}')
    except Exception as e:
        log.warning(f'Could not update device status: {e}')


def is_system_armed(db):
    """Check if system is armed from Flutter app. Defaults to True."""
    try:
        doc = db.collection('system').document('status').get()
        if doc.exists:
            return doc.to_dict().get('armed', True)
        return True
    except Exception:
        return True
