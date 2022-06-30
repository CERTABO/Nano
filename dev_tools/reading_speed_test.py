import logging
import time

import cfg
from utils import reader_writer, usbtool, logger

NTRIALS = 10
cfg.APPLICATION = 'reading_speed_test'
cfg.VERSION = '09.07.2020'
cfg.DEBUG = True
cfg.DEBUG_READING = True

while True:
    port_chessboard = usbtool.find_address()
    if port_chessboard is not None:
        break
    else:
        print('Did not find serial port, make sure Certabo board is connected')
        time.sleep(.1)

logger.set_logger()
usbtool.start_usbtool(port_chessboard)
usb_reader = reader_writer.BoardReader(port_chessboard)
led_manager = reader_writer.LedWriter()


def msg(message):
    logging.info(message)
    print(message)


border_leds = [
    'c5', 'd5', 'e5',
    'c4',       'e4',
    'c3', 'd3', 'e3',
]

msg('Place black pawns around d4 square and remove any other pieces from the board')
led_manager.set_leds(border_leds)

while usb_reader.read_board() != '8/8/8/2ppp3/2p1p3/2ppp3/8/8':
    time.sleep(1)

times = []
for i in range(10):
    msg(f'Trial {i}')

    led_manager.set_leds(border_leds)
    while usb_reader.read_board() != '8/8/8/2ppp3/2p1p3/2ppp3/8/8':
        time.sleep(.01)
    time.sleep(2)

    msg('Place white pawn on D4 when the square LED turns on')
    time.sleep(.500)
    led_manager.set_leds()
    time.sleep(.500)
    led_manager.set_leds('d4')
    time.sleep(.750)  # Time that it takes to send command

    start_time = time.time()
    while usb_reader.read_board() != '8/8/8/2ppp3/2pPp3/2ppp3/8/8':
        time.sleep(.001)
    print('here')
    end_time = time.time()
    diff_time = (end_time - start_time) * 1000
    times.append(diff_time)
    msg(f'Change detected in {diff_time:.0f}ms')
    print('Remove white pawn from D4')

led_manager.set_leds()
msg(f'All times: {times}')
msg(f'Mean: {sum(times) / NTRIALS}')
msg(f'Min: {min(times)}')
msg(f'Max: {max(times)}')