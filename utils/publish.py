import datetime
import queue
import threading
from datetime import datetime

import chess.pgn
import requests

from utils import logger

log = logger.get_logger()


QUIT = object()


def publisher_thread(publisher_queue, base_url, game_id, game_key):
    """Blocking thread that publishes game data to server

    This can be tested with
        base_url: https://broadcast.certabo.com
        game-key: aaa690b5-757b-48ad-9135-e4aac22e80ba
        gam-id: 102
    """

    log.info("Starting publisher thread")
    log.debug(f"base_url={base_url}, game_id={game_id}, game_key={game_key}")
    publish_url = f"{base_url}/api/game/{game_id}/"
    data = {"key": game_key}
    while True:
        message = publisher_queue.get()

        if message is QUIT:
            log.debug("Quitting publisher thread")
            return

        data["pgn_data"] = message
        data["key"] = game_key
        log.debug("Sending game state to server")
        request = requests.patch(publish_url, data=data)
        if not request.ok:
            log.warning(f"Failed to publish game state to server: request={request}")


class Publisher:
    def __init__(self, url, game_id=None, game_key=None):
        self.running = url is not None
        if not self.running:
            return

        if url.endswith("/"):
            url = url[:-1]
        self.queue = queue.Queue()
        self.thread = threading.Thread(
            target=publisher_thread,
            kwargs=dict(
                publisher_queue=self.queue,
                base_url=url,
                game_id=game_id,
                game_key=game_key,
            ),
            daemon=True,
        )
        self.thread.start()

    def kill(self):
        if self.running:
            self.queue.put(QUIT)
            self.thread.join(timeout=5)

    def publish_pgn(self, settings: dict):
        if self.running:
            self.queue.put(generate_pgn(settings))


def generate_pgn(settings: dict):
    move_history = [move.uci() for move in settings["virtual_chessboard"].move_stack]
    game = chess.pgn.Game()
    game.headers["Date"] = datetime.now().strftime("%Y.%m.%d")
    opponent = "Computer" if not settings["human_game"] else "Human"
    if settings["play_white"]:
        game.headers["White"] = "Human"
        game.headers["Black"] = opponent
    else:
        game.headers["White"] = opponent
        game.headers["Black"] = "Human"
    game.headers["Result"] = settings["virtual_chessboard"].result()
    game.setup(
        chess.Board(settings["starting_position"], chess960=settings["chess960"])
    )
    if len(move_history) >= 2:
        node = game.add_variation(chess.Move.from_uci(move_history[0]))
        for move in move_history[1:]:
            node = node.add_variation(chess.Move.from_uci(move))
    pgn_data = game.accept(chess.pgn.StringExporter())
    return pgn_data
