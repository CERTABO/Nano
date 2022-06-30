import multiprocessing
import queue
import threading
import time
from collections import deque

import serial
from serial.tools.list_ports import comports

from utils.logger import cfg, get_logger

QUEUE_TO_USBTOOL = queue.Queue(maxsize=64)
QUEUE_FROM_USBTOOL = queue.Queue(maxsize=64)


log = get_logger()


def _usbtool(address_chessboard, queue_to_usbtool, queue_from_usbtool, buffer_ms=750):
    log.debug("Starting Usbtool")
    log.debug(f"Usbtool buffer = {buffer_ms}ms")

    socket = None
    socket_ok = False
    first_connection = True

    time_last_message_to_board = 0
    buffer = buffer_ms / 1000
    message_to_board = deque(maxlen=1)

    message_from_board = ""
    last_reading_time = time.time()

    # pylint: disable=too-many-nested-blocks
    try:
        while True:
            time.sleep(0.001)

            # Try to (re)connect to board
            if not socket_ok:
                try:
                    if not first_connection:
                        socket.close()
                        address_chessboard = (
                            find_address()
                            if cfg.args.usbport is None
                            else cfg.args.usbport
                        )
                        if address_chessboard is None:
                            time.sleep(0.5)
                            continue

                    socket = serial.Serial(address_chessboard, 38400, timeout=2.5)

                # pylint: disable=broad-except
                except Exception as exc:
                    # pylint: enable=broad-except
                    log.warning(
                        f"Failed to (re)connect to port {address_chessboard}: {exc}"
                    )
                    time.sleep(1)
                    continue

                else:
                    socket_ok = True
                    if first_connection:
                        first_connection = False

            # Store message to board
            try:
                new_message = queue_to_usbtool.get_nowait()
                # Kill command
                if new_message is ...:
                    break
                message_to_board.append(new_message)
            except queue.Empty:
                pass

            # Send message to board
            if message_to_board and time.time() >= time_last_message_to_board + buffer:
                data = message_to_board.pop()
                try:
                    socket.reset_output_buffer()
                    socket.write(data)
                # pylint: disable=broad-except
                except Exception as exc:
                    # pylint: enable=broad-except
                    log.warning(f"Could not write to serial port {exc}")
                    socket_ok = False
                    continue
                else:  # No Exception
                    time_last_message_to_board = time.time()
                    if cfg.DEBUG_LED:
                        log.debug(f"Sending to board - {list(data)}")

            # Read messages from board
            try:
                while socket.inWaiting():
                    char = socket.read().decode("ISO-8859-1")

                    # Look for newline
                    if char != "\n":
                        message_from_board += char
                    else:
                        message_from_board = message_from_board[
                            :-2
                        ]  # Remove trailing ' /r'
                        if len(message_from_board.split(" ")) == 320:  # 64*5
                            queue_from_usbtool.put(message_from_board)

                        message_from_board = ""
                        socket.reset_input_buffer()
                        if cfg.DEBUG_READING:
                            new_reading_time = time.time()
                            diff_reading_time = (
                                new_reading_time - last_reading_time
                            ) * 1000
                            log.debug(f"Got reading in {diff_reading_time:.0f}ms")
                            last_reading_time = new_reading_time

            # pylint: disable=broad-except
            except Exception as exc:
                # pylint: enable=broad-except
                log.warning(f"Could not read from serial port: {exc}")
                socket_ok = False

    except KeyboardInterrupt:
        pass
    finally:
        log.debug("Quitting usbtool")
        if socket is not None:
            wait_time = buffer - (time.time() - time_last_message_to_board)
            if wait_time > 0:
                time.sleep(wait_time)
            socket.write(bytes([0, 0, 0, 0, 0, 0, 0, 0]))
            socket.close()
    # pylint: enable=too-many-nested-blocks


def start_usbtool(address_chessboard, buffer_ms=750, separate_process=False):

    global QUEUE_TO_USBTOOL
    global QUEUE_FROM_USBTOOL

    if separate_process:
        log.debug("Launching Usbtool in separate process")
        QUEUE_FROM_USBTOOL = multiprocessing.Queue(maxsize=64)
        QUEUE_TO_USBTOOL = multiprocessing.Queue(maxsize=64)
        thread = multiprocessing.Process(
            target=_usbtool,
            args=(address_chessboard, QUEUE_TO_USBTOOL, QUEUE_FROM_USBTOOL, buffer_ms),
            daemon=True,
        )
        thread.start()

    else:
        log.debug("Launching Usbtool in separate thread")
        thread = threading.Thread(
            target=_usbtool,
            args=(address_chessboard, QUEUE_TO_USBTOOL, QUEUE_FROM_USBTOOL, buffer_ms),
            daemon=True,
        )
        thread.start()

    # Override kill to send ellipsis message
    thread.kill = lambda: QUEUE_TO_USBTOOL.put_nowait(...)
    return thread


def find_address(
    strict=cfg.args.port_not_strict,
    test_address=None,
):
    """
    Method to find Certabo Chess port.

    It looks for availbale ports with the right driver in their description: 'cp210x'

    If strict=False, it also looks for available serial ports missing the right driver description,
    (but only if no available cp210x driver was found among all listed ports)

    If try_port: it tries only that one
    """

    def test_availability(device, description):
        """
        Helper method to check if port is available.
        """
        try:
            log.debug(f"Checking {device}: {description}")
            serial_device = serial.Serial(device)
        except serial.SerialException:
            log.debug("Port is busy")
            return False
        else:
            serial_device.close()
            log.debug("Port is available")
            return True

    devices_wrong_description = []
    log.debug(f"Searching for USB devices: strict = {strict}")
    log.debug(f"test_address: {test_address}")

    for port in comports():
        device, description = port[0], port[1]

        # Ignore different addresses when testing specific address
        if (test_address is not None) and (device != test_address):
            continue

        # Look for CP210X driver in port description
        if "cp210" in description.lower():
            if test_availability(device, description):
                log.debug("Returning port with right description")
                return device

        elif not strict:
            if "bluetooth" in device.lower():
                continue
            if test_availability(device, description):
                log.debug("Found port with wrong description: checking for others...")
                devices_wrong_description.append(device)

    if devices_wrong_description:
        device = devices_wrong_description[0]
        log.debug(
            "Did not find port with right description: "
            f"returning port with wrong description: {device}"
        )
        return devices_wrong_description[0]

    log.warning("No ports available")
    return None
