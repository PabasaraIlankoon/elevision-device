"""
Offline Queue for Elevision RW-001
Saves alerts when internet is not available.
Uploads them when internet returns.
"""

import os
import logging
from pathlib import Path

log = logging.getLogger('elevision')
QUEUE_DIR = '/home/pi/elevision/offline_queue'


def save_to_queue(alert_id, timestamp_ms, image_path, confidence,
                  device_id, device_name, device_lat, device_lng):
    os.makedirs(QUEUE_DIR, exist_ok=True)
    qfile = os.path.join(QUEUE_DIR, f'{alert_id}.txt')
    with open(qfile, 'w') as f:
        f.write(f'{timestamp_ms}|{image_path}|{confidence}|'
                f'{device_id}|{device_name}|{device_lat}|{device_lng}')
    log.info(f'Alert saved to offline queue: {alert_id[:8]}')


def process_queue(send_alert_func, has_internet_func):
    if not os.path.exists(QUEUE_DIR):
        return
    files = list(Path(QUEUE_DIR).glob('*.txt'))
    if not files:
        return
    if not has_internet_func():
        log.debug(f'{len(files)} alerts queued — waiting for internet')
        return
    log.info(f'Internet restored — uploading {len(files)} queued alerts')
    for qf in files:
        try:
            parts = qf.read_text().strip().split('|')
            if len(parts) >= 7:
                ts, img, conf, did, dname, lat, lng = parts[:7]
                if os.path.exists(img):
                    send_alert_func(img, float(conf), 1, True)
            qf.unlink()
        except Exception as e:
            log.warning(f'Queue error: {e}')
