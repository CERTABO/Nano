import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Union

import pygame
from chess import SQUARE_NAMES

import cfg
from utils import media
from utils.logger import get_logger
from utils.media import (
    COLORS,
    RadioOption,
    coords_in,
    create_button,
    play_audio,
    show_sprite,
    show_text,
)
from utils.reader_writer import COLUMNS_LETTERS, FEN_SPRITE_MAPPING

log = get_logger()


class DisplayPygame:
    def __init__(self, game_clock=None):
        self.game_clock = game_clock

        self.buttons_index = {}
        self.x, self.y = None, None
        self.engine_choice_menu = None
        self.avatar_weights_menu = None
        self.book_choice_menu = None
        self.first_saved_game = 0

        # Smal: new addition to handle radio options and help improve performance
        self.init_state = True
        self.ui_cache: Dict[str, Union[RadioOption, List[RadioOption]]] = {}
        self.ui_active: List[str] = []

        self.last_move_counter = 0
        self.animate_move = None
        self.animate_move_fen = None
        self.animate_move_piece = None
        self.animate_move_frame = 0

        self.poweroff_time = datetime.now()

        if cfg.DEBUG_FPS:
            self.fps_clock = pygame.time.Clock()

        xresolution = "auto"
        fullscreen = False
        with open("screen.ini", "r", encoding="utf-8") as file:
            try:
                xresolution = file.readline().split(" #")[0].strip()
                if xresolution != "auto":
                    xresolution = int(xresolution)
            # pylint: disable=broad-except
            except Exception as exc:
                # pylint: enable=broad-except
                log.warning(
                    f"Cannot read resolution from first line of screen.ini: {exc}"
                )

            try:
                fullscreen_string = file.readline().split(" #")[0].strip()
                if fullscreen_string == "fullscreen":
                    fullscreen = True
            # pylint: disable=broad-except
            except Exception as exc:
                # pylint: enable=broad-except
                log.warning(
                    f"Cannot read 'fullscreen' or 'window' from second line of screen.ini: {exc}"
                )

        icon = pygame.image.load("certabo.png")
        pygame.display.set_icon(icon)

        os.environ["SDL_VIDEO_CENTERED"] = "1"
        # os.environ['SDL_AUDIODRIVER'] = 'dsp'
        try:
            pygame.mixer.init()
        except pygame.error as exc:
            log.error(f"Failed to load audio driver {exc}")

        pygame.init()

        # auto reduce a screen's resolution
        dispaly_info = pygame.display.Info()
        xmax, ymax = dispaly_info.current_w, dispaly_info.current_h
        log.debug(f"Screen size = {xmax}px x {ymax}px")

        sprite_resolutions = (1920, 1366, 1024, 800, 480)
        window_sizes = ((1500, 1000), (900, 600), (800, 533), (625, 417), (480, 320))

        # Check if screen.ini resolution is not too large for user screen
        if xresolution != "auto":
            try:
                index = sprite_resolutions.index(xresolution)
            except ValueError:
                log.warning(
                    f"Resolution defined on screen.ini = {xresolution} not supported. "
                    "Defaulting to 'auto'"
                )
                xresolution = "auto"
            else:
                x, y = window_sizes[index]
                if xmax >= x and ymax >= y:
                    screen_width = x
                    screen_height = y
                else:
                    log.warning(
                        f"Resolution defined on screen.ini = {xresolution} is too "
                        "large for the detected screen size. Defaulting to 'auto'."
                    )
                    xresolution = "auto"

        # Find largest resolution automatically
        if xresolution == "auto":
            if not fullscreen:
                ymax -= 100  # Leave 100px margin for os taskbar when not running in fullscreen

            for xres, (x, y) in zip(sprite_resolutions, window_sizes):
                if xmax >= x and ymax >= y:
                    xresolution = xres
                    screen_width = x
                    screen_height = y
                    break
            else:  # Nobreak
                raise SystemError(
                    "Screen resolution is too small! Screen must be at least 480px x 320px."
                )

        log.debug(f"Running game with xresolution = {xresolution}")
        log.debug(
            f"Running game with window size = {screen_width}px x {screen_height}px"
        )

        cfg.xresolution = xresolution
        cfg.x_multiplier = screen_width / 480
        cfg.y_multiplier = screen_height / 320

        screen_options = pygame.HWSURFACE | pygame.DOUBLEBUF
        if fullscreen:
            screen_options |= pygame.FULLSCREEN
        cfg.scr = pygame.display.set_mode(
            (screen_width, screen_height), screen_options, 32
        )
        pygame.display.set_caption("Chess software")
        pygame.display.flip()  # copy to screen

        media.load_sprites(xresolution)
        media.load_audio()
        media.load_fonts()

        # change mouse cursor to be invisible - not needed for Windows!
        if cfg.args.hide_cursor:
            mc_strings = (
                "        ",
                "        ",
                "        ",
                "        ",
                "        ",
                "        ",
                "        ",
                "        ",
            )
            cursor, mask = pygame.cursors.compile(mc_strings)
            cursor_sizer = ((8, 8), (0, 0), cursor, mask)
            pygame.mouse.set_cursor(*cursor_sizer)

    @staticmethod
    def quit():
        log.debug("Quitting Pygame display")
        pygame.display.quit()
        pygame.quit()

    def _check_poweroff(self):
        if pygame.mouse.get_pressed()[0] and (self.x < 110) and (self.y < 101):
            if datetime.now() - self.poweroff_time >= timedelta(seconds=2):
                return True
        else:
            self.poweroff_time = datetime.now()
        return False

    def _check_input_events(self) -> Tuple[float, float, bool, Union[bool, str]]:
        left_click = False
        quit_program = False
        # button = None

        x, y = pygame.mouse.get_pos()
        x = x / cfg.x_multiplier
        y = y / cfg.y_multiplier

        for event in pygame.event.get():  # all values in event list
            if event.type == pygame.QUIT:
                quit_program = "window"
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_q:
                    quit_program = "key"
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                left_click = True
                # button = self.check_buttons()
        if self._check_poweroff():
            quit_program = "logo"

        return x, y, left_click, quit_program

    @staticmethod
    def _show_board(fen_string, *, rotate):
        # Show chessboard using FEN string like
        # "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        x0, y0 = 178, 40
        show_sprite("chessboard_xy", x0, y0)

        fen_string = fen_string.split(" ")[0]
        if rotate:
            fen_string = fen_string[::-1]

        x, y = 0, 0
        for char in fen_string:
            if char in FEN_SPRITE_MAPPING:
                show_sprite(
                    FEN_SPRITE_MAPPING[char], x0 + 26 + 31.8 * x, y0 + 23 + y * 31.8
                )
                x += 1
            elif char == "/":  # new line
                x = 0
                y += 1
            elif char == "X":  # Missing piece
                x += 1
            else:
                x += int(char)

    def _show_board_and_animated_move(self, fen_string, *, rotate, frames=30):

        move = self.animate_move

        if move is None:
            self._show_board(fen_string, rotate=rotate)
            return

        piece = self.animate_move_piece
        if piece is None:
            raise ValueError
        self._show_board(self.animate_move_fen, rotate=rotate)

        start_col = COLUMNS_LETTERS.index(move[0])
        start_row = 8 - int(move[1])
        end_col = COLUMNS_LETTERS.index(move[2])
        end_row = 8 - int(move[3])
        x0, y0 = 178, 40

        if rotate:
            start_col = 7 - start_col
            start_row = 7 - start_row
            end_col = 7 - end_col
            end_row = 7 - end_row

        xstart, ystart = x0 + 26 + 31.8 * start_col, y0 + 23 + start_row * 31.8
        xend, yend = x0 + 26 + 31.8 * end_col, y0 + 23 + end_row * 31.8

        # Interpolate piece position based on frame
        piecex = xstart + (xend - xstart) * self.animate_move_frame / frames
        piecey = ystart + (yend - ystart) * self.animate_move_frame / frames
        show_sprite(piece, piecex, piecey)

        # Increment current frame and stop animation if at end
        self.animate_move_frame += 1
        if self.animate_move_frame >= frames:
            self.animate_move = None

    def _display_clock(self):
        clock = self.game_clock
        if clock is None:
            return

        if clock.time_constraint == "unlimited":
            return

        cols = [110]
        rows = [5, 40]

        black_minutes = int(clock.time_black_left // 60)
        black_seconds = int(clock.time_black_left % 60)
        color = COLORS["grey"]
        if clock.time_black_left < clock.time_warning_threshold:
            color = COLORS["red"]
        create_button(
            f"{black_minutes:02d}:{black_seconds:02d}",
            cols[0],
            rows[0],
            color=color,
            text_color=COLORS["white"],
            padding=(1, 1, 1, 1),
        )

        white_minutes = int(clock.time_white_left // 60)
        white_seconds = int(clock.time_white_left % 60)
        color = COLORS["lightestgrey"]
        if clock.time_white_left < clock.time_warning_threshold:
            color = COLORS["red"]
        create_button(
            f"{white_minutes:02d}:{white_seconds:02d}",
            cols[0],
            rows[1],
            color=color,
            text_color=COLORS["black"],
            padding=(1, 1, 1, 1),
        )

    def _check_option_buttons(self, x, y) -> Optional[str]:
        for button_name, button in self.ui_cache.items():
            if button_name in self.ui_active:
                if isinstance(button, RadioOption):
                    if button.click(x, y):
                        return f"{button_name}_{button.value}"
                else:
                    for nested_button in button:
                        if nested_button.click(x, y):
                            return f"{button_name}_{nested_button.value}"

        return None

    def _draw_option_buttons(self):
        for button_name, button in self.ui_cache.items():
            if button_name in self.ui_active:
                if isinstance(button, RadioOption):
                    button.draw()
                else:
                    for nested_button in button:
                        nested_button.draw()

    def _register_option_button(self, name, item,active=True):
        self.ui_cache[name] = item
        if active:
            self.ui_active.append(name)

    def _unregister_option_button(self, name):
        self.ui_cache.pop(name)
        if name in self.ui_active:
            self.ui_active.remove(name)

    def _clear_cache(self):
        self.ui_cache.clear()
        self.ui_active.clear()

    def _check_buttons(self, x, y):
        for button, button_area in self.buttons_index.items():
            if coords_in(x, y, button_area):
                return button
        return None

    def _register_button(self, name, *args, **kwargs):
        self.buttons_index[name] = show_sprite(name, *args, **kwargs)

    def _register_custom_button(self, name, *args, **kwargs):
        self.buttons_index[name] = create_button(*args, **kwargs)

    def _unregister_button(self, name):
        self.buttons_index.pop(name)

    def _clear_buttons(self):
        self.buttons_index = {}

    def clear_state(self):
        self._clear_cache()
        self.init_state = True

    # pylint: disable=too-many-return-statements
    def process_window(
        self, state: str, settings: Optional[dict] = None
    ) -> Tuple[str, Union[str, bool]]:
        self._clear_buttons()
        x, y, left_click, quit_program = self._check_input_events()
        self.x, self.y = x, y

        if state == "init":
            cfg.scr.fill(COLORS["white"])
            show_sprite("start-up-logo", 7, 0)

        elif state == "init_connection":
            cfg.scr.fill(COLORS["white"])
            show_sprite("start-up-logo", 7, 0)
            if self.init_state:
                self._register_option_button(
                    "connection_method",
                    media.RadioOption(
                        "Connect via:",
                        settings["_certabo_settings"],
                        "connection_method",
                        options=["usb", "bluetooth"],
                        x0=360,
                        y0=10,
                        x1=340,
                        y1=40,
                        font=cfg.font_large,
                    ),
                )

        elif state == "startup_leds":
            cfg.scr.fill(COLORS["white"])
            show_sprite("start-up-logo", 7, 0)

        # Main game states
        elif state == "home":
            # if self.init_state:
            first_button_y = 125
            button_spacing_y = 38
            self._register_button("new_game", 5, first_button_y)
            self._register_button(
                "resume_game", 5, first_button_y + button_spacing_y * 1
            )
            self._register_button(
                "calibration", 5, first_button_y + button_spacing_y * 2
            )
            self._register_button("options", 5, first_button_y + button_spacing_y * 3)
            self._register_button("lichess", 5, first_button_y + button_spacing_y * 4)
            show_sprite("welcome", 111, 6)

            self._show_board(settings["physical_chessboard_fen"], rotate=False)

        elif state == "calibration_menu":
            first_button_y = 125
            button_spacing_y = 38
            self._register_button("setup", 5, first_button_y + button_spacing_y * 1)
            self._register_button("new-setup", 5, first_button_y + button_spacing_y * 2)
            self._register_button("done", 5, first_button_y + button_spacing_y * 4)
            self._show_board(settings["physical_chessboard_fen"], rotate=False)
            show_sprite("welcome", 111, 6)

        elif state in ("calibration", "calibration_return_home", "calibration_partial"):
            self._show_board(settings["physical_chessboard_fen"], rotate=False)
            show_sprite("welcome", 111, 6)
            show_sprite("please-wait", 253, 170)

        elif state == "new_game":
            # TODO: Switch logic to use radiooptions instead
            game_settings = settings
            cols = [20, 150, 190, 280, 460]
            rows = [15, 60, 105, 150, 195, 225, 255, 270]

            txt_x, _ = show_text(
                "Mode:", cols[1], rows[0] + 5, COLORS["grey"], fontsize="large"
            )
            self._register_custom_button(
                "human_game",
                "Human",
                txt_x + 15,
                rows[0],
                text_color=COLORS["white"],
                color=COLORS["darkergreen"]
                if game_settings["human_game"]
                else COLORS["lightgrey"],
            )
            self._register_custom_button(
                "computer_game",
                "Engine",
                self.buttons_index["human_game"][2] + 5,
                rows[0],
                text_color=COLORS["white"],
                color=COLORS["darkergreen"]
                if not game_settings["human_game"]
                else COLORS["lightgrey"],
            )
            self._register_custom_button(
                "flip_board",
                "Flip board",
                self.buttons_index["computer_game"][2] + 5,
                rows[0],
                text_color=COLORS["white"],
                color=COLORS["darkergreen"]
                if game_settings["rotate180"]
                else COLORS["lightgrey"],
            )
            self._register_custom_button(
                "use_board_position",
                "Use board position",
                cols[1],
                rows[1],
                text_color=COLORS["white"],
                color=COLORS["darkergreen"]
                if game_settings["use_board_position"]
                else COLORS["lightgrey"],
            )

            if game_settings["use_board_position"]:
                white_to_move = game_settings["side_to_move"] == "white"
                self._register_custom_button(
                    "side_to_move",
                    "White to move" if white_to_move else "Black to move",
                    self.buttons_index["use_board_position"][2] + 5,
                    rows[1],
                    text_color=COLORS["black"] if white_to_move else COLORS["white"],
                    color=COLORS["lightestgrey"] if white_to_move else COLORS["black"],
                )

            txt_x, _ = show_text(
                "Time:", cols[1], rows[2] + 5, COLORS["grey"], fontsize="large"
            )
            time_constraint = game_settings["time_constraint"]
            self._register_custom_button(
                "time_unlimited",
                "\u221E",
                txt_x + 5,
                rows[2],
                text_color=COLORS["white"],
                color=COLORS["darkergreen"]
                if time_constraint == "unlimited"
                else COLORS["lightgrey"],
                padding=(5, 10, 5, 10),
            )
            h_gap = 4
            self._register_custom_button(
                "time_blitz",
                "5+0",
                self.buttons_index["time_unlimited"][2] + h_gap,
                rows[2],
                text_color=COLORS["white"],
                color=COLORS["darkergreen"]
                if time_constraint == "blitz"
                else COLORS["lightgrey"],
            )
            self._register_custom_button(
                "time_rapid",
                "10+0",
                self.buttons_index["time_blitz"][2] + h_gap,
                rows[2],
                text_color=COLORS["white"],
                color=COLORS["darkergreen"]
                if time_constraint == "rapid"
                else COLORS["lightgrey"],
            )
            self._register_custom_button(
                "time_classical",
                "15+15",
                self.buttons_index["time_rapid"][2] + h_gap,
                rows[2],
                text_color=COLORS["white"],
                color=COLORS["darkergreen"]
                if time_constraint == "classical"
                else COLORS["lightgrey"],
            )
            self._register_custom_button(
                "time_custom",
                "Other",
                self.buttons_index["time_classical"][2] + h_gap,
                rows[2],
                text_color=COLORS["white"],
                color=COLORS["darkergreen"]
                if time_constraint == "custom"
                else COLORS["lightgrey"],
            )

            self._register_custom_button(
                "chess960",
                "Chess960",
                cols[1],
                rows[3],
                text_color=COLORS["white"],
                color=COLORS["darkergreen"]
                if game_settings["chess960"]
                else COLORS["lightgrey"],
            )

            if game_settings["syzygy_available"]:
                self._register_custom_button(
                    "syzygy",
                    "Syzygy",
                    self.buttons_index["chess960"][2] + 5,
                    rows[3],
                    text_color=COLORS["white"],
                    color=COLORS["darkergreen"]
                    if game_settings["syzygy_enabled"]
                    else COLORS["lightgrey"],
                )

            if not game_settings["human_game"]:
                engine_repr = game_settings["_game_engine"]["engine"]
                weights = game_settings["_game_engine"]["weights"]
                if weights is not None:
                    engine_repr = f"{engine_repr} {{{weights}}}"
                if len(engine_repr) > 20:
                    engine_repr = f"{engine_repr[:20]}..."
                show_text(
                    f"Engine: {engine_repr}",
                    cols[1],
                    rows[4] + 5,
                    COLORS["grey"],
                    fontsize="large",
                )
                self._register_custom_button(
                    "select_engine",
                    "...",
                    cols[-1],
                    rows[4],
                    text_color=COLORS["white"],
                    color=COLORS["darkergreen"],
                    padding=(0, 5, 0, 5),
                    align="right",
                )

                book_repr = game_settings["book"]
                if len(book_repr) > 20:
                    book_repr = f"{book_repr[:20]}..."
                _, _ = show_text(
                    f"Book: {book_repr}",
                    cols[1],
                    rows[5] + 5,
                    COLORS["grey"],
                    fontsize="large",
                )
                self._register_custom_button(
                    "select_book",
                    "...",
                    cols[-1],
                    rows[5],
                    text_color=COLORS["white"],
                    color=COLORS["darkergreen"],
                    padding=(0, 5, 0, 5),
                    align="right",
                )

                txt_x, _ = show_text("Depth:", cols[0], rows[4] + 8, COLORS["grey"])
                difficulty_button_area = create_button(
                    f"{game_settings['_game_engine']['Depth']:02d}",
                    cols[0] + 20,
                    rows[5],
                    color=COLORS["green"],
                    text_color=COLORS["white"],
                )
                self._register_custom_button(
                    "depth_less",
                    "<",
                    difficulty_button_area[0] - 5,
                    rows[5],
                    text_color=COLORS["white"],
                    color=COLORS["lightgrey"],
                    align="right",
                )
                self._register_custom_button(
                    "depth_more",
                    ">",
                    difficulty_button_area[2] + 5,
                    rows[5],
                    text_color=COLORS["white"],
                    color=COLORS["lightgrey"],
                )

                x0 = txt_x + 5
                y0 = rows[4] + 8

                if game_settings["_game_engine"]["Depth"] == 1:
                    difficulty_label = "Easiest"
                elif game_settings["_game_engine"]["Depth"] < 5:
                    difficulty_label = "Easy"
                elif game_settings["_game_engine"]["Depth"] > 19:
                    difficulty_label = "Hardest"
                elif game_settings["_game_engine"]["Depth"] > 10:
                    difficulty_label = "Hard"
                else:
                    difficulty_label = "Normal"
                show_text(difficulty_label, x0, y0, COLORS["green"])

                txt_x, _ = show_text(
                    "Play as:", cols[1], rows[6] + 5, COLORS["green"], fontsize="large"
                )
                sprite_color = "black"
                if game_settings["play_white"]:
                    sprite_color = "white"
                self._register_button(sprite_color, txt_x + 5, rows[6])

            self._register_button("back", cols[0], rows[-1])
            self._register_button("start", cols[-1] - 100, rows[-1])

        elif state == "select_time":
            time_total_minutes = settings["time_total_minutes"]
            time_increment_seconds = settings["time_increment_seconds"]

            cols = [150, 195]
            rows = [15, 70, 105, 160, 200]

            show_sprite("hide_back", 0, 0)

            create_button(
                "Custom Time Settings",
                cols[0],
                rows[0],
                color=COLORS["green"],
                text_color=COLORS["white"],
            )

            show_text(
                "Minutes per side:", cols[0], rows[1], COLORS["black"], fontsize="large"
            )
            minutes_button_area = create_button(
                str(time_total_minutes),
                cols[1],
                rows[2],
                color=COLORS["grey"],
                text_color=COLORS["white"],
            )
            self._register_custom_button(
                "minutes_less",
                "<",
                minutes_button_area[0] - 5,
                rows[2],
                text_color=COLORS["grey"],
                color=COLORS["white"],
                align="right",
                padding=(5, 2, 5, 2),
            )
            self._register_custom_button(
                "minutes_less2",
                "<<",
                self.buttons_index["minutes_less"][0] - 5,
                rows[2],
                text_color=COLORS["grey"],
                color=COLORS["white"],
                align="right",
                padding=(5, 0, 5, 0),
            )
            self._register_custom_button(
                "minutes_more",
                ">",
                minutes_button_area[2] + 5,
                rows[2],
                text_color=COLORS["grey"],
                color=COLORS["white"],
                padding=(5, 2, 5, 2),
            )
            self._register_custom_button(
                "minutes_more2",
                ">>",
                self.buttons_index["minutes_more"][2] + 5,
                rows[2],
                text_color=COLORS["grey"],
                color=COLORS["white"],
                padding=(5, 0, 5, 0),
            )

            show_text(
                "Increment in seconds:",
                cols[0],
                rows[3],
                COLORS["black"],
                fontsize="large",
            )
            seconds_button_area = create_button(
                str(time_increment_seconds),
                cols[1],
                rows[4],
                color=COLORS["grey"],
                text_color=COLORS["white"],
            )
            self._register_custom_button(
                "seconds_less",
                "<",
                seconds_button_area[0] - 5,
                rows[4],
                text_color=COLORS["grey"],
                color=COLORS["white"],
                align="right",
                padding=(5, 2, 5, 2),
            )
            self._register_custom_button(
                "seconds_less2",
                "<<",
                self.buttons_index["seconds_less"][0] - 5,
                rows[4],
                text_color=COLORS["grey"],
                color=COLORS["white"],
                align="right",
                padding=(5, 0, 5, 0),
            )
            self._register_custom_button(
                "seconds_more",
                ">",
                seconds_button_area[2] + 5,
                rows[4],
                text_color=COLORS["grey"],
                color=COLORS["white"],
                padding=(5, 2, 5, 2),
            )
            self._register_custom_button(
                "seconds_more2",
                ">>",
                self.buttons_index["seconds_more"][2] + 5,
                rows[4],
                text_color=COLORS["grey"],
                color=COLORS["white"],
                padding=(5, 0, 5, 0),
            )
            self._register_custom_button(
                "done",
                "Done",
                415,
                275,
                color=COLORS["darkergreen"],
                text_color=COLORS["white"],
            )

        elif state == "select_engine":
            if self.engine_choice_menu is None:
                self.engine_choice_menu = media.ListOption(
                    "Select game engine:",
                    settings["_game_engine"],
                    "engine",
                    settings["_game_engine"]["engine_list"],
                    x0=160,
                    y0=20,
                    x1=160,
                    y1=50,
                    font=cfg.font_large,
                )
            self.engine_choice_menu.update_options(
                settings["_game_engine"]["engine_list"]
            )
            self.engine_choice_menu.draw()
            if left_click:
                self.engine_choice_menu.click(x, y)
                if not self.engine_choice_menu.open:
                    return "done", quit_program
                elif self.engine_choice_menu.value == "avatar":
                    return "avatar", quit_program
                else:
                    return None, quit_program

        elif state == "select_weights":
            if self.avatar_weights_menu is None:
                self.avatar_weights_menu = media.ListOption(
                    "Select engine weights:",
                    settings["_game_engine"],
                    "weights",
                    settings["_game_engine"]["weights_list"],
                    x0=160,
                    y0=20,
                    x1=160,
                    y1=50,
                    font=cfg.font_large,
                )
            self.avatar_weights_menu.update_options(
                settings["_game_engine"]["weights_list"]
            )
            self.avatar_weights_menu.draw()
            if left_click:
                self.avatar_weights_menu.click(x, y)
                if not self.avatar_weights_menu.open:
                    return "done", quit_program
                else:
                    return None, quit_program

        elif state == "select_book":
            if self.book_choice_menu is None:
                self.book_choice_menu = media.ListOption(
                    "Select book:",
                    settings,
                    "book",
                    settings["book_list"],
                    x0=160,
                    y0=20,
                    x1=160,
                    y1=50,
                    font=cfg.font_large,
                    null_value="",
                )
            self.book_choice_menu.update_options(settings["book_list"])
            self.book_choice_menu.draw()
            if left_click:
                self.book_choice_menu.click(x, y)
                if not self.book_choice_menu.open:
                    return "done", quit_program
                else:
                    return None, quit_program

        elif state in ("resume_game", "delete_game"):
            # Base
            show_text(
                "Select game name to resume", 159, 1, COLORS["black"], fontsize="large"
            )
            show_sprite("resume_back", 107, 34)

            # Compute displayed files offset
            saved_games = settings["_saved_games"]
            n_files = len(saved_games["filenames"])
            last_idx = min(max(saved_games["selected_idx"] + 3, 8), n_files)
            first_idx = max(0, last_idx - 8)
            selected_offset = saved_games["selected_idx"] - first_idx

            # Selection shading
            pygame.draw.rect(
                cfg.scr,
                COLORS["lightestgrey"],
                (
                    int(113 * cfg.x_multiplier),
                    int(
                        41 * cfg.y_multiplier + selected_offset * 29 * cfg.y_multiplier
                    ),
                    int(330 * cfg.x_multiplier),
                    int(30 * cfg.y_multiplier),
                ),
            )

            # Filenames and datetimes
            for row, idx in enumerate(range(first_idx, last_idx)):
                show_text(
                    saved_games["filenames"][idx][:-4],
                    117,
                    41 + row * 29,
                    COLORS["grey"],
                    fontsize="large",
                )
                date = saved_games["datetimes"][idx]
                # pylint: disable=consider-using-f-string
                show_text(
                    "{:d}-{:d}-{:d}  {:d}:{:d}".format(
                        date.tm_year,
                        date.tm_mon,
                        date.tm_mday,
                        date.tm_hour,
                        date.tm_min,
                    ),
                    300,
                    41 + row * 29,
                    COLORS["lightgrey"],
                    fontsize="large",
                )
                # pylint: enable=consider-using-f-string

            if state == "resume_game":
                self._register_button("resume_game", 263, 283)
                self._register_button("back", 3, 146)
                self._register_button("delete-game", 103, 283)

                if left_click:
                    # pressed on file list
                    if (107 < x < 442) and (40 < y < 274):
                        i = int((int(y) - 41) / 29)
                        idx = i + first_idx
                        if idx < n_files:
                            saved_games["selected_idx"] = idx

                    if 448 < x < 472:  # arrows
                        if 37 < y < 60:  # arrow
                            saved_games["selected_idx"] = max(
                                0, saved_games["selected_idx"] - 1
                            )
                        elif 253 < y < 284:
                            saved_games["selected_idx"] = min(
                                n_files - 1, saved_games["selected_idx"] + 1
                            )

            # delete_game
            else:
                show_sprite("hide_back", 0, 0)
                pygame.draw.rect(
                    cfg.scr,
                    COLORS["lightgrey"],
                    (
                        int(202 * cfg.x_multiplier),
                        int(79 * cfg.y_multiplier),
                        int(220 * cfg.x_multiplier),
                        int(78 * cfg.y_multiplier),
                    ),
                )
                pygame.draw.rect(
                    cfg.scr,
                    COLORS["white"],
                    (
                        int(200 * cfg.x_multiplier),
                        int(77 * cfg.y_multiplier),
                        int(220 * cfg.x_multiplier),
                        int(78 * cfg.y_multiplier),
                    ),
                )
                show_text(
                    "Delete the game ?",
                    200 + 32,
                    67 + 15,
                    COLORS["grey"],
                    fontsize="large",
                )
                self._register_button("back", 200 + 4, 77 + 40)
                self._register_button("confirm", 200 + 120, 77 + 40)

        elif state == "save":
            name_to_save = settings["name_to_save"]
            show_text(
                "Enter game name to save", 159, 41, COLORS["grey"], fontsize="large"
            )
            show_sprite("terminal", 139, 80)
            show_text(
                name_to_save,
                273 - len(name_to_save) * (51 / 10.0),
                86,
                COLORS["terminal_text_color"],
                fontsize="large",
            )

            # show keyboard
            keyboard_buttons = (
                ("1", "2", "3", "4", "5", "6", "7", "8", "9", "0", "-"),
                ("q", "w", "e", "r", "t", "y", "u", "i", "o", "p"),
                ("a", "s", "d", "f", "g", "h", "j", "k", "l"),
                ("z", "x", "c", "v", "b", "n", "m"),
            )

            lenx = 42  # size of buttons
            leny = 38  # size of buttons

            keyy = 128
            x0 = 11

            hover_key = None

            pygame.draw.rect(
                cfg.scr,
                COLORS["lightgrey"],
                (
                    int(431 * cfg.x_multiplier),
                    int(81 * cfg.y_multiplier),
                    int(lenx * cfg.x_multiplier - 2),
                    int(leny * cfg.y_multiplier - 2),
                ),
            )  # back space
            show_text("<", (431 + 14), (81 + 4), COLORS["black"], fontsize="large")

            for row in keyboard_buttons:
                keyx = x0
                for key in row:
                    pygame.draw.rect(
                        cfg.scr,
                        COLORS["lightgrey"],
                        (
                            int(keyx * cfg.x_multiplier),
                            int(keyy * cfg.y_multiplier),
                            int(lenx * cfg.x_multiplier - 2),
                            int(leny * cfg.y_multiplier - 2),
                        ),
                    )
                    show_text(
                        key, keyx + 14, keyy + 4, COLORS["black"], fontsize="large"
                    )
                    if keyx < x < (keyx + lenx) and keyy < y < (keyy + leny):
                        hover_key = key
                    keyx += lenx
                keyy += leny
                x0 += 20

            pygame.draw.rect(
                cfg.scr,
                COLORS["lightgrey"],
                (
                    int(x0 * cfg.x_multiplier + lenx * cfg.x_multiplier),
                    int(keyy * cfg.y_multiplier),
                    int(188 * cfg.x_multiplier),
                    int(leny * cfg.y_multiplier - 2),
                ),
            )  # spacebar
            if (x0 + lenx) < x < (x0 + lenx + 188) and keyy < y < (keyy + leny):
                hover_key = " "
            self._register_button("save", 388, 264)
            if 431 < x < (431 + lenx) and 81 < y < (81 + leny):
                hover_key = "<"

            if left_click:
                if hover_key is not None:
                    if hover_key == "<":
                        if len(name_to_save) > 0:
                            settings["name_to_save"] = name_to_save[
                                : len(name_to_save) - 1
                            ]
                    elif len(name_to_save) < 22:
                        settings["name_to_save"] += hover_key

        elif state.startswith("game"):
            # Check if board changed (for starting or interrupting animations)
            len_moves = len(settings["virtual_chessboard"].move_stack)
            if len_moves != self.last_move_counter:
                if len_moves > self.last_move_counter:
                    board = settings["virtual_chessboard"].copy()
                    self.animate_move = str(board.pop())
                    square = SQUARE_NAMES.index(self.animate_move[:2])
                    self.animate_move_piece = FEN_SPRITE_MAPPING[
                        str(board.piece_at(square))
                    ]
                    board.remove_piece_at(square)
                    self.animate_move_fen = board.fen()
                    self.animate_move_frame = 0

                    play_audio("move")
                else:
                    self.animate_move = None
                    self.animate_move_fen = None
                    self.animate_move_piece = None
                    self.animate_move_frame = 0

                self.last_move_counter = len_moves

            self._show_board_and_animated_move(
                settings["virtual_chessboard"].fen(), rotate=settings["rotate180"]
            )

            self._display_clock()
            show_sprite("terminal", 179, 3)

            terminal_y = 6  # y position of first line
            terminal_l = 2  # number of lines to print
            for i in range(terminal_l, 0, -1):
                if i <= len(settings["terminal_lines"]):
                    show_text(
                        settings["terminal_lines"][-i],
                        183,
                        terminal_y,
                        COLORS["terminal_text_color"],
                    )
                    terminal_y += 13

            self._register_button("save", 5, 140 + 140)
            self._register_button("exit", 5 + 80, 140 + 140)

            # Hint and analysis
            if (
                not settings["show_extended_analysis"]
                and not settings["show_extended_hint"]
            ):
                if not settings["_game_engine"]["is_rom"]:
                    self._register_button("take_back", 5, 140 + 22)
                self._register_button("hint", 5, 140 + 40 + 22)
                self._register_button("analysis", 5, 140 + 100)

                if settings["show_hint"]:
                    bestmove = settings["hint_engine"].get_latest_bestmove()
                    if bestmove is None:
                        bestmove = "..."
                    bestmove = bestmove.center(9)
                    show_text(bestmove, 92, 212, COLORS["grey"])
                    # Extended hint is only avaliable in non-human games
                    if not settings["human_game"]:
                        self._register_custom_button(
                            "extended_hint",
                            "+",
                            178 - 25,
                            207,
                            color=COLORS["grey"],
                            text_color=COLORS["white"],
                            padding=[0, 5, 0, 5],
                        )
                if settings["show_analysis"]:
                    analysis_score = settings["analysis_engine"].get_latest_score()
                    show_text(analysis_score, 92, 250, COLORS["grey"])
                    self._register_custom_button(
                        "extended_analysis",
                        "+",
                        178 - 25,
                        245,
                        color=COLORS["grey"],
                        text_color=COLORS["white"],
                        padding=[0, 5, 0, 5],
                    )
            elif settings["show_extended_hint"]:
                self._register_button("hint", 5, 140 + 100)

                settings["hint_engine"].plot_extended_hint(
                    settings["virtual_chessboard"]
                )
                bestmove = settings["hint_engine"].get_latest_bestmove(
                    return_incomplete=True
                )
                if bestmove is None:
                    bestmove = "..."
                bestmove = bestmove.center(9)
                show_text(bestmove, 92, 250, COLORS["grey"])

                self._register_custom_button(
                    "extended_hint",
                    "x",
                    178 - 25,
                    245,
                    color=COLORS["grey"],
                    text_color=COLORS["white"],
                    padding=[0, 5, 0, 5],
                )
            elif settings["show_extended_analysis"]:
                self._register_button("analysis", 5, 140 + 100)
                settings["analysis_engine"].plot_extended_analysis(
                    settings["virtual_chessboard"]
                )  # check what this does
                analysis_score = settings["analysis_engine"].get_latest_score(
                    return_incomplete=True
                )  # check what this does
                show_text(analysis_score, 92, 250, COLORS["grey"])

                self._register_custom_button(
                    "extended_analysis",
                    "x",
                    178 - 25,
                    245,
                    color=COLORS["grey"],
                    text_color=COLORS["white"],
                    padding=[0, 5, 0, 5],
                )

            # Banners
            x0, y0 = 5, 127
            if state == "game_waiting_user_move":
                show_sprite("do-your-move", x0 + 2, y0 + 2)
            elif state == "game_pieces_wrong_place_ai_move":
                show_sprite("move-certabo", x0, y0 + 2)
            elif state.startswith("game_pieces_wrong_place"):
                show_sprite("place-pieces", x0, y0 + 2)
            elif state in (
                "game_resume",
                "game_do_user_move",
                "game_request_ai_move",
                "game_waiting_ai_move",
                "game_do_ai_move",
                "game_do_take_back",
                "game_exit",
                "game_over",
            ):
                pass
            else:
                raise ValueError(f"state={state}")

            if state == "game_exit":
                pygame.draw.rect(
                    cfg.scr,
                    COLORS["lightgrey"],
                    (
                        int(229 * cfg.x_multiplier),
                        int(79 * cfg.y_multiplier),
                        int(200 * cfg.x_multiplier),
                        int(78 * cfg.y_multiplier),
                    ),
                )
                pygame.draw.rect(
                    cfg.scr,
                    COLORS["white"],
                    (
                        int(227 * cfg.x_multiplier),
                        int(77 * cfg.y_multiplier),
                        int(200 * cfg.x_multiplier),
                        int(78 * cfg.y_multiplier),
                    ),
                )
                show_text("Save the game or not ?", 227 + 37, 77 + 15, COLORS["grey"])
                self._register_button("save", 238, 77 + 40)
                self._register_button("exit", 238 + 112, 77 + 40)

            if state == "game_waiting_ai_move":
                # Display force move banner
                pygame.draw.rect(
                    cfg.scr,
                    COLORS["lightgrey"],
                    (
                        int(229 * cfg.x_multiplier),
                        int(79 * cfg.y_multiplier),
                        int(200 * cfg.x_multiplier),
                        int(78 * cfg.y_multiplier),
                    ),
                )
                pygame.draw.rect(
                    cfg.scr,
                    COLORS["white"],
                    (
                        int(227 * cfg.x_multiplier),
                        int(77 * cfg.y_multiplier),
                        int(200 * cfg.x_multiplier),
                        int(78 * cfg.y_multiplier),
                    ),
                )
                show_text(
                    "Analysing...", 227 + 55, 77 + 8, COLORS["grey"], fontsize="large"
                )
                if not settings["_game_engine"]["is_rom"]:
                    self._register_button("force-move", 247, 77 + 39)

            if state == "game_over":
                if self.game_clock.game_overtime:
                    if self.game_clock.game_overtime_winner == 1:
                        create_button(
                            "White wins",
                            270,
                            97,
                            color=COLORS["grey"],
                            text_color=COLORS["white"],
                        )
                    else:
                        create_button(
                            "Black wins",
                            270,
                            97,
                            color=COLORS["grey"],
                            text_color=COLORS["white"],
                        )
                elif settings["virtual_chessboard"].is_game_over():
                    if settings["virtual_chessboard"].is_checkmate():
                        gameover_banner = "check-mate-banner"
                    elif settings["virtual_chessboard"].is_stalemate():
                        gameover_banner = "stale-mate-banner"
                    elif settings["virtual_chessboard"].is_fivefold_repetition():
                        gameover_banner = "five-fold-repetition-banner"
                    elif settings["virtual_chessboard"].is_seventyfive_moves():
                        gameover_banner = "seventy-five-moves-banner"
                    elif settings["virtual_chessboard"].is_insufficient_material():
                        gameover_banner = "insufficient-material-banner"
                    show_sprite(gameover_banner, 227, 97)

        elif state == "options":
            # ----------
            # Init UI cache
            # -----------
            if self.init_state:
                # Settings submenu selector
                self._register_option_button(
                    "settings_menu",
                    RadioOption(
                        "Settings",
                        {"dialog": "Game Engine"},
                        "dialog",
                        options=["Game Engine", "Analysis Engine", "Chessboard"],
                        y0=145,
                        x1=10,
                        y1=170,
                        vertical=True,
                        font=cfg.font_large,
                    ),
                )

                # 'Game Engine' Menu
                cols = [160, 235, 270, 380]
                rows = [0, 35, 70, 105, 140, 175, 225, 260]
                engine_settings = settings["_game_engine"]
                engine_settings_buttons = [
                    media.RangeOption(
                        "Depth:",
                        engine_settings,
                        "Depth",
                        min_=1,
                        max_=20,
                        x0=cols[0],
                        x1=cols[2],
                        y1=rows[1],
                    ),
                    media.RangeOption(
                        "Threads:",
                        engine_settings,
                        "Threads",
                        min_=1,
                        max_=512,
                        x0=cols[0],
                        x1=cols[2],
                        y1=rows[2],
                    ),
                    media.RangeOption(
                        "Contempt:",
                        engine_settings,
                        "Contempt",
                        min_=-100,
                        max_=100,
                        x0=cols[0],
                        x1=cols[2],
                        y1=rows[3],
                    ),
                    media.RadioOption(
                        "Ponder:",
                        engine_settings,
                        "Ponder",
                        options=[True, False],
                        x0=cols[0],
                        x1=cols[1],
                        y1=rows[4],
                    ),
                    media.RangeOption(
                        "Skill Level:",
                        engine_settings,
                        "Skill Level",
                        min_=0,
                        max_=20,
                        x0=cols[0],
                        x1=cols[2],
                        y1=rows[5],
                        subtitle="(Stockfish & Lc0)",
                    ),
                    media.RangeOption(
                        "Strength:",
                        engine_settings,
                        "Strength",
                        min_=0,
                        max_=100,
                        x0=cols[0],
                        x1=cols[2],
                        y1=rows[6],
                        subtitle="(Houdini)",
                    ),
                    
                ]
                self._register_option_button("Game Engine", engine_settings_buttons)

                # 'Analysis Engine' Menu
                cols = [160, 235, 270]
                rows = [0, 35, 70, 105, 140]

                engine_settings = settings["_analysis_engine"]
                game_analysis_buttons = [
                    media.RadioOption(
                        "Engine:",
                        engine_settings,
                        "engine",
                        options=settings["_game_engine"]["engine_list"],
                        x0=cols[0],
                        x1=cols[1],
                        y1=rows[1],
                    ),
                    media.RangeOption(
                        "Depth:",
                        engine_settings,
                        "Depth",
                        min_=1,
                        max_=20,
                        x0=cols[0],
                        x1=cols[2],
                        y1=rows[2],
                    ),
                    media.RangeOption(
                        "Threads:",
                        engine_settings,
                        "Threads",
                        min_=1,
                        max_=128,
                        x0=cols[0],
                        x1=cols[2],
                        y1=rows[3],
                    ),
                    media.RangeOption(
                        "Contempt:",
                        engine_settings,
                        "Contempt",
                        min_=-100,
                        max_=100,
                        x0=cols[0],
                        x1=cols[2],
                        y1=rows[4],
                    ),
                ]
                self._register_option_button("Analysis Engine", game_analysis_buttons,active=False)

                # 'Chessboard' Menu
                certabo_settings = settings["_certabo_settings"]
                certabo_settings_buttons = [
                    media.RadioOption(
                        "Remote control:",
                        certabo_settings,
                        "remote_control",
                        options=[True, False],
                        x0=cols[0],
                        x1=cols[2],
                        y1=rows[1],
                    ),
                    media.RadioOption(
                        "AI Thinking leds:",
                        settings["_led"],
                        "thinking",
                        options=["center", "corner", "none"],
                        x0=cols[0],
                        x1=cols[2],
                        y1=rows[2],
                    ),
                ]
                self._register_option_button("Chessboard", certabo_settings_buttons,active=False)

            self._register_button("done", 5, 277)
            self.ui_active = ["settings_menu", self.ui_cache["settings_menu"].value]
        else:
            raise ValueError(f"state={state}")

        # Draw option buttons
        self._draw_option_buttons()

        self.init_state = False

        action = None
        if left_click:
            action = self._check_buttons(x, y)
            if action is None:
                action = self._check_option_buttons(x, y)

        return action, quit_program

    # pylint: enable=too-many-return-statements

    @staticmethod
    def process_init():
        # Clear screen
        cfg.scr.fill(COLORS["white"])
        show_sprite("logo", 8, 6)

    def process_finish(self):
        if cfg.DEBUG_FPS:
            self.fps_clock.tick()
            fps = self.fps_clock.get_fps()
            show_text(f"FPS = {fps:.1f}", 5, 5, color=COLORS["black"])

        pygame.display.flip()
        time.sleep(0.001)
