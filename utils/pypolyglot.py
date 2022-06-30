# Todo: Use python-chess instead
import os

import chess
import chess.polyglot

from utils.get_books_engines import BOOK_PATH
from utils.logger import get_logger

TO_EXE = True

log = get_logger()


class Finder:
    def __init__(self, book, board, difficulty):
        self.book_path = os.path.join(BOOK_PATH, book)
        self.board = board
        self.difficulty = difficulty
        self.reader = chess.polyglot.open_reader(self.book_path)

    def bestmove(self):
        entry = self.reader.get(self.board)
        if entry is not None:
            best_move = entry.move.uci()
        else:
            best_move = None
        return best_move
