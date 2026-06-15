"""
LED Controller for Elevision RW-001

LED wiring:
  GPIO17 (Physical Pin 11) → 330Ω resistor → LED long leg (+) → LED short leg (-) → GND (Physical Pin 6)

Behaviour:
  - No elephant: LED is OFF
  - Elephant first appears: LED turns ON INSTANTLY on first detection frame
  - Elephant still visible: LED stays ON solid
  - Elephant gone: LED turns OFF immediately
  - Alert sent to cloud: 3 quick blinks to confirm, then back to solid ON
"""

import RPi.GPIO as GPIO
import time
import logging

log = logging.getLogger('elevision')


class LEDController:

    def __init__(self, pin=17):
        self.pin = pin
        self._is_on = False
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            GPIO.setup(self.pin, GPIO.OUT, initial=GPIO.LOW)
            log.info(f'LED ready on GPIO{self.pin} (Physical Pin 11) — currently OFF')
        except Exception as e:
            log.error(f'LED setup error: {e}')

    def elephant_detected(self):
        """Turn LED ON instantly. Call this on the FIRST detection frame."""
        if not self._is_on:
            try:
                GPIO.output(self.pin, GPIO.HIGH)
                self._is_on = True
                log.info('LED: ON — elephant detected')
            except Exception as e:
                log.debug(f'LED on error: {e}')

    def elephant_gone(self):
        """Turn LED OFF immediately. Call this when elephant leaves frame."""
        if self._is_on:
            try:
                GPIO.output(self.pin, GPIO.LOW)
                self._is_on = False
                log.info('LED: OFF — elephant gone')
            except Exception as e:
                log.debug(f'LED off error: {e}')

    def alert_sent_blink(self):
        """3 quick blinks to confirm alert was sent, then back to solid ON."""
        try:
            for _ in range(3):
                GPIO.output(self.pin, GPIO.LOW)
                time.sleep(0.1)
                GPIO.output(self.pin, GPIO.HIGH)
                time.sleep(0.1)
            GPIO.output(self.pin, GPIO.HIGH)
            self._is_on = True
            log.info('LED: alert confirmation blink done, back to solid ON')
        except Exception as e:
            log.debug(f'LED blink error: {e}')

    def is_on(self):
        return self._is_on

    def cleanup(self):
        try:
            GPIO.output(self.pin, GPIO.LOW)
            GPIO.cleanup()
            self._is_on = False
            log.info('LED cleaned up and GPIO released')
        except Exception:
            pass
