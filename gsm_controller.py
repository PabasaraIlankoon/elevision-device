"""
GSM Controller for Elevision RW-001

SIM800L wiring:
  GPIO14 (Physical Pin 8)  = Pi UART RX → SIM800L TXD
  GPIO15 (Physical Pin 10) = Pi UART TX → SIM800L RXD
  GPIO27 (Physical Pin 13) = RST control → SIM800L RST
  Separate 4V regulated supply → SIM800L VCC
  Common GND → SIM800L GND

IMPORTANT: Never power SIM800L from Pi GPIO pins. Use separate 4V supply.
"""

import serial
import RPi.GPIO as GPIO
import time
import logging

log = logging.getLogger('elevision')


class GSMController:

    def __init__(self, port='/dev/ttyS0', baud=9600, rst_pin=27):
        self.port = port
        self.baud = baud
        self.rst_pin = rst_pin
        self.ser = None
        self._setup_rst_pin()

    def _setup_rst_pin(self):
        try:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            GPIO.setup(self.rst_pin, GPIO.OUT, initial=GPIO.HIGH)
            log.info(f'GSM RST pin ready on GPIO{self.rst_pin} (Physical Pin 13)')
        except Exception as e:
            log.warning(f'GSM RST pin setup error: {e}')

    def hardware_reset(self):
        log.info('Resetting SIM800L...')
        try:
            GPIO.output(self.rst_pin, GPIO.LOW)
            time.sleep(0.2)
            GPIO.output(self.rst_pin, GPIO.HIGH)
            time.sleep(5)
            log.info('SIM800L reset complete')
        except Exception as e:
            log.warning(f'Reset error: {e}')

    def _open_serial(self):
        try:
            if self.ser and self.ser.is_open:
                return True
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baud,
                timeout=2
            )
            return True
        except serial.SerialException as e:
            log.warning(f'Cannot open serial port {self.port}: {e}')
            return False

    def _close_serial(self):
        try:
            if self.ser and self.ser.is_open:
                self.ser.close()
        except Exception:
            pass

    def _send_command(self, command, wait=1):
        try:
            self.ser.flushInput()
            self.ser.write((command + '\r\n').encode('utf-8'))
            time.sleep(wait)
            response = ''
            while self.ser.in_waiting > 0:
                response += self.ser.read(self.ser.in_waiting).decode('utf-8', errors='ignore')
                time.sleep(0.1)
            log.debug(f'CMD: {command} | RESP: {response.strip()}')
            return response
        except Exception as e:
            log.warning(f'Command error: {e}')
            return ''

    def check_module(self):
        result = {'alive': False, 'network': False, 'signal': 0, 'signal_quality': 'No signal'}
        if not self._open_serial():
            return result
        try:
            response = self._send_command('AT', wait=1)
            if 'OK' in response:
                result['alive'] = True
                log.info('SIM800L alive and responding')
            else:
                log.warning('SIM800L not responding')
                return result

            response = self._send_command('AT+CREG?', wait=1)
            if ',1' in response or ',5' in response:
                result['network'] = True
                log.info('SIM800L registered to GSM network')
            else:
                log.warning('SIM800L not registered. Check SIM card.')

            response = self._send_command('AT+CSQ', wait=1)
            if '+CSQ:' in response:
                try:
                    sig = int(response.split(':')[1].strip().split(',')[0])
                    result['signal'] = sig
                    if sig == 0:
                        result['signal_quality'] = 'No signal'
                    elif sig < 5:
                        result['signal_quality'] = 'Very weak'
                    elif sig < 10:
                        result['signal_quality'] = 'Weak'
                    elif sig < 15:
                        result['signal_quality'] = 'Fair'
                    elif sig < 20:
                        result['signal_quality'] = 'Good'
                    else:
                        result['signal_quality'] = 'Excellent'
                    log.info(f'Signal: {sig}/31 ({result["signal_quality"]})')
                except Exception:
                    pass
        finally:
            self._close_serial()
        return result

    def send_sms(self, phone_number, message):
        log.info(f'Sending SMS to {phone_number}...')
        if not self._open_serial():
            log.warning('Cannot open serial port for SMS')
            return False
        try:
            response = self._send_command('AT', wait=1)
            if 'OK' not in response:
                log.warning('SIM800L not responding. Trying hardware reset...')
                self._close_serial()
                self.hardware_reset()
                if not self._open_serial():
                    return False
                response = self._send_command('AT', wait=2)
                if 'OK' not in response:
                    log.error('SIM800L still not responding after reset')
                    return False

            self._send_command('AT+CMGF=1', wait=1)

            response = self._send_command(f'AT+CMGS="{phone_number}"', wait=2)
            if '>' not in response:
                log.warning('Module not ready for message body')
                return False

            self.ser.write((message + '\x1A').encode('utf-8'))
            time.sleep(8)

            response = ''
            timeout = time.time() + 15
            while time.time() < timeout:
                if self.ser.in_waiting > 0:
                    response += self.ser.read(self.ser.in_waiting).decode('utf-8', errors='ignore')
                    if '+CMGS' in response or 'ERROR' in response:
                        break
                time.sleep(0.5)

            if '+CMGS' in response:
                log.info(f'SMS sent successfully to {phone_number}')
                return True
            else:
                log.warning(f'SMS may have failed. Response: {response}')
                return False
        except Exception as e:
            log.error(f'SMS exception: {e}')
            return False
        finally:
            self._close_serial()

    def cleanup(self):
        self._close_serial()
        try:
            GPIO.cleanup()
        except Exception:
            pass
