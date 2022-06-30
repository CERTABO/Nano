import time
import threading
import logging

import bluetooth

from cfg import BTPORT
from utils.bluetoothtool import find_address


class serialreader(threading.Thread):
    def __init__(self, handler, device, kill_thread_event):
        threading.Thread.__init__(self)
        self.device = device
        self.connected = False
        self.handler = handler
        self.uart = None
        self.buf = bytearray()
        self.kill_thread_event = kill_thread_event

    def send_led(self, message: bytes):
        # logging.debug(f'Sending to serial: {message}')
        if self.connected:
            return self.uart.send(message)
            # return self.uart.write(message)
        return None

    def readline(self):
        return self.uart.recv(1024)

    def run(self):
        while True:
            # Check exit command
            if self.kill_thread_event.is_set():
                self.uart.close()
                return

            if not self.connected:
                try:
                    if self.device == 'auto':
                        logging.info(f'Auto-detecting serial port')
                        serialport = find_address()
                    else:
                        serialport = self.device
                        self.device = 'auto'  # If it disconnects after, ignore typed device and try to find new!
                    if serialport is None:
                        logging.info(f'No port found, retrying')
                        time.sleep(1)
                        continue
                    logging.info(f'Opening bt port {serialport}, {BTPORT}')

                    self.uart = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
                    self.uart.connect((serialport, BTPORT))
                    self.connected = True
                except Exception as e:
                    logging.info(f'ERROR: Cannot open bt port {serialport}: {str(e)}')
                    self.connected = False
                    time.sleep(1)
            else:
                try:
                    while True:
                        # Check exit command
                        if self.kill_thread_event.is_set():
                            self.uart.close()
                            return

                        raw_message = self.readline()
                        try:
                            message = raw_message.decode("utf-8")[1:]
                            if len(message.split(" ")) == 320:  # 64*5
                                self.handler(message)
                        except Exception as e:
                            logging.info(f'Exception during message decode: {str(e)}')
                except Exception as e:
                    logging.info(f'Exception during serial communication: {str(e)}')
                    self.connected = False
