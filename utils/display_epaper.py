import math
import multiprocessing
import os
import threading
import time
from typing import Optional, Tuple, Union

import pygame
from chess import BLACK, STARTING_BOARD_FEN, WHITE
from PIL import Image, ImageDraw, ImageFont, ImageOps

import cfg
from utils.logger import get_logger
from utils.openings import OPENINGS
from utils.reader_writer import FEN_SPRITE_MAPPING

log = get_logger()

EPD_PARTIAL_UPDATE_COUNT = 2  # Number of partial updates before a full update
EPD_UPDATE_RATE = 0.2  # Time in seconds between updates

SCREEN_WIDTH = 250
SCREEN_HEIGHT = 122
SCREEN_HALF_WIDTH = int(SCREEN_WIDTH / 2)
SCREEN_HALF_HEIGHT = int(SCREEN_HEIGHT / 2)


def pil_to_surface(pil_image):
    return pygame.image.fromstring(
        pil_image.tobytes(), pil_image.size, pil_image.mode
    ).convert()


def _epaper_thread(queue_to_epd):
    # pylint: disable=import-outside-toplevel
    from epd.epd2in13_V2 import EPD

    # pylint: enable=import-outside-toplevel

    epd = EPD()
    epd.init(EPD.FULL_UPDATE)

    while True:
        cmd, canvas = queue_to_epd.get()

        if cmd == "full":
            epd.init(epd.FULL_UPDATE)
            buffer = epd.getbuffer(canvas)
            epd.displayPartBaseImage(buffer)
            epd.init(epd.PART_UPDATE)
        elif cmd == "partial":
            buffer = epd.getbuffer(canvas)
            epd.displayPartial(buffer)
            epd.init(epd.PART_UPDATE)
        elif cmd == "quit":
            log.debug("Quitting Epaper display")
            epd.sleep()
            return
        else:
            raise ValueError(f"cmd {cmd} not recognized")


def _epaper_emulator_thread(queue_to_epd):
    os.environ["SDL_VIDEO_CENTERED"] = "1"
    pygame.init()
    screen_options = pygame.HWSURFACE | pygame.DOUBLEBUF
    screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT), screen_options, 32)
    pygame.display.flip()

    # canvas = Image.new("1", (SCREEN_WIDTH, SCREEN_HEIGHT), 0xFF)
    partial_refresh_time = 0.3
    partial_refresh_timer = 0
    full_refresh_time = 2.0
    full_refresh_timer = 0
    full_refresh_flash_count = 0
    full_refresh_flash_amount = 6

    while True:
        cmd = None
        full_refresh_animation = False
        if not queue_to_epd.empty():
            cmd, canvas = queue_to_epd.get_nowait()

        if cmd == "full":
            full_refresh_animation = True
            full_refresh_timer = (
                time.time() + full_refresh_time / full_refresh_flash_amount
            )
            full_refresh_flash_count = 0
        elif cmd == "partial":
            full_refresh_animation = False
            partial_refresh_timer = time.time() + partial_refresh_time
        elif cmd == "quit":
            log.debug("Quitting Pygame display")
            break
        elif cmd is None:
            pass
        else:
            raise ValueError(f"cmd {cmd} not recognized")

        if not full_refresh_animation:
            if time.time() > partial_refresh_timer:
                screen.blit(pil_to_surface(canvas.convert("RGB")), (0, 0))
            pygame.display.flip()
        else:
            # Simulate full update blinking
            while full_refresh_animation:
                # Show normal picture on even frames
                if full_refresh_flash_count % 2:
                    screen.blit(pil_to_surface(canvas.convert("RGB")), (0, 0))
                # Invert picture on odd frames
                else:
                    inverted = ImageOps.invert(canvas.convert("RGB"))
                    screen.blit(pil_to_surface(inverted.convert("RGB")), (0, 0))

                if time.time() > full_refresh_timer:
                    full_refresh_flash_count += 1
                    full_refresh_timer = (
                        time.time() + full_refresh_time / full_refresh_flash_amount
                    )
                    if full_refresh_flash_count == full_refresh_flash_amount:
                        break
                pygame.display.flip()

    pygame.display.quit()
    pygame.quit()


class DisplayEpaper:
    def __init__(self, game_clock=None):
        self.game_clock = game_clock
        self.epaper_pygame = cfg.DEBUG_PYGAME

        # Load all the sprites,TODO: move this to another area?
        self.sprites = {}
        for _, _, files in os.walk("sprites/sprites_epaper"):
            for file in files:
                if file.endswith(".png"):
                    self.sprites[file[:-4]] = Image.open(
                        f"sprites/sprites_epaper/{file}"
                    )
        # load font, TODO: move this to another area?
        self.font_small = ImageFont.truetype("fonts/at01.ttf", size=16)
        self.font_medium_light = ImageFont.truetype("fonts/Abaddon Light.ttf", size=16)
        self.font_medium_bold = ImageFont.truetype("fonts/Abaddon Bold.ttf", size=16)

        self.canvas = Image.new("1", (SCREEN_WIDTH, SCREEN_HEIGHT), 0xFF)
        self.canvas_draw = ImageDraw.Draw(self.canvas)

        self.epd_update_time = 0
        self.epd_update_count = 0
        self.epd_last_canvas = None
        self.queue_to_epd = multiprocessing.Queue(maxsize=8)

        if self.epaper_pygame:
            self.epd_thread = threading.Thread(
                target=_epaper_emulator_thread,
                args=(self.queue_to_epd,),
                daemon=True,
            )
        else:
            self.epd_thread = threading.Thread(
                target=_epaper_thread,
                args=(self.queue_to_epd,),
                daemon=True,
            )
        self.epd_thread.start()

        self.opening = None
        self.init_state = False

        self.in_game = False
        self.cur_turn = None

    def quit(self):
        self._blit_sprite((0, 0), "logo")
        self._force_update_epd()
        self._update_epd()

        self.queue_to_epd.put(("quit", None))

        log.debug("Awaiting epd thread quit")
        self.epd_thread.join()
        log.debug("Quitting display module..")

    def _clear_canvas(self):
        self.canvas_draw.rectangle((0, 0, SCREEN_WIDTH, SCREEN_HEIGHT), fill=0xFF)

    def _blit_sprite(self, pos, name):
        sprite = self.sprites[name]
        self.canvas.paste(sprite, pos, sprite.getchannel("A"))

    def _show_board(self, pos, fen_string, *, rotate=False):
        x0, y0 = pos
        self._blit_sprite(pos, "chessboard")
        fen_string = fen_string.split(" ")[0]
        if rotate:
            fen_string = fen_string[::-1]
        x, y = 0, 0
        for char in fen_string:
            if char in FEN_SPRITE_MAPPING:
                self._blit_sprite(
                    (x0 + 4 + 15 * x, y0 + 1 + 15 * y), FEN_SPRITE_MAPPING[char]
                )
                x += 1
            elif char == "/":  # new line
                x = 0
                y += 1
            elif char == "X":  # Missing piece
                x += 1
            else:
                x += int(char)

    def _display_move(
        self, pos, piece, move_text, score_text="", promotion_piece="", symbol_text=""
    ):
        piece_width = 0
        move_text_width = self.font_medium_bold.getsize(move_text)[0]
        promotion_piece_width = 0
        symbol_text_width = self.font_medium_bold.getsize(symbol_text)[0]
        score_text_width = self.font_small.getsize(score_text)[0]

        # Offset of score_text dependent on how much room is avaliable
        score_text_offset = 5
        if (
            piece_width + move_text_width + promotion_piece_width + score_text_width
            > 35
        ):
            score_text_offset = 1

        piece = FEN_SPRITE_MAPPING.get(piece, piece)
        promotion_piece = FEN_SPRITE_MAPPING.get(promotion_piece, promotion_piece)

        if piece != "":
            self._blit_sprite(pos, piece)
            piece_width = 9
        self.canvas_draw.text(
            (pos[0] + piece_width, pos[1] + 3), move_text, font=self.font_medium_bold
        )
        if promotion_piece != "":
            self._blit_sprite(
                (pos[0] + piece_width + move_text_width, pos[1]), promotion_piece
            )
            promotion_piece_width = 9
        self.canvas_draw.text(
            (
                pos[0] + piece_width + move_text_width + promotion_piece_width,
                pos[1] + 3,
            ),
            symbol_text,
            font=self.font_medium_bold,
        )
        self.canvas_draw.text(
            (
                pos[0]
                + piece_width
                + move_text_width
                + promotion_piece_width
                + symbol_text_width
                + score_text_offset,
                pos[1] + 3,
            ),
            score_text,
            font=self.font_small,
        )

        return (
            piece_width
            + move_text_width
            + promotion_piece_width
            + symbol_text_width
            + score_text_width
            + score_text_offset
        )

    def _display_move_san(self, pos, san, turn, score_text="", show_pawn=True):
        piece = ""
        promotion_piece = ""
        symbol_text = ""
        move_text = san
        if move_text != "-":
            if move_text[-1] in ["+", "#", "*"]:
                symbol_text = move_text[-1]
                move_text = move_text[:-1]
            if move_text[-2] == "=":
                promotion_piece = move_text[-1]
                if not turn:
                    promotion_piece = promotion_piece.lower()
                move_text = move_text[:-1]
            if move_text[0] in ["R", "N", "B", "Q", "K"]:
                piece = move_text[0]
                move_text = move_text[1:]
                if not turn:
                    piece = piece.lower()
            else:
                if (not move_text[0] == "O") and show_pawn:  # O-O/O-O-O = castling
                    if turn:
                        piece = "P"
                    else:
                        piece = "p"
        return self._display_move(
            pos,
            piece,
            move_text,
            score_text=score_text,
            promotion_piece=promotion_piece,
            symbol_text=symbol_text,
        )

    def _display_option(self, pos, option, piece, move_text, selected):
        x = pos[0]
        y = pos[1]
        if not selected:
            self.canvas_draw.rounded_rectangle(
                (x, y + 6, x + 58, y + 17), width=1, radius=0
            )
            # self.canvas_draw.rectangle((x+1,y+1,x+57,y+17),fill=0XFF)
        else:
            self.canvas_draw.rounded_rectangle(
                (x, y + 4, x + 58, y + 18), width=2, radius=3
            )
        self.canvas_draw.text((x + 3, y + 4), option, font=self.font_small)
        self._display_move((x + 32, y + 1), piece, move_text)

    def _display_radio_options(self, pos, selected, options):
        for i, option in enumerate(options):
            piece = option[1]
            if i == selected:
                piece = piece.lower()
            self._display_option(
                (pos[0] + 62 * i, pos[1]), option[0], piece, option[2], i == selected
            )

    def _display_clock(self, pos, time):
        clock = self.game_clock
        full_time = clock.time_total_minutes * 60
        ratio = time / full_time
        meter = f"{clock.time_total_minutes}min."
        if time <= 60:
            ratio = time / 60
            meter = "1min."
        elif time <= 60 * 5:
            ratio = time / (60 * 5)
            meter = "5min."

        self.canvas_draw.rounded_rectangle(
            (pos[0], pos[1], pos[0] + 40, pos[1] + 10), radius=3, width=2
        )
        self.canvas_draw.text(
            (pos[0] + 21, pos[1] + 8), meter, font=self.font_small, anchor="ma"
        )
        if ratio > 0:
            self.canvas_draw.rectangle(
                (
                    pos[0] + 3,
                    pos[1] + 3,
                    pos[0] + 3 + math.ceil(34 * ratio),
                    pos[1] + 7,
                ),
                fill=0x00,
            )

    def _display_clocks(self, turn):
        arrow_x = [15, 223]
        arrow_y = [68, 90]
        arrow = "arrow"
        clock = self.game_clock
        if clock is None or clock.time_constraint == "unlimited":
            self._blit_sprite((arrow_x[not turn], arrow_y[0]), arrow)
        else:
            self._display_clock((0, 69), clock.time_white_left)
            self._display_clock((SCREEN_WIDTH - 32 - 10, 69), clock.time_black_left)
            if turn:
                arrow_time = clock.time_white_left
            else:
                arrow_time = clock.time_black_left
            if arrow_time <= 60:
                arrow = "arrow_t1"
            elif arrow_time <= 60 * 5:
                arrow = "arrow_t5"
            self._blit_sprite((arrow_x[not turn], arrow_y[1]), arrow)

    def _update_epd(self):
        # TODO: Investigate if we can:
        #  1) Only create buffer when the screen elements have changed, otherwise we don't
        #     spend effert creating it (it won't be used anyway)
        #  2) Move the update_time_check to the thread, which keeps the last non-forced buffer
        #     in memory until enough time has passed. If it's a forced update
        #     (new flag variable is needed), it displays it immediately. This replaces the
        #     _force_update_epd method below
        if self.epd_update_time < time.time():
            # TODO: Is this comparison expensive?
            if self.canvas != self.epd_last_canvas:
                canvas_copy = self.canvas.copy()
                if self.epd_update_count <= 0:
                    log.debug("updating screen full")
                    self.queue_to_epd.put(("full", canvas_copy))
                    self.epd_update_count = EPD_PARTIAL_UPDATE_COUNT
                else:
                    log.debug("updating screen partial")
                    self.queue_to_epd.put(("partial", canvas_copy))
                    self.epd_update_count -= 1
                self.epd_last_canvas = canvas_copy
                self.epd_update_time = time.time() + EPD_UPDATE_RATE

    def _force_update_epd(self):
        """
        Forces a Full Update of E-Paper Display (if new image)
        """
        self.epd_update_time = 0
        self.epd_update_count = 0

    def _get_parsed_san(self, board, move_stack, turn=WHITE):
        """
        Parses the chess.py variation_san string into an array of (san_move,color,round)
         that can then be iter()'d
        """
        moves = []
        san_string = board.variation_san(move_stack)
        san_string = san_string.replace("...", ". - ")
        for i, line in enumerate(san_string.split(".")):
            if i > 0:
                for j, move in enumerate(line.split(" ")):
                    move = move.strip()
                    if j <= 2 and move != "":
                        if move != "-":
                            moves.append((move, turn, i))
                        turn = not turn
        return moves

    def process_window(
        self, state: str, settings: Optional[dict] = None
    ) -> Tuple[str, Union[str, bool]]:
        action = None
        exit_program = False

        if state in ("init", "init_connection", "startup_leds"):
            self._process_init_state()
        elif state.startswith("calibration"):
            self._process_calibration_state(settings)
        elif state == "home":
            action = self._process_home_state(settings)
        elif state.startswith("new_game"):
            self._process_new_game_states(settings, state)
        elif state.startswith("game"):
            action = self._process_game_states(settings, state)
        else:
            raise ValueError(state)

        # Keyboard controls when in debug mode:
        if self.epaper_pygame:
            events = pygame.event.get()
            for event in events:
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_RETURN:
                        action = "start"
                    elif event.key == pygame.K_ESCAPE:
                        if state.startswith("game"):
                            action = "exit"
                        else:
                            exit_program = True
                if event.type == pygame.QUIT:
                    exit_program = True

        self._update_epd()

        self.init_state = False
        return action, exit_program

    def _process_init_state(self):
        self._blit_sprite((0, 0), "logo")
        self._force_update_epd()

    def _process_home_state(self, settings):
        settings["_certabo_settings"]["remote_control"] = True
        settings["human_game"] = False
        settings["difficulty"] = "easy"
        settings["_analysis_engine"]["engine"] = "stockfish"
        settings["_analysis_engine"]["Depth"] = 20
        settings["time_constraint"] = "unlimited"
        self.in_game = False
        return "new_game"

    def _process_calibration_state(self, settings):
        self._force_update_epd()
        self._clear_canvas()
        self._show_board((128, 0), settings["physical_chessboard_fen"])
        self.canvas_draw.line((5, 35, 120, 35))
        self.canvas_draw.text(
            (64, SCREEN_HALF_HEIGHT - 5),
            "Calibrating...",
            font=self.font_medium_bold,
            anchor="mm",
        )
        self.canvas_draw.line((5, 75, 120, 75))

    def _process_new_game_states(self, settings, state):
        self._clear_canvas()
        if state == "new_game":
            self.opening = None
            # Game Mode
            self.canvas_draw.text((0, 0), "+Game Mode:", font=self.font_medium_light)
            if settings["human_game"] is True:
                selected = 0
            else:
                selected = {
                    "easy": 1,
                    "medium": 2,
                    "hard": 3,
                }[settings["difficulty"]]
            self._display_radio_options(
                (2, 10),
                selected,
                [
                    ("Human", "Q", "a6"),
                    ("Easy", "Q", "b6"),
                    ("Mediu.", "Q", "c6"),
                    ("Hard", "Q", "d6"),
                ],
            )
            # Play as
            self.canvas_draw.text((0, 30), "+Play as:", font=self.font_medium_light)
            selected = 0
            if not settings["play_white"]:
                selected = 1
            self._display_radio_options(
                (2, 40),
                selected,
                [
                    ("White", "Q", "a5"),
                    ("Black", "Q", "b5"),
                ],
            )
            # Time
            self.canvas_draw.text((0, 60), "+Time:", font=self.font_medium_light)
            selected = {
                "unlimited": 0,
                "blitz": 1,
                "rapid": 2,
                "classical": 3,
                "custom": 0,
            }[settings["time_constraint"]]
            self._display_radio_options(
                (2, 70),
                selected,
                [
                    ("Unli.", "Q", "a4"),
                    ("5+0", "Q", "b4"),
                    ("10+0", "Q", "c4"),
                    ("15+5", "Q", "d4"),
                ],
            )
            # Board Start
            self.canvas_draw.text((0, 90), "+Board Start:", font=self.font_medium_light)
            selected = -1
            # TODO: figure a way to show state here
            if settings["use_board_position"]:
                if settings["side_to_move"] == "white":
                    selected = 1
                else:
                    selected = 2
            self._display_radio_options(
                (2, 100),
                selected,
                [("Initial", "Q", "a3"), ("Pos.W", "Q", "b3"), ("Pos.B", "Q", "c3")],
            )
        elif state == "new_game_wrong_place":
            self._show_board((128, 0), STARTING_BOARD_FEN)
            self.canvas_draw.line((5, 35, 120, 35))
            self.canvas_draw.text(
                (64, 40),
                "Please place pieces\n in initial position.",
                font=self.font_medium_bold,
                anchor="ma",
            )
            self.canvas_draw.line((5, 75, 120, 75))
            self._force_update_epd()
        elif state == "new_game_start_remove_kings":
            self.canvas_draw.line((15, 35, SCREEN_WIDTH - 15, 35))
            self.canvas_draw.line((15, 70, 113, 70))
            self.canvas_draw.line((135, 70, SCREEN_WIDTH - 15, 70))
            self._blit_sprite((SCREEN_HALF_WIDTH - 10, 67), "white_king")
            self._blit_sprite((SCREEN_HALF_WIDTH, 67), "black_king")
            self.canvas_draw.text(
                (SCREEN_HALF_WIDTH, 38),
                "Starting from custom board position...",
                font=self.font_small,
                anchor="ma",
            )
            self.canvas_draw.text(
                (SCREEN_HALF_WIDTH, 50),
                "Remove Kings from board",
                font=self.font_medium_bold,
                anchor="ma",
            )
            self._force_update_epd()
        elif state == "new_game_start_place_pieces":
            self.canvas_draw.line((15, 35, SCREEN_WIDTH - 15, 35))
            self.canvas_draw.line((15, 70, 113, 70))
            self.canvas_draw.line((135, 70, SCREEN_WIDTH - 15, 70))
            self._blit_sprite((SCREEN_HALF_WIDTH - 10, 67), "white_king")
            self._blit_sprite((SCREEN_HALF_WIDTH, 67), "black_king")
            self.canvas_draw.text(
                (SCREEN_HALF_WIDTH, 38),
                "Set board to custom position",
                font=self.font_small,
                anchor="ma",
            )
            self.canvas_draw.text(
                (SCREEN_HALF_WIDTH, 50),
                "Place back Kings when done",
                font=self.font_medium_bold,
                anchor="ma",
            )
            self._force_update_epd()

    def _process_game_states(self, settings, state):
        # Logic to force update screen when game starts or when turn changes
        if self.in_game is False:
            self._force_update_epd()
            self.in_game = True
            self.cur_turn = settings["virtual_chessboard"].turn
        elif self.cur_turn != settings["virtual_chessboard"].turn:
            self._force_update_epd()
            self.cur_turn = settings["virtual_chessboard"].turn

        self._clear_canvas()
        # ========================
        # Render Clocks/Player Markers
        # ========================
        self._blit_sprite((10, 29), "white_pawn_large")
        self._blit_sprite((SCREEN_WIDTH - 32, 29), "black_pawn_large")
        if settings["human_game"]:
            side_a = "Human"
            side_b = "Human"
        elif settings["play_white"]:
            side_a = "Human"
            side_b = "Maia"
        else:
            side_a = "Maia"
            side_b = "Human"
        self.canvas_draw.text((21, 15), side_a, font=self.font_medium_bold, anchor="ma")
        self.canvas_draw.text(
            (SCREEN_WIDTH - 21, 15), side_b, font=self.font_medium_bold, anchor="ma"
        )
        self._display_clocks(settings["virtual_chessboard"].turn)

        # ========================
        # Render Terminal
        # ========================
        self.canvas_draw.text(
            (SCREEN_HALF_WIDTH, 0),
            "Move History",
            font=self.font_medium_light,
            anchor="ma",
        )
        move_scores = {}
        if settings["analysis_engine"] is None:
            return "analysis"
        else:
            history = settings["analysis_engine"].get_analysis_history(
                settings["virtual_chessboard"]
            )
            for move_idx, position_analysis in history.items():
                if position_analysis.complete:
                    move_scores[move_idx] = position_analysis.get_score()

        # --------------------------------
        # Print the move stack
        # TODO: run this only when a move happens
        terminal_data = self._get_parsed_san(
            settings["initial_chessboard"], settings["virtual_chessboard"].move_stack
        )
        if terminal_data != []:
            terminal_y = 16  # y position of first round line
            terminal_l = 5  # number of rounds to display
            terminal_s = terminal_data[-1][2] - terminal_l  # first round to display
            cur_turn = 0
            for move, color, game_round in iter(terminal_data):
                if game_round > terminal_s:
                    self.canvas_draw.text(
                        (55, terminal_y + 4),
                        f"{game_round}.",
                        font=self.font_small,
                        anchor="ra",
                    )
                    score = ""
                    if cur_turn in move_scores:
                        if move_scores[cur_turn] > 0:
                            plus = "+"
                        else:
                            plus = ""
                        score = f"{plus}{move_scores[cur_turn]}"
                    if color == WHITE:
                        self._display_move_san((55, terminal_y), move, WHITE, score)
                    if color == BLACK:
                        self._display_move_san((130, terminal_y), move, BLACK, score)
                        terminal_y += 16
                cur_turn += 1

        # ========================
        # Render Banner
        # ========================
        # order is game_over -> hint -> check -> opening
        banner_pos = (SCREEN_HALF_WIDTH, SCREEN_HEIGHT - 22)
        subbanner_pos = (SCREEN_HALF_WIDTH, SCREEN_HEIGHT - 12)
        # opening Detection
        if self.init_state and state == "game_resume":
            epd_string = settings["virtual_chessboard"].epd()
            # self.opening = None # Uncomment to hide opening after it has passed
            if epd_string in OPENINGS:
                self.opening = OPENINGS[epd_string]
        # Banner selection
        if state == "game_over":
            if self.game_clock.game_overtime:
                if self.game_clock.game_overtime_winner == 1:
                    self.canvas_draw.text(
                        banner_pos,
                        "Time Over: White Wins!",
                        font=self.font_medium_bold,
                        anchor="ma",
                    )
                else:
                    self.canvas_draw.text(
                        banner_pos,
                        "Time Over: Black Wins!",
                        font=self.font_medium_bold,
                        anchor="ma",
                    )
            elif settings["virtual_chessboard"].is_checkmate():
                self.canvas_draw.text(
                    banner_pos, "Checkmate!", font=self.font_medium_bold, anchor="ma"
                )
            elif settings["virtual_chessboard"].is_stalemate():
                self.canvas_draw.text(
                    banner_pos, "Stalemate!", font=self.font_medium_bold, anchor="ma"
                )
            elif settings["virtual_chessboard"].is_fivefold_repetition():
                self.canvas_draw.text(
                    banner_pos,
                    "Five-Fold Repetition!",
                    font=self.font_medium_bold,
                    anchor="ma",
                )
            elif settings["virtual_chessboard"].is_seventyfive_moves():
                self.canvas_draw.text(
                    banner_pos,
                    "Seventy-Five Moves!",
                    font=self.font_medium_bold,
                    anchor="ma",
                )
            elif settings["virtual_chessboard"].is_insufficient_material():
                self.canvas_draw.text(
                    banner_pos,
                    "Insufficient Material!",
                    font=self.font_medium_bold,
                    anchor="ma",
                )

            self.canvas_draw.text(
                subbanner_pos, "Remove Kings to Exit", font=self.font_small, anchor="ma"
            )
        elif settings["show_hint"]:
            moves = settings["hint_engine"].get_hint_bestmove_pv()

            if moves:
                score = settings["hint_engine"].get_hint_bestmove_score()
                score_value = ""
                if score is not None:
                    if score <= 0:
                        score_value = str(score)
                    else:
                        score_value = "+" + str(score)
                score_text = f"{score_value}cp"

                self.canvas_draw.text(
                    (5, SCREEN_HEIGHT - 17),
                    "Hint:",
                    font=self.font_medium_light,
                    anchor="la",
                )
                x = 37
                first = True
                for move, color, _ in iter(
                    self._get_parsed_san(settings["virtual_chessboard"], moves)
                ):
                    old_x = x
                    if first:
                        x += self._display_move_san(
                            (x, 104), move, color, score_text=score_text
                        )
                        first = False
                    else:
                        x += self._display_move_san((x, 104), move, color)
                    if x > SCREEN_WIDTH:
                        self.canvas_draw.rectangle(
                            (old_x, SCREEN_HEIGHT - 18, SCREEN_WIDTH, SCREEN_HEIGHT),
                            fill=0xFF,
                        )
                        break
            else:
                self.canvas_draw.text(
                    (SCREEN_HALF_WIDTH, SCREEN_HEIGHT - 20),
                    "...",
                    font=self.font_medium_light,
                    anchor="ma",
                )
        elif settings["virtual_chessboard"].is_check():
            self.canvas_draw.text(
                banner_pos, "-Check-", font=self.font_medium_bold, anchor="ma"
            )

        elif self.opening is not None:
            opening_text = f"~{self.opening}~"
            if self.font_medium_light.getsize(opening_text)[0] > SCREEN_WIDTH:
                if self.font_small.getsize(opening_text)[0] > SCREEN_WIDTH:
                    split = opening_text.split(" ")
                    middle = int(len(split) / 2)
                    opening_text = (
                        " ".join(split[:middle]) + "\n" + " ".join(split[middle:])
                    )
                self.canvas_draw.multiline_text(
                    banner_pos,
                    opening_text,
                    font=self.font_small,
                    anchor="ma",
                    spacing=-2,
                )
            else:
                self.canvas_draw.text(
                    banner_pos,
                    opening_text,
                    font=self.font_medium_light,
                    anchor="ma",
                )

        if state == "game_exit":
            return "exit"
        return None

    def clear_state(self):
        self.init_state = True

    def process_init(self):
        pass

    @staticmethod
    def process_finish():
        time.sleep(0.001)
