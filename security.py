"""
ELEVISION RW-001 — Elephant Guard System
==========================================
Fixes applied:
1. Camera auto-detection (index 1 on this Pi)
2. Real-time inference worker (no frame backlog)
3. SMS alert via GSM
4. Firebase Storage image upload
5. Full FCM push notification pipeline
6. Offline queue support
7. Stable loop timing
"""

import cv2
import time
import datetime
import uuid
import os
import sys
import socket
import logging
import threading

os.environ['ORT_LOGGING_LEVEL'] = '3'

os.makedirs('/home/pi/elevision/logs', exist_ok=True)
os.makedirs('/home/pi/elevision/alerts_images', exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler('/home/pi/elevision/logs/elevision.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger('elevision')

sys.path.insert(0, '/home/pi/elevision')

try:
    from detection_config import (
        FIREBASE_PROJECT_ID, FIREBASE_STORAGE_BUCKET, FIREBASE_KEY_PATH,
        DEVICE_ID, DEVICE_NAME, DEVICE_LAT, DEVICE_LNG,
        CONFIDENCE_THRESHOLD, ALERT_COOLDOWN_SECONDS,
        CAMERA_INDEX, DETECTION_INTERVAL_SECONDS,
        MODEL_PATH, EMERGENCY_SMS_NUMBER,
        LED_PIN, GSM_TX_PIN, GSM_RX_PIN, GSM_RST_PIN, GSM_PORT, GSM_BAUD
    )
    from led_controller import LEDController
    from gsm_controller import GSMController
    from firebase_helper import (
        initialize_firebase, upload_image_to_storage,
        write_alert_to_firestore, send_push_notification,
        send_topic_notification, get_fcm_token,
        update_device_status, is_system_armed
    )
    from offline_queue import save_to_queue, process_queue
    from onnx_detector import ONNXElephantDetector
except ImportError as e:
    print(f'ERROR loading module: {e}')
    sys.exit(1)


# ---------------- INTERNET CHECK ----------------
def has_internet():
    try:
        socket.create_connection(('8.8.8.8', 53), timeout=3)
        return True
    except OSError:
        return False


# ---------------- CAMERA AUTO-DETECT ----------------
def open_camera():
    # Try index 1 first (confirmed working on this Pi), then fallback
    for i in [1, 0, 2, 3]:
        cap = cv2.VideoCapture(i, cv2.CAP_V4L2)
        if cap.isOpened():
            log.info(f'Camera opened at index {i}')
            return cap
        cap.release()
    raise RuntimeError('No working camera found')


# ---------------- INFERENCE WORKER ----------------
class InferenceWorker:
    """
    Runs ONNX inference on a background thread.
    Always processes the LATEST frame — no queue backlog.
    LED response is near-instant because main loop is never blocked.
    """
    def __init__(self, detector):
        self.detector = detector
        self.latest_frame = None
        self.latest_result = None
        self.lock = threading.Lock()
        self.running = True
        self.thread = threading.Thread(target=self._worker, daemon=True)
        self.thread.start()
        log.info('Inference worker started (real-time mode)')

    def _worker(self):
        while self.running:
            with self.lock:
                frame = self.latest_frame
                self.latest_frame = None

            if frame is None:
                time.sleep(0.01)
                continue

            try:
                result = self.detector.detect(frame)
                with self.lock:
                    self.latest_result = result
            except Exception as e:
                log.error(f'Inference error: {e}')

    def submit_frame(self, frame):
        with self.lock:
            self.latest_frame = frame

    def get_result(self):
        with self.lock:
            return self.latest_result

    def stop(self):
        self.running = False


# ---------------- ALERT PIPELINE ----------------
def run_alert_pipeline(image_path, confidence_score, alert_id, gsm, db, bucket):
    now = datetime.datetime.now()
    timestamp_ms = int(now.timestamp() * 1000)
    time_str = now.strftime('%I:%M %p')

    log.info('─' * 50)
    log.info('ALERT PIPELINE STARTING')
    log.info(f'Confidence: {confidence_score:.0%}')
    log.info(f'Alert ID:   {alert_id[:8]}')
    log.info('─' * 50)

    # [A] SMS — send DIRECTLY (not in a thread) to avoid serial port conflicts
    sms_text = (
        f'ELEPHANT ALERT from Elevision {DEVICE_ID}. '
        f'Detected at {DEVICE_NAME} at {time_str}. '
        f'Confidence: {confidence_score:.0%}. '
        f'GPS: {DEVICE_LAT}, {DEVICE_LNG}. '
        f'Check app for image.'
    )
    log.info('[A] Sending SMS...')
    ok = gsm.send_sms(EMERGENCY_SMS_NUMBER, sms_text)
    log.info('[A] SMS SENT' if ok else '[A] SMS FAILED')

    if not has_internet():
        log.warning('No internet — SMS sent, alert queued for later')
        save_to_queue(
            alert_id=alert_id,
            timestamp_ms=timestamp_ms,
            image_path=image_path,
            confidence=confidence_score,
            device_id=DEVICE_ID,
            device_name=DEVICE_NAME,
            device_lat=DEVICE_LAT,
            device_lng=DEVICE_LNG
        )
        return

    log.info('Internet OK — running cloud pipeline')

    # [B] Upload image
    image_url = ''
    log.info('[B] Uploading image to Firebase Storage...')
    try:
        image_url = upload_image_to_storage(
            bucket=bucket,
            image_path=image_path,
            device_id=DEVICE_ID,
            alert_id=alert_id
        )
        if image_url:
            log.info(f'[B] Upload SUCCESS — {image_url[:80]}')
        else:
            log.error('[B] Upload returned empty URL')
    except Exception as e:
        log.error(f'[B] Upload FAILED: {type(e).__name__}: {e}')

    # [C] Firestore
    log.info('[C] Writing alert to Firestore...')
    try:
        write_alert_to_firestore(
            db=db,
            alert_id=alert_id,
            timestamp_ms=timestamp_ms,
            image_url=image_url,
            confidence=confidence_score,
            device_id=DEVICE_ID,
            device_name=DEVICE_NAME,
            device_lat=DEVICE_LAT,
            device_lng=DEVICE_LNG
        )
        log.info('[C] Firestore SUCCESS')
    except Exception as e:
        log.error(f'[C] Firestore FAILED: {e}')

    # [D] FCM push
    log.info('[D] Sending FCM push notification...')
    fcm_token = get_fcm_token(db)
    if fcm_token:
        try:
            send_push_notification(
                fcm_token=fcm_token,
                alert_id=alert_id,
                device_id=DEVICE_ID,
                device_name=DEVICE_NAME,
                confidence=confidence_score,
                device_lat=DEVICE_LAT,
                device_lng=DEVICE_LNG,
                timestamp_ms=timestamp_ms,
                time_str=time_str
            )
            log.info('[D] Push notification SENT')
        except Exception as e:
            log.error(f'[D] Push FAILED: {e}')
    else:
        log.warning('[D] No FCM token — open Flutter app to register')

    # [E] Web dashboard
    log.info('[E] Sending web dashboard notification...')
    try:
        send_topic_notification(alert_id, DEVICE_ID, DEVICE_NAME, confidence_score)
        log.info('[E] Web notification SENT')
    except Exception as e:
        log.warning(f'[E] Web notification: {e}')

    log.info('─' * 50)
    log.info(f'ALERT COMPLETE — ID: {alert_id[:8]}')
    log.info('─' * 50)

    # [A] SMS — always attempted regardless of internet
    sms_text = (
        f'ELEPHANT ALERT from Elevision {DEVICE_ID}. '
        f'Detected at {DEVICE_NAME} at {time_str}. '
        f'Confidence: {confidence_score:.0%}. '
        f'GPS: {DEVICE_LAT}, {DEVICE_LNG}. '
        f'Check app for image.'
    )

    def _sms():
        log.info('[A] Sending SMS...')
        ok = gsm.send_sms(EMERGENCY_SMS_NUMBER, sms_text)
        log.info('[A] SMS SENT' if ok else '[A] SMS FAILED')

    threading.Thread(target=_sms, daemon=True).start()

    if not has_internet():
        log.warning('No internet — SMS sent, alert queued for later')
        save_to_queue(
            alert_id=alert_id,
            timestamp_ms=timestamp_ms,
            image_path=image_path,
            confidence=confidence_score,
            device_id=DEVICE_ID,
            device_name=DEVICE_NAME,
            device_lat=DEVICE_LAT,
            device_lng=DEVICE_LNG
        )
        return

    log.info('Internet OK — running cloud pipeline')

    # [B] Upload image to Firebase Storage
    image_url = ''
    log.info('[B] Uploading image to Firebase Storage...')
    try:
        image_url = upload_image_to_storage(
            bucket=bucket,
            image_path=image_path,
            device_id=DEVICE_ID,
            alert_id=alert_id
        )
        if image_url:
            log.info(f'[B] Upload SUCCESS — {image_url[:80]}')
        else:
            log.error('[B] Upload returned empty URL')
    except Exception as e:
        log.error(f'[B] Upload FAILED: {type(e).__name__}: {e}')

    # [C] Write alert to Firestore
    log.info('[C] Writing alert to Firestore...')
    try:
        write_alert_to_firestore(
            db=db,
            alert_id=alert_id,
            timestamp_ms=timestamp_ms,
            image_url=image_url,
            confidence=confidence_score,
            device_id=DEVICE_ID,
            device_name=DEVICE_NAME,
            device_lat=DEVICE_LAT,
            device_lng=DEVICE_LNG
        )
        log.info('[C] Firestore SUCCESS')
    except Exception as e:
        log.error(f'[C] Firestore FAILED: {e}')

    # [D] FCM push notification
    log.info('[D] Sending FCM push notification...')
    fcm_token = get_fcm_token(db)
    if fcm_token:
        try:
            send_push_notification(
                fcm_token=fcm_token,
                alert_id=alert_id,
                device_id=DEVICE_ID,
                device_name=DEVICE_NAME,
                confidence=confidence_score,
                device_lat=DEVICE_LAT,
                device_lng=DEVICE_LNG,
                timestamp_ms=timestamp_ms,
                time_str=time_str
            )
            log.info('[D] Push notification SENT')
        except Exception as e:
            log.error(f'[D] Push FAILED: {e}')
    else:
        log.warning('[D] No FCM token — open Flutter app to register')

    # [E] Web dashboard topic notification
    log.info('[E] Sending web dashboard notification...')
    try:
        send_topic_notification(alert_id, DEVICE_ID, DEVICE_NAME, confidence_score)
        log.info('[E] Web notification SENT')
    except Exception as e:
        log.warning(f'[E] Web notification: {e}')

    log.info('─' * 50)
    log.info(f'ALERT COMPLETE — ID: {alert_id[:8]}')
    log.info('─' * 50)


# ---------------- MAIN ----------------
def main():
    log.info('=' * 60)
    log.info('  ELEVISION RW-001 — Elephant Guard System')
    log.info('=' * 60)
    log.info(f'Device:     {DEVICE_ID} — {DEVICE_NAME}')
    log.info(f'GPS:        {DEVICE_LAT}, {DEVICE_LNG}')
    log.info(f'Confidence: {CONFIDENCE_THRESHOLD:.0%}')
    log.info(f'Cooldown:   {ALERT_COOLDOWN_SECONDS}s')
    log.info(f'Bucket:     {FIREBASE_STORAGE_BUCKET}')
    log.info('=' * 60)

    log.info('Initializing LED...')
    led = LEDController(pin=LED_PIN)

    log.info('Initializing GSM...')
    gsm = GSMController(port=GSM_PORT, baud=GSM_BAUD, rst_pin=GSM_RST_PIN)
    gsm_status = gsm.check_module()
    if gsm_status['alive']:
        log.info(f'GSM ready — Signal:{gsm_status["signal"]}/31 ({gsm_status["signal_quality"]})')
    else:
        log.warning('GSM not responding — SMS alerts will fail')

    log.info('Connecting to Firebase...')
    try:
        db, bucket = initialize_firebase(FIREBASE_KEY_PATH, FIREBASE_STORAGE_BUCKET)
    except Exception as e:
        log.error(f'Firebase failed: {e}')
        led.cleanup()
        gsm.cleanup()
        sys.exit(1)

    log.info('Loading elephant detection model...')
    if not os.path.exists(MODEL_PATH):
        log.error(f'Model not found: {MODEL_PATH}')
        led.cleanup()
        gsm.cleanup()
        sys.exit(1)

    try:
        model = ONNXElephantDetector(MODEL_PATH, CONFIDENCE_THRESHOLD)
        model.warmup()
        mb = os.path.getsize(MODEL_PATH) / 1024 / 1024
        log.info(f'Model ready ({mb:.1f} MB)')
    except Exception as e:
        log.error(f'Model load failed: {e}')
        led.cleanup()
        gsm.cleanup()
        sys.exit(1)

    log.info('Marking RW-001 as ONLINE...')
    update_device_status(db, DEVICE_ID, DEVICE_NAME, DEVICE_LAT, DEVICE_LNG, 'online')

    log.info('Opening camera...')
    try:
        camera = open_camera()
    except RuntimeError as e:
        log.error(str(e))
        update_device_status(db, DEVICE_ID, DEVICE_NAME, DEVICE_LAT, DEVICE_LNG, 'offline')
        led.cleanup()
        gsm.cleanup()
        sys.exit(1)

    camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    w = int(camera.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(camera.get(cv2.CAP_PROP_FRAME_HEIGHT))
    log.info(f'Camera ready at {w}x{h}')

    worker = InferenceWorker(model)

    elephant_present = False
    consecutive = 0
    best_confidence = 0.0
    last_alert = 0
    frames_since = 0
    frame_count = 0
    last_status_update = time.time()
    STATUS_INTERVAL = 60
    GONE_THRESHOLD = 3

    log.info('=' * 60)
    log.info('DETECTION RUNNING — LED responds near-instantly')
    log.info(f'Watching: {DEVICE_NAME}')
    log.info('Press Ctrl+C to stop')
    log.info('=' * 60)

    try:
        while True:
            loop_start = time.time()

            # Periodic status update + offline queue flush
            now = time.time()
            if now - last_status_update >= STATUS_INTERVAL:
                update_device_status(db, DEVICE_ID, DEVICE_NAME, DEVICE_LAT, DEVICE_LNG, 'online')
                process_queue(
                    lambda img, conf, aid: run_alert_pipeline(img, conf, aid, gsm, db, bucket),
                    has_internet
                )
                last_status_update = now

            # Check armed status every 30 frames
            if frame_count % 30 == 0 and frame_count > 0:
                if not is_system_armed(db):
                    log.info('DISARMED from app')
                    elephant_present = False
                    led.elephant_gone()
                    consecutive = 0
                    time.sleep(10)
                    frame_count += 1
                    continue

            # Capture frame
            ret, frame = camera.read()
            if not ret:
                log.warning('Camera read failed')
                time.sleep(0.5)
                continue

            frame_count += 1
            worker.submit_frame(frame.copy())
            result = worker.get_result()

            if result is not None:
                if result['detected']:
                    consecutive += 1
                    frames_since = 0
                    best_confidence = max(best_confidence, result['confidence'])

                    # Turn LED ON on first detection
                    if not elephant_present:
                        elephant_present = True
                        led.elephant_detected()
                        log.info(
                            f'ELEPHANT DETECTED → LED ON — '
                            f'Conf:{best_confidence:.0%} — Frame:{frame_count}'
                        )
                    else:
                        log.info(
                            f'Elephant visible — '
                            f'Conf:{result["confidence"]:.0%} — '
                            f'Frame:{frame_count} — Consecutive:{consecutive}'
                        )

                    # Send full alert after 2 consecutive detections
                    if consecutive == 2:
                        cooldown_left = ALERT_COOLDOWN_SECONDS - (now - last_alert)
                        if cooldown_left > 0 and last_alert > 0:
                            log.info(f'In cooldown — {cooldown_left:.0f}s remaining')
                        else:
                            ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
                            img_path = (
                                f'/home/pi/elevision/alerts_images/'
                                f'alert_{DEVICE_ID}_{ts}.jpg'
                            )
                            saved = cv2.imwrite(img_path, frame)
                            if saved:
                                size = os.path.getsize(img_path)
                                log.info(f'Alert image saved: {img_path} ({size} bytes)')
                            else:
                                log.error(f'Image save FAILED: {img_path}')

                            alert_id = str(uuid.uuid4())
                            threading.Thread(
                                target=run_alert_pipeline,
                                args=(img_path, best_confidence, alert_id, gsm, db, bucket),
                                daemon=True
                            ).start()
                            last_alert = now

                else:
                    frames_since += 1

                    if elephant_present and frames_since >= GONE_THRESHOLD:
                        elephant_present = False
                        consecutive = 0
                        best_confidence = 0.0
                        led.elephant_gone()
                        log.info(f'Elephant GONE → LED OFF — Frame:{frame_count}')
                    elif not elephant_present:
                        consecutive = 0
                        best_confidence = 0.0

            # ~30 FPS loop, stable on Pi
            elapsed = time.time() - loop_start
            sleep_time = max(0.0, 0.03 - elapsed)
            if sleep_time > 0:
                time.sleep(sleep_time)

    except KeyboardInterrupt:
        log.info('Stopped by user')

    except Exception as e:
        log.error(f'Fatal error: {e}')
        import traceback
        log.error(traceback.format_exc())

    finally:
        log.info('Shutting down...')
        worker.stop()
        camera.release()
        led.elephant_gone()
        led.cleanup()
        gsm.cleanup()
        update_device_status(db, DEVICE_ID, DEVICE_NAME, DEVICE_LAT, DEVICE_LNG, 'offline')
        log.info('Shutdown complete')


if __name__ == '__main__':
    main()
