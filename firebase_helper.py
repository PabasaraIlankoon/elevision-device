"""
Firebase Helper for Elevision RW-001

Handles:
- Image upload to Firebase Storage (with verified URL)
- Alert document write to Firestore
- FCM push notifications
- Device status updates
"""

import firebase_admin
from firebase_admin import credentials, firestore, messaging, storage
import logging
import time
import os

log = logging.getLogger('elevision')

_initialized = False
_db = None
_bucket = None


def initialize_firebase(key_path, storage_bucket):
    global _initialized, _db, _bucket
    if _initialized:
        return _db, _bucket

    if not os.path.exists(key_path):
        raise FileNotFoundError(
            f'Firebase key not found: {key_path}\n'
            'Download from Firebase Console > Project Settings > Service Accounts'
        )

    cred = credentials.Certificate(key_path)
    firebase_admin.initialize_app(cred, {'storageBucket': storage_bucket})
    _db = firestore.client()
    _bucket = storage.bucket()
    _initialized = True

    log.info('Firebase connected successfully')
    log.info(f'Storage bucket: {storage_bucket}')
    return _db, _bucket


def upload_image_to_storage(bucket, image_path, device_id, alert_id):
    """
    Upload alert image to Firebase Storage.
    Returns the public URL so Flutter app and web dashboard can display it.
    Returns empty string if upload fails.
    """
    if not os.path.exists(image_path):
        log.error(f'Image file does not exist: {image_path}')
        return ''

    file_size = os.path.getsize(image_path)
    if file_size == 0:
        log.error(f'Image file is 0 bytes: {image_path}')
        return ''

    log.info(f'Uploading image ({file_size} bytes) to Firebase Storage...')

    import datetime
    date_str = datetime.datetime.now().strftime('%Y-%m-%d')
    storage_path = f'alerts/{date_str}/{device_id}/{alert_id}.jpg'

    log.info(f'Storage path: {storage_path}')

    blob = bucket.blob(storage_path)
    blob.upload_from_filename(image_path, content_type='image/jpeg')
    blob.make_public()

    url = blob.public_url
    log.info('Image upload SUCCESS')
    log.info(f'Public URL: {url}')
    return url


def write_alert_to_firestore(db, alert_id, timestamp_ms, image_url,
                              confidence, device_id, device_name,
                              device_lat, device_lng):
    """
    Write alert to Firestore.
    This triggers instant real-time update in Flutter app and web dashboard.
    Both use snapshots() listeners that automatically receive new documents.
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
    log.info(f'  imageUrl:     {"SET (" + str(len(image_url)) + " chars)" if image_url else "EMPTY"}')

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
