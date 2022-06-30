from typing import Optional, Tuple, Union

import chess
import pygame

from utils.get_books_engines import get_book_list, get_engine_list
from utils.logger import get_logger


def _has_numbers(input_string):
    return any(char.isdigit() for char in input_string)


def _number_of_pieces(inputs_string):
    return sum(not char.isdigit() for char in inputs_string)


def _row_0_to_8(row, piece="q", ignore_color=True):
    """
    Return integer between 1-8 depending on the placement of piece(queen) in a row, 0 if none
    Used for epaper setting selection
    """
    if ignore_color:
        row = row.lower()
        piece = piece.lower()

    for i in range(8):
        prefix = ""
        if i > 0:
            prefix = i
        suffix = ""
        if i < 7:
            suffix = 7 - i
        if row == f"{prefix}{piece}{suffix}":
            return i + 1
    return 0


def _row_0_to_71(row):
    """
    Return integer between 0-71 depending on the placement of two queens in a row.
    Used for both engine and difficulty choice
    """
    # Case where there are two queens
    if "Q" in row and "q" in row:
        # Check how many empty squares are on the left side
        try:
            leftmost_gap = int(row[0])
        except ValueError:
            leftmost_gap = 0
        level = (16, 30, 42, 52, 60, 66, 70, 72)[leftmost_gap : leftmost_gap + 2]

        base = level[0]
        diff = (level[1] - level[0]) // 2

        # Check how many empty squares are on the right side
        try:
            rightmost_gap = int(row[-1])
        except ValueError:
            rightmost_gap = 0
        extra = diff - rightmost_gap

        # Check if black queen comes before white queen
        # pylint: disable=invalid-name
        qs = [c for c in row if c in ("Q", "q")]
        # pylint: enable=invalid-name
        if qs[0] == "q":
            extra += diff
        num = base + extra

    # Simpler case with only one queen
    else:
        try:
            num = 8 - int(row[-1])
        except ValueError:
            num = 8
        if "q" in row:
            num += 8

    num -= 1
    return num


class BaseRemoteControl:
    def __init__(self, led_manager, on=True):
        self.led_manager = led_manager
        self.wait_between_commands = 3000
        self.last_command_time = -self.wait_between_commands
        self.last_exit_command_time = -self.wait_between_commands
        self.exit_command_initiated = {"application": False, "game": False}
        self.start_game = False
        self.can_calibrate = True
        self.changed_settings = {}
        self.log = get_logger()
        self._on = on

    @property
    def on(self):
        return self._on

    @on.setter
    def on(self, value):
        self.log.debug(f'Remote control is turned {("OFF", "ON")[value]}')
        self._on = value

    def process_state(self, state, settings) -> Tuple[Optional[str], Union[str, bool]]:
        raise NotImplementedError

    def _process_game_state(self, state, settings):
        # Do nothing if last command happened recently
        if (
            pygame.time.get_ticks() - self.last_command_time
            < self.wait_between_commands
        ):
            return None

        physical_board_fen = settings["physical_chessboard_fen"]
        if physical_board_fen == settings["virtual_chessboard"].fen():
            return None

        # Check if force-move (one of the kings removed from board)
        if state == "game_waiting_ai_move":
            for i in range(2):
                virtual_board = settings["virtual_chessboard"]
                temp_board = virtual_board.copy()
                temp_board.remove_piece_at(virtual_board.king(i))
                if temp_board.board_fen() == physical_board_fen:
                    self.log.debug("Force move recognized")
                    self.last_command_time = pygame.time.get_ticks()
                    return "force-move"

        if not settings["human_game"]:
            # Check if hint request
            if self._check_hint(settings):
                return "hint"

        # Check if game exit
        if self._check_exit(settings, type_="game"):
            return "new_game"

        return None

    def _check_hint(self, settings):
        raise NotImplementedError

    def _check_exit(self, settings, type_):
        raise NotImplementedError

    def change_settings(self, settings, key, value):
        """Update settings in dictionary, and save changes in self.changed_settings dict."""
        if settings[key] != value:
            old_value = settings[key]
            settings[key] = value
            self.changed_settings[key] = (old_value, value)
            self.log.debug(f'Changed setting "{key}": {old_value} --> {value}')

    def try_calibrate(self, settings):
        if self.can_calibrate:
            board_rows = settings["physical_chessboard_fen_missing"].split("/")
            # All normal pieces in place
            # Check if any pieces are in ranks plus E3/E6 -> Calibration
            if (
                all(
                    # Check if top and bottom rows are full
                    len(board_rows[row]) == 8
                    # Check if top and bottom rows have no integers
                    and not _has_numbers(board_rows[row])
                    for row in (0, 1, 6, 7)
                )
                # Check if middle rows are empty
                and all(board_rows[row] == "8" for row in (3, 4))
                # Check if D3 and D6 are occupied
                and board_rows[2][::2] == "34"
                and board_rows[5][::2] == "34"
            ):
                self.log.debug("Calibration command - board_state")
                self.last_command_time = pygame.time.get_ticks()
                self.led_manager.set_leds("corners")
                self.can_calibrate = False
                return True
        return False

    def try_exit(self, type_, kings_in_exit_position):
        if kings_in_exit_position:
            # Exit command started
            if not self.exit_command_initiated[type_]:
                self.log.debug(f"Exit {type_} initiated")
                self.exit_command_initiated[type_] = True
                self.last_exit_command_time = pygame.time.get_ticks() + (
                    5000 - self.wait_between_commands
                )

            # Exit after enough time
            elif (
                pygame.time.get_ticks() - self.last_exit_command_time
            ) > self.wait_between_commands:
                self.exit_command_initiated[type_] = False
                self.log.debug(f"Exit {type_} confirmed")
                return True
            self.led_manager.flash_leds("all")

        else:
            # Exit command aborted
            if self.exit_command_initiated[type_]:
                self.log.debug(f"Exit {type_} aborted")
                self.led_manager.set_leds()
                self.exit_command_initiated[type_] = False

        return False


class RemoteControlPygame(BaseRemoteControl):
    def process_state(self, state, settings) -> Tuple[Optional[str], Union[str, bool]]:
        action = None

        if not self.on:
            return action, False

        if state == "home":
            action = self._process_home_state(settings)
        elif state == "new_game":
            action = self._process_new_game_state(settings)
        elif state.startswith("game_"):
            action = self._process_game_state(state, settings)

        exit_application = self._check_exit(settings)
        if exit_application:
            exit_application = "remote_control"

        return action, exit_application

    def _process_home_state(self, settings) -> Optional[str]:
        """
        Change to new game if spare queens are placed in D4/D5
        Start calibration if all pieces are in initial positions plus D3/D6
        """

        board_rows = settings["physical_chessboard_fen"].split("/")

        # Check if spare queens are in D4/D5 -> New game
        if _row_0_to_8(board_rows[3]) == 4 and _row_0_to_8(board_rows[4]) == 4:
            self.log.debug("Remote control: New Game")
            self.last_command_time = pygame.time.get_ticks()
            self.led_manager.set_leds("corners")
            return "new_game"

        if self.try_calibrate(settings):
            return "calibration_remote"

        return None

    def _process_new_game_state(self, settings) -> Optional[str]:
        # Do not update settings if last command happened recently
        if (
            pygame.time.get_ticks() - self.last_command_time
            < self.wait_between_commands
        ):
            if not self.start_game:
                self.led_manager.set_leds("corners")
            else:
                self.led_manager.flash_leds("corners")
            return None

        if self.start_game:
            physical_board_fen = settings["physical_chessboard_fen"]
            # Check if kings are in place when starting from board position
            if not settings["use_board_position"] or (
                "k" in physical_board_fen and "K" in physical_board_fen
            ):
                self.start_game = False
                return "start"
            self.last_command_time = (
                pygame.time.get_ticks()
            )  # So it goes back to blinking next time it's called
            return None

        self.led_manager.set_leds()
        self.changed_settings = {}

        board_rows = settings["physical_chessboard_fen"].split("/")
        static_rows = "/".join(board_rows[0:2] + board_rows[-2:])
        normal_pieces = static_rows == "rnbqkbnr/pppppppp/PPPPPPPP/RNBQKBNR"

        # All normal pieces in place
        if normal_pieces:
            # Only command with two queens in different rows is 'game start'
            if _row_0_to_8(board_rows[3]) == 5 and _row_0_to_8(board_rows[4]) == 5:
                self.start_game = True
                self.last_command_time = pygame.time.get_ticks()
                # Give at least 20 seconds to remove kings, if using board
                if settings["use_board_position"]:
                    self.log.debug("Starting game once both kings are placed")
                    self.last_command_time += 20000 - self.wait_between_commands
                else:
                    self.log.debug("Starting game")

            # Color, Flip board and Book
            elif "Q" in board_rows[5] or "q" in board_rows[5]:
                # Color and Flip board
                if board_rows[5][0] == "Q":
                    self.change_settings(settings, "play_white", True)
                elif board_rows[5][0] == "q":
                    self.change_settings(settings, "play_white", False)
                if board_rows[5].lower() in ("qq6", "1q6"):
                    self.change_settings(settings, "rotate180", False)
                elif board_rows[5].lower() in ("q1q5", "2q5"):
                    self.change_settings(settings, "rotate180", True)

                # Chess 960
                if board_rows[5].lower() == "3q4":
                    if board_rows[5][1] == "Q":
                        self.change_settings(settings, "chess960", True)
                    else:
                        self.change_settings(settings, "chess960", False)

                # Book
                if board_rows[5][0] in ("4", "5", "6", "7") and board_rows[5][1] in (
                    "Q",
                    "q",
                ):
                    # If both Queens are placed, remove book
                    if "Q" in board_rows[5] and "q" in board_rows[5]:
                        self.change_settings(settings, "book", "")
                    else:
                        book_offset = int(board_rows[5][0]) - 4
                        if "q" in board_rows[5]:
                            book_offset += 4
                        try:
                            self.change_settings(
                                settings, "book", get_book_list()[book_offset]
                            )
                        except IndexError:
                            self.change_settings(settings, "book", "")

            # Use board position, Color to move, and default Time settings
            elif "Q" in board_rows[4] or "q" in board_rows[4]:
                if board_rows[4][0] == "Q":
                    self.change_settings(settings, "use_board_position", False)
                    self.change_settings(settings, "side_to_move", "white")
                elif board_rows[4][0] == "q":
                    self.change_settings(settings, "use_board_position", True)

                if board_rows[4].lower() in ("qq6", "1q6"):
                    self.change_settings(settings, "side_to_move", "white")
                elif board_rows[4].lower() in ("q1q5", "2q5"):
                    self.change_settings(settings, "side_to_move", "black")

                else:
                    try:
                        index = 7 - int(board_rows[4][0])
                        if index < 5:
                            self.change_settings(
                                settings,
                                "time_constraint",
                                ("classical", "rapid", "blitz", "unlimited", "custom")[
                                    index
                                ],
                            )
                    except ValueError:
                        pass

            # Engine difficulty
            elif "Q" in board_rows[3] or "q" in board_rows[3]:
                self.change_settings(
                    settings["_game_engine"], "Depth", _row_0_to_71(board_rows[3]) + 1
                )

            # Engine
            elif "Q" in board_rows[2] or "q" in board_rows[2]:
                engine_index = _row_0_to_71(board_rows[2])
                try:
                    self.change_settings(
                        settings["_game_engine"],
                        "engine",
                        get_engine_list()[engine_index],
                    )
                except IndexError:
                    self.change_settings(
                        settings["_game_engine"], "engine", "stockfish"
                    )

        # Kings out of place
        elif static_rows in (
            "rnbq1bnr/pppppppp/PPPPPPPP/RNBQKBNR",
            "rnbqkbnr/pppppppp/PPPPPPPP/RNBQ1BNR",
            "rnbq1bnr/pppppppp/PPPPPPPP/RNBQ1BNR",
        ):
            mins = None
            secs = None

            # White King Specifies Minutes
            king_pos = _row_0_to_8(board_rows[5], "K", False)  # unlimited to 7
            if king_pos == 1:
                self.change_settings(settings, "time_constraint", "unlimited")
            elif king_pos > 1:
                mins = king_pos - 1
            king_pos = _row_0_to_8(board_rows[4], "K", False)  # 8 to 15
            if king_pos > 0:
                mins = king_pos + 7
            king_pos = _row_0_to_8(board_rows[3], "K", False)  # 16 to 30
            if king_pos > 0:
                mins = king_pos * 2 + 14
            king_pos = _row_0_to_8(board_rows[2], "K", False)  # 40 to 120
            if king_pos == 8:
                mins = 120
            elif king_pos > 0:
                mins = king_pos * 10 + 30

            # Black King Specifies Seconds
            king_pos = _row_0_to_8(board_rows[5], "k", False)  # 0 to 7
            if king_pos > 0:
                secs = king_pos - 1
            king_pos = _row_0_to_8(board_rows[4], "k", False)  # 8 to 15
            if king_pos > 0:
                secs = king_pos + 7
            king_pos = _row_0_to_8(board_rows[3], "k", False)  # 16 to 30
            if king_pos > 0:
                secs = king_pos * 2 + 14
            king_pos = _row_0_to_8(board_rows[2], "k", False)  # 40 to 120
            if king_pos == 8:
                secs = 120
            elif king_pos > 0:
                secs = king_pos * 10 + 30

            if mins is not None or secs is not None:
                self.change_settings(settings, "time_constraint", "custom")
                if mins is not None:
                    self.change_settings(settings, "time_total_minutes", mins)
                if secs is not None:
                    self.change_settings(settings, "time_increment_seconds", secs)

        if self.changed_settings:
            for key, (old, new) in self.changed_settings.items():
                self.log.debug(f'Changed setting "{key}": {old} --> {new}')
            self.last_command_time = pygame.time.get_ticks()

        return None

    def _check_hint(self, settings):
        virtual_board = settings["virtual_chessboard"]
        temp_board = virtual_board.copy()
        temp_board.remove_piece_at(virtual_board.king(0))
        temp_board.remove_piece_at(virtual_board.king(1))
        if temp_board.board_fen() == settings["physical_chessboard_fen"]:
            self.log.debug("Implicit hint request recognized")
            # Wait five seconds until next hint request
            self.last_command_time = pygame.time.get_ticks() + 2000
            return True
        return False

    def _check_exit(self, settings, type_="application") -> bool:
        """Check if chessboard corresponds to exit command

        if type_=="application": Exit software by placing both kings in central
        squares in the same column
        elif type_=="game": Exit game by placing both kings in central squares
        diagonally

        Flash all light for five seconds to indicate exit procedure and allow
        time to abort
        """

        physical_board_fen = settings["physical_chessboard_fen"]
        if type_ == "game":
            kings_in_exit_position = "/".join(
                physical_board_fen.split("/")[3:5]
            ).lower() in (
                "4k3/3k4",
                "3k4/4k3",
            )
        else:
            kings_in_exit_position = "/".join(
                physical_board_fen.split("/")[3:5]
            ).lower() in (
                "4k3/4k3",
                "3k4/3k4",
            )
        return self.try_exit(type_, kings_in_exit_position)


class RemoteControlEpaper(BaseRemoteControl):
    def __init__(self, led_manager, original_on=True):
        super().__init__(led_manager, on=True)
        if not original_on:
            self.log.warning(
                "Epaper remote control was initialized with on=False. This was ignored!"
            )

        # We wait the same amount of time to trigger a hint as it will take for the
        # led_manager to activate the led on the missing piece
        self.hint_wait_time = self.led_manager.misplaced_wait_time * 1000
        self.cached_fen_missing = None
        self.lifted_square = None
        self.lifted_time = 0
        self.lifted_hint = False
        self.requested_hint = False  # TODO: Do we need this to be a class attribute?

    @property
    def on(self):
        return self._on

    @on.setter
    def on(self, value):
        if not value:
            self.log.warning(
                "Epaper remote control cannot be turned Off. Change was ignored!"
            )

    def process_state(self, state, settings) -> Tuple[Optional[str], Union[str, bool]]:
        action = None

        if not self.on:
            return action, False

        if state == "new_game":
            action = self._process_new_game_state(settings)
        elif state == "new_game_wrong_place":
            action = self._process_new_game_wrong_place_state(settings)
        elif state == "new_game_start_remove_kings":
            action = self._process_new_game_start_remove_kings_state(settings)
        elif state == "new_game_start_place_pieces":
            action = self._process_new_game_start_place_pieces_state(settings)
        elif state.startswith("game_"):
            action = self._process_game_state(state, settings)

        exit_application = self._check_exit(settings)
        if exit_application:
            exit_application = "remote_control"

        return action, exit_application

    # pylint: disable=too-many-return-statements
    def _process_new_game_state(self, settings) -> Optional[str]:
        # Do not update settings if last command happened recently
        if (
            pygame.time.get_ticks() - self.last_command_time
            < self.wait_between_commands
        ):
            if not self.start_game:
                self.led_manager.set_leds("corners")
            else:
                self.led_manager.flash_leds("corners")
            return None

        self.led_manager.set_leds()

        if self.start_game:
            # Check if kings are in place when starting from board position
            if (
                not settings["use_board_position"]
                or settings["physical_chessboard_fen"].lower().count("k") == 2
            ):
                self.start_game = False
                return "start"
            self.last_command_time = (
                pygame.time.get_ticks()
            )  # So it goes back to blinking next time it's called
            return None

        if self.try_calibrate(settings):
            return "calibration_remote"

        board_rows_missing = settings["physical_chessboard_fen_missing"].split("/")
        static_rows_missing = "/".join(
            board_rows_missing[0:2] + board_rows_missing[-2:]
        )
        expected_static_rows_missing = not _has_numbers(static_rows_missing)

        if not expected_static_rows_missing:
            return "wrong_place"

        board_rows = settings["physical_chessboard_fen"].split("/")
        extra_pieces = sum(_number_of_pieces(row) for row in board_rows[2:-2])

        # Check that only one extra queen is on the board
        if extra_pieces == 1:
            self.changed_settings = {}

            # Difficulty:
            queen_pos = _row_0_to_8(board_rows[2])
            if 0 < queen_pos <= 4:
                self.change_settings(settings, "human_game", queen_pos == 1)
                self.change_settings(
                    settings,
                    "difficulty",
                    ["easy", "easy", "medium", "hard"][queen_pos - 1],
                )
            # Play as:
            queen_pos = _row_0_to_8(board_rows[3])
            if 0 < queen_pos <= 2:
                self.change_settings(settings, "play_white", not queen_pos - 1)
            # Time:
            queen_pos = _row_0_to_8(board_rows[4])
            if 0 < queen_pos <= 4:
                self.change_settings(
                    settings,
                    "time_constraint",
                    ["unlimited", "blitz", "rapid", "classical"][queen_pos - 1],
                )
            # Start game:
            queen_pos = _row_0_to_8(board_rows[5])
            if 0 < queen_pos <= 3:
                if queen_pos == 1:
                    self.change_settings(settings, "use_board_position", False)
                    self.change_settings(settings, "side_to_move", "white")
                    self.start_game = True
                    self.last_command_time = pygame.time.get_ticks()
                    self.log.debug("Starting game")
                elif queen_pos == 2:
                    self.change_settings(settings, "use_board_position", True)
                    self.change_settings(settings, "side_to_move", "white")
                    self.start_game = True
                    self.log.debug("Starting game once both kings are placed")
                    return "start_position"
                elif queen_pos == 3:
                    self.change_settings(settings, "use_board_position", True)
                    self.change_settings(settings, "side_to_move", "black")
                    self.start_game = True
                    self.log.debug("Starting game once both kings are placed")
                    return "start_position"

            if self.changed_settings:
                # Start game branches handle last_command_time manually
                if not self.start_game:
                    self.last_command_time = pygame.time.get_ticks()
                return None

        return None

    # pylint: enable=too-many-return-statements

    def _process_new_game_wrong_place_state(self, settings) -> Optional[str]:
        # Nothing changed
        if settings["physical_chessboard_fen_missing"] == self.cached_fen_missing:
            return None

        board_rows_missing = settings["physical_chessboard_fen_missing"].split("/")
        static_rows_missing = "/".join(
            board_rows_missing[0:2] + board_rows_missing[-2:]
        )
        expected_static_rows_missing = not _has_numbers(static_rows_missing)
        extra_pieces_missing = sum(
            _number_of_pieces(row) for row in board_rows_missing[2:-2]
        )

        # Check if pieces are fixed
        if expected_static_rows_missing and extra_pieces_missing <= 1:
            self.cached_fen_missing = None
            return "pieces_placed"

        # Highlight wrong squares
        physical_board_map = chess.Board(
            fen=settings["physical_chessboard_fen"]
        ).piece_map()
        target_board_map = chess.Board(
            fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR"
        ).piece_map()
        bad_squares = []
        for file in range(8):
            # Check if pieces in initial ranks are not expected
            for rank in (0, 1, 6, 7):
                square = chess.square(file, rank)
                if physical_board_map.get(square) != target_board_map.get(square):
                    bad_squares.append(chess.square_name(square))
            # Check for any additional pieces in middle ranks
            for rank in range(2, 6):
                square = chess.square(file, rank)
                if square in physical_board_map:
                    bad_squares.append(chess.square_name(square))
        self.led_manager.set_leds(bad_squares)
        self.cached_fen_missing = settings["physical_chessboard_fen_missing"]
        return None

    def _process_new_game_start_remove_kings_state(self, settings) -> Optional[str]:
        if settings["physical_chessboard_fen"].lower().count("k") == 0:
            return "kings_removed"
        return None

    def _process_new_game_start_place_pieces_state(self, settings) -> Optional[str]:
        if settings["physical_chessboard_fen"].lower().count("k") == 2:
            self.start_game = False
            return "start"
        return None

    def _check_hint(self, settings):
        lifted = False
        virtual_board = settings["virtual_chessboard"]
        # TODO: What happens if more than one square is lifted?
        for square in chess.SQUARES:
            if virtual_board.color_at(square) == settings["play_white"]:
                temp_board = virtual_board.copy()
                temp_board.remove_piece_at(square)
                if temp_board.board_fen() == settings["physical_chessboard_fen"]:
                    lifted = True
                    if self.lifted_square != square:
                        self.lifted_time = pygame.time.get_ticks() + self.hint_wait_time
                        self.lifted_square = square
                        self.requested_hint = False
                    elif (
                        pygame.time.get_ticks() > self.lifted_time
                        and not self.requested_hint
                    ):
                        root_moves = [
                            move
                            for move in virtual_board.legal_moves
                            if move.from_square == square
                        ]
                        if root_moves:
                            self.log.debug("Implicit hint request recognized")
                            # Wait a while until next hint request
                            self.requested_hint = True
                            settings["hint_root_moves"] = root_moves
                            return True
        if not lifted:
            self.lifted_square = None
            self.requested_hint = False
        return False

    def _check_exit(self, settings, type_="application") -> bool:
        """Check if chessboard corresponds to exit command

        if type_=="application": Exit software by placing both kings in central
        squares
        elif type_=="game": Exit game by removing both kings

        Flash all light for five seconds to indicate exit procedure and allow
        time to abort
        """

        if type_ == "game":
            kings_in_exit_position = (
                not "k" in settings["physical_chessboard_fen"].lower()
            )
        else:
            kings_in_exit_position = "/".join(
                settings["physical_chessboard_fen"].split("/")[3:5]
            ).lower() in (
                "4k3/4k3",
                "3k4/3k4",
                "4k3/3k4",
                "3k4/4k3",
            )
        return self.try_exit(type_, kings_in_exit_position)
