# TODO: Run piscan and chmod by default
import os
import select
import time

import bluetooth

from cfg import BTPORT
from utils import logger, usbtool

if os.name == "nt":
    raise SystemExit("This program is designed to run only on a Raspberry Device")

logger.cfg.DEBUG = True
logger.cfg.DEBUG_READING = False
logger.set_logger()

# Establish serial connection to board
while True:
    port_chessboard = usbtool.find_address()
    if port_chessboard is None:
        print("Did not find serial port, make sure Certabo board is connected")
        time.sleep(2)
    else:
        print("Found port:", port_chessboard)
        break

usbtool.start_usbtool(port_chessboard, separate_process=True)
QUEUE_TO_USBTOOL = usbtool.QUEUE_TO_USBTOOL
QUEUE_FROM_USBTOOL = usbtool.QUEUE_FROM_USBTOOL

# Establish bluetooth connection
server_sock = bluetooth.BluetoothSocket(bluetooth.RFCOMM)

server_sock.bind(("", BTPORT))
server_sock.listen(1)

UUID = "41c9ee4d-871e-4556-b521-84c89c24710a"
bluetooth.advertise_service(
    server_sock,
    name="Certabo",
    service_id=UUID,
    provider="Certabo",
    description="Certabo Serial to Bluetooth converter",
    service_classes=[UUID, bluetooth.SERIAL_PORT_CLASS],
    profiles=[bluetooth.SERIAL_PORT_PROFILE],
)

try:
    while True:
        # Turn on center leds to indicate listening status
        QUEUE_TO_USBTOOL.put(bytes([0, 0, 0, 24, 24, 0, 0, 0]))

        print("Listening on BT port:", server_sock.getsockname())
        client_sock, address = server_sock.accept()

        print("Accepted BT connection from ", address)

        # Turn of leds to indicate connected status
        QUEUE_TO_USBTOOL.put(bytes([0, 0, 0, 0, 0, 0, 0, 0]))

        # Linux can select on queues
        # pylint: disable=protected-access
        readable_list = [QUEUE_FROM_USBTOOL._reader, client_sock]
        # pylint: enable=protected-access

        while True:
            readable, _, _ = select.select(readable_list, [], [])

            for connection in readable:
                # pylint: disable=protected-access
                if connection is QUEUE_FROM_USBTOOL._reader:
                    # pylint: enable=protected-access
                    # Send board data to client
                    try:
                        data = QUEUE_FROM_USBTOOL.get_nowait()
                        client_sock.send(data.encode("utf-8"))
                    except bluetooth.btcommon.BluetoothError as err:
                        print("Connection closed:", err)
                        break

                if connection is client_sock:
                    # Read led data from client
                    try:
                        data = client_sock.recv(1024)
                        if not data:
                            print("Lost connection to device: no data")
                            break
                        QUEUE_TO_USBTOOL.put(data)
                    except bluetooth.btcommon.BluetoothError as err:
                        print("Connection closed:", err)
                        break

            else:  # nobreak
                continue
            break  # break if there was any break above

except KeyboardInterrupt:
    print("Closing server")
finally:
    bluetooth.stop_advertising(server_sock)
    server_sock.close()
    try:
        client_sock.close()
    except NameError:
        pass
    # Give time for usbtool to turn off
    time.sleep(2)
