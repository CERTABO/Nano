# TODO: Don't allow chess960, start from position, etc... when using roms
# TODO: Put main loop in it's own function
import json
import multiprocessing
import os
import platform
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import chess.pgn

import cfg
from utils import bluetoothtool, logger, pypolyglot, reader_writer, usbtool
from utils.analysis_engine import AnalysisEngine, GameEngine, HintEngine
from utils.game_clock import GameClock
from utils.get_books_engines import (
    CERTABO_SAVE_PATH,
    get_avatar_weights_list,
    get_book_list,
    get_engine_list,
    get_saved_games,
)
from utils.get_moves import get_moves, is_move_back
from utils.logger import CERTABO_DATA_PATH
from utils.messchess import RomEngine
from utils.publish import Publisher, generate_pgn

if not cfg.args.epaper:
    from utils.display_pygame import DisplayPygame as Display
    from utils.remote_control import RemoteControlPygame as RemoteControl
else:
    from utils.display_epaper import DisplayEpaper as Display
    from utils.remote_control import RemoteControlEpaper as RemoteControl

if __name__ == "__main__":
    multiprocessing.freeze_support()
    logger.set_logger()
    log = logger.get_logger()

    def do_poweroff(method=None):
        if method == "logo":
            log.info("Closing program via logo click")
        elif method == "key":
            log.info("Closing program via q key")
        elif method == "window":
            log.info("Closing program via window closed")
        elif method == "remote_control":
            log.info("Closing program via remote control")
        elif method == "interrupt":
            log.info("Closing program via interrupt")
        else:
            log.warning("Closing program via unknown method")

        for thread in (PUBLISHER, GAME_ENGINE, HINT_ENGINE, ANALYSIS_ENGINE):
            if thread is not None:
                thread.kill()

        try:
            CHESSBOARD_CONNECTION_PROCESS.kill()
            CHESSBOARD_CONNECTION_PROCESS.join(timeout=1)
        except (NameError, AttributeError):
            pass

        DISPLAY.quit()
        sys.exit()

    # TODO: Refactor this to display_pygame
    def terminal_print(terminal_lines, string, newline=True):
        """
        Print lines in virtual terminal. Does not repeat previous line
        """
        if not terminal_lines:
            terminal_lines.append(string)
        else:
            if newline:
                # If line is different than previous
                if string != terminal_lines[-1]:
                    terminal_lines.append(string)
            else:
                terminal_lines[-1] = f"{terminal_lines[-1]}{string}"

    def terminal_print_move(terminal_lines, turn, move):
        side = ("black", "white")[turn]
        if not cfg.args.epaper:
            terminal_print(terminal_lines, f"{side} move: {str(move)}")

    # ------------- Define initial variables

    # Loads settings into game_settings, returns False if failed
    def load_game_settings():
        if not os.path.exists(game_settings_filepath):
            return False
        else:
            log.debug(f"Loading game settings from {game_settings_filepath}")
            with open(game_settings_filepath, "r", encoding="utf-8") as file:
                saved_game_settings = json.load(file)
                for settings_key in ("_game_engine", "_analysis_engine", "_led"):
                    for key, value in saved_game_settings.get(settings_key, {}).items():
                        SETTINGS[settings_key][key] = value
        return True

    def load_certabo_settings():
        if not os.path.exists(certabo_settings_filepath):
            return False
        else:
            log.debug(f"Loading certabo settings from {certabo_settings_filepath}")
            with open(certabo_settings_filepath, "r", encoding="utf-8") as file:
                SETTINGS["_certabo_settings"] = json.load(file)
        return True

    def save_game_settings():
        log.debug(f"Saving game settings from {game_settings_filepath}")
        with open(game_settings_filepath, "w", encoding="utf-8") as file:
            json.dump(
                {
                    "_game_engine": SETTINGS["_game_engine"],
                    "_analysis_engine": SETTINGS["_analysis_engine"],
                    "_led": SETTINGS["_led"],
                },
                file,
            )

    def save_certabo_settings():
        log.debug(f"Saving certabo settings to {certabo_settings_filepath}")
        log.debug(f"Certabo_settings: {SETTINGS['_certabo_settings']}")
        with open(certabo_settings_filepath, "w", encoding="utf-8") as file:
            json.dump(SETTINGS["_certabo_settings"], file)

    # pylint: disable=used-before-assignment
    def switch_state(new_state):
        global STATE
        log.debug(f"Switching states: {STATE} -> {new_state}")
        STATE = new_state
        DISPLAY.clear_state()

        # If not in game (or save) window kill engines and reset UI options
        if not (STATE.startswith("game") or STATE == "save"):
            global PUBLISHER, GAME_ENGINE, HINT_ENGINE, ANALYSIS_ENGINE
            for thread in (PUBLISHER, GAME_ENGINE, HINT_ENGINE, ANALYSIS_ENGINE):
                if thread is not None:
                    thread.kill()
            PUBLISHER = GAME_ENGINE = HINT_ENGINE = ANALYSIS_ENGINE = None

            SETTINGS["show_hint"] = False
            SETTINGS["show_extended_hint"] = False
            SETTINGS["show_analysis"] = False
            SETTINGS["show_extended_analysis"] = False

    # pylint: enable=used-before-assignment

    if cfg.args.syzygy is None:
        cfg.args.syzygy = os.path.join(CERTABO_DATA_PATH, "syzygy")

    # Load game_settings
    SETTINGS = {
        "human_game": False,
        "rotate180": False,
        "use_board_position": False,
        "side_to_move": "white",
        "time_constraint": "unlimited",
        "time_total_minutes": 5,
        "time_increment_seconds": 8,
        "chess960": False,
        "syzygy_available": os.path.exists(cfg.args.syzygy),
        "syzygy_enabled": False,
        "book": "",
        "book_list": None,
        "play_white": True,
        "difficulty": "easy",
        # Using leading underscore to distinguish dictionaries
        "_game_engine": {
            "engine": "stockfish",
            "Depth": 1,
            "Threads": 1,
            "Contempt": 24,
            "Ponder": False,
            "Skill Level": 20,
            "Strength": 100,
            "weights": None,
            "is_rom": False,
        },
        "_analysis_engine": {
            "engine": "stockfish",
            "Depth": 20,
            "Threads": 1,
            "Contempt": 24,
            "Ponder": False,
        },
        "_led": {
            "thinking": "center",
        },
        "_certabo_settings": {
            "address_chessboard": None,
            "connection_method": "usb",
            "remote_control": False,
        },
        "_saved_games": {
            "filenames": [],
            "datetimes": None,
            "selected_idx": 0,
        },
        # State Variables
        "show_analysis": False,
        "show_extended_analysis": False,
        "show_hint": False,
        "show_extended_hint": False,
        "hint_engine": None,
        "analysis_engine": None,
        "name_to_save": "",
        "terminal_lines": ["Game started", "Terminal text here"],
        "virtual_chessboard": chess.Board(),
        "initial_chessboard": None,
        "physical_chessboard_fen": chess.STARTING_FEN,
        "physical_chessboard_fen_missing": chess.STARTING_FEN,
        "starting_position": chess.STARTING_FEN,
    }

    game_settings_filepath = os.path.join(CERTABO_DATA_PATH, "game_settings.json")
    if not load_game_settings():
        save_game_settings()

    # Load Certabo settings
    certabo_settings_filepath = os.path.join(
        logger.CERTABO_DATA_PATH, "certabo_settings.json"
    )
    if not load_certabo_settings():
        save_certabo_settings()

    if cfg.args.usbport is not None:
        SETTINGS["_certabo_settings"]["connection_method"] = "usb"
        SETTINGS["_certabo_settings"]["address_chessboard"] = cfg.args.usbport
        LAST_ADDRESS_CHESSBOARD = None
    elif cfg.args.btport is not None:
        SETTINGS["_certabo_settings"]["connection_method"] = "bluetooth"
        SETTINGS["_certabo_settings"]["address_chessboard"] = cfg.args.btport
        LAST_ADDRESS_CHESSBOARD = None
    else:
        SETTINGS["_certabo_settings"]["connection_method"] = SETTINGS[
            "_certabo_settings"
        ].get("connection_method", "usb")
        LAST_ADDRESS_CHESSBOARD = SETTINGS["_certabo_settings"].get(
            "address_chessboard", None
        )
        SETTINGS["_certabo_settings"]["address_chessboard"] = None
    LAST_CONNECTION_METHOD = SETTINGS["_certabo_settings"]["connection_method"]

    try:
        STATE = "init"
        MOVES = []
        RESUMING_NEW_GAME = False

        CHESSBOARD_CONNECTION_PROCESS = None
        BT_FIND_ADDRESS_EXECUTOR = None
        FUTURE_BT_ADDRESS = None
        CONNECTION_BUTTON = None
        SYSTEM = platform.system()

        GAME_CLOCK = GameClock()
        DISPLAY = Display(game_clock=GAME_CLOCK)
        PUBLISHER = None
        GAME_ENGINE = None
        HINT_ENGINE = None
        ANALYSIS_ENGINE = None
        USB_READER = None
        LED_MANAGER = None
        REMOTE_CONTROL = None

        AI_MOVE = None
        DEPLETED_BOOK = False

        INIT_TIMER = None
        CONNECTION_BUTTON_TIMER = None
        STARTUP_TIMER = None
        WAITING_AI_TIMER = None

        # ------------- Init loop
        while True:

            # Initialization ended
            if STATE in ("home", "calibration_return_home"):
                break

            DISPLAY.process_init()
            action, quit_program = DISPLAY.process_window(STATE, SETTINGS)

            if quit_program:
                do_poweroff(method=quit_program)

            if STATE in ("init", "init_connection"):
                # User changed connection method
                if action is not None and action.startswith("connection_method"):
                    SETTINGS["_certabo_settings"]["remote_control"] = (
                        SETTINGS["_certabo_settings"]["connection_method"]
                        == "bluetooth"
                    )
                    SETTINGS["_certabo_settings"]["address_chessboard"] = None
                    INIT_TIMER = None

                    # Close thread and processes that may have started for the other
                    # connection_method option
                    if FUTURE_BT_ADDRESS is not None:
                        FUTURE_BT_ADDRESS.cancel()
                        FUTURE_BT_ADDRESS = None
                    if CHESSBOARD_CONNECTION_PROCESS is not None:
                        CHESSBOARD_CONNECTION_PROCESS.kill()
                        CHESSBOARD_CONNECTION_PROCESS = None

                # If there is a timer set, wait it before trying to reconnect
                if (INIT_TIMER is None) or (time.time() > INIT_TIMER):

                    # Find chessboard address
                    if SETTINGS["_certabo_settings"]["address_chessboard"] is None:
                        if SETTINGS["_certabo_settings"]["connection_method"] == "usb":
                            SETTINGS["_certabo_settings"][
                                "address_chessboard"
                            ] = usbtool.find_address(
                                test_address=LAST_ADDRESS_CHESSBOARD
                            )
                        else:
                            # Bluettoth find_adress() has to be launched on another
                            # thread, as it takes a long time to run
                            if BT_FIND_ADDRESS_EXECUTOR is None:
                                BT_FIND_ADDRESS_EXECUTOR = ThreadPoolExecutor(
                                    max_workers=1
                                )

                            if FUTURE_BT_ADDRESS is None:
                                # ThreadPoolExecutor runs threads as non-daemon, so
                                # program may take a while to exit if
                                # bluetoothool.find_address is still running
                                FUTURE_BT_ADDRESS = BT_FIND_ADDRESS_EXECUTOR.submit(
                                    bluetoothtool.find_address,
                                    test_address=LAST_ADDRESS_CHESSBOARD,
                                )
                            else:
                                if FUTURE_BT_ADDRESS.done():
                                    SETTINGS["_certabo_settings"][
                                        "address_chessboard"
                                    ] = FUTURE_BT_ADDRESS.result()
                                    FUTURE_BT_ADDRESS = None

                        # Disable last_address_chessboard so that every possible
                        # address is checked next time
                        LAST_ADDRESS_CHESSBOARD = None
                        # Set 0.5 timer before attempting re-connection
                        INIT_TIMER = time.time() + 0.5

                    # Attempt new connection
                    if (
                        CHESSBOARD_CONNECTION_PROCESS is None
                        and SETTINGS["_certabo_settings"]["address_chessboard"]
                        is not None
                    ):
                        CONNECTION_TYPE = SETTINGS["_certabo_settings"][
                            "connection_method"
                        ]
                        CONNECTION_ADDRESS = SETTINGS["_certabo_settings"][
                            "address_chessboard"
                        ]
                        log.info(
                            f"Attempting {CONNECTION_TYPE} connection to {CONNECTION_ADDRESS}"
                        )
                        if CONNECTION_TYPE == "usb":
                            CHESSBOARD_CONNECTION_PROCESS = usbtool.start_usbtool(
                                CONNECTION_ADDRESS, separate_process=True
                            )
                        else:
                            CHESSBOARD_CONNECTION_PROCESS = (
                                bluetoothtool.start_bluetoothtool(
                                    CONNECTION_ADDRESS, separate_process=True
                                )
                            )

                    # Check if expected reading is obtained
                    # (future_bt_address should be None by now)
                    if (FUTURE_BT_ADDRESS is None) and (
                        not usbtool.QUEUE_FROM_USBTOOL.empty()
                    ):
                        log.info("Connected succesfully")
                        save_certabo_settings()
                        # Initialize modules
                        USB_READER = reader_writer.BoardReader(
                            SETTINGS["_certabo_settings"]["address_chessboard"]
                        )
                        LED_MANAGER = reader_writer.LedWriter()
                        REMOTE_CONTROL = RemoteControl(
                            LED_MANAGER, SETTINGS["_certabo_settings"]["remote_control"]
                        )
                        switch_state("startup_leds")

                    # If three seconds have elapsed without a successful connection
                    # Create and show connection method option button
                    elif STATE == "init":
                        # But only if no specific usbport or bt port was given,
                        # And if not on macOS, as bluetooth is not implemented yet
                        if (
                            cfg.args.usbport is None
                            and cfg.args.btport is None
                            and SYSTEM != "Darwin"
                        ):
                            if CONNECTION_BUTTON_TIMER is None:
                                CONNECTION_BUTTON_TIMER = time.time() + 3
                            elif time.time() > CONNECTION_BUTTON_TIMER:
                                switch_state("init_connection")
                    elif STATE == "init_connection":
                        pass
                    else:
                        raise ValueError(f"state={STATE}")

            elif STATE == "startup_leds":
                action, quit_program = DISPLAY.process_window(STATE, SETTINGS)
                IS_USB = (
                    SETTINGS["_certabo_settings"]["connection_method"] != "bluetooth"
                )

                if IS_USB and STARTUP_TIMER is None:
                    # Turn lights for 1.0 seconds if connecting via usb
                    LED_MANAGER.set_leds("all")
                    STARTUP_TIMER = time.time() + 1.0

                if not IS_USB or time.time() > STARTUP_TIMER:
                    LED_MANAGER.set_leds()

                    # Go to calibration if connection is new
                    if not USB_READER.needs_calibration:
                        switch_state("home")
                    else:
                        switch_state("calibration_return_home")

            else:
                raise ValueError(STATE)

            DISPLAY.process_finish()

        # ------------- Main loop
        while True:
            SETTINGS["hint_engine"] = HINT_ENGINE
            SETTINGS["analysis_engine"] = ANALYSIS_ENGINE
            SETTINGS["physical_chessboard_fen"] = USB_READER.read_board()
            SETTINGS["physical_chessboard_fen_missing"] = USB_READER.board_fen_missing

            DISPLAY.process_init()
            action, quit_program = DISPLAY.process_window(STATE, SETTINGS)

            if action is None and not quit_program:
                action, quit_program = REMOTE_CONTROL.process_state(STATE, SETTINGS)

            if quit_program:
                do_poweroff(quit_program)

            elif STATE == "home":

                if action == "new_game":
                    switch_state("new_game")
                    LED_MANAGER.set_leds()

                elif action == "resume_game":
                    switch_state("resume_game")
                    SETTINGS["_saved_games"].update(get_saved_games())

                elif action == "calibration":
                    switch_state("calibration_menu")

                elif action == "calibration_remote":
                    switch_state("calibration_return_home")

                elif action == "options":
                    SETTINGS["_game_engine"]["engine_list"] = get_engine_list()
                    switch_state("options")

                elif action == "lichess":  # online mode
                    # Kill usbtool
                    CHESSBOARD_CONNECTION_PROCESS.kill()
                    CHESSBOARD_CONNECTION_PROCESS.join()
                    time.sleep(0.750)

                    log.info("Switching to Online Application")
                    if (
                        SETTINGS["_certabo_settings"]["connection_method"]
                        == "bluetooth"
                    ):
                        args = sys.argv[1:] + [
                            "--btport",
                            SETTINGS["_certabo_settings"]["address_chessboard"],
                        ]
                    else:
                        args = sys.argv[1:] + [
                            "--usbport",
                            SETTINGS["_certabo_settings"]["address_chessboard"],
                        ]
                    if getattr(sys, "frozen", False):
                        executable = os.path.dirname(sys.executable)
                        executable = os.path.join(
                            executable,
                            f"online{'.exe' if SYSTEM == 'Windows' else ''}",
                        )
                        # Hack for windows paths with spaces!
                        os.execlp(executable, '"' + executable + '"', *args)
                    else:
                        os.execl(sys.executable, sys.executable, "online.py", *args)

            elif STATE == "calibration_menu":

                if action == "setup":
                    switch_state("calibration_partial")

                elif action == "new-setup":
                    switch_state("calibration")

                elif action == "done":
                    switch_state("home")

            elif STATE in (
                "calibration",
                "calibration_return_home",
                "calibration_return_new_game_wrong_place",
                "calibration_partial",
            ):
                CALIBRATION_DONE = USB_READER.calibration(
                    STATE != "calibration_partial",
                    verbose=False,
                )
                LED_MANAGER.set_leds("setup")
                if CALIBRATION_DONE:
                    LED_MANAGER.set_leds()
                    # Go back to home menu directly if calibration was triggered
                    # via new connection or remote control
                    if STATE == "calibration_return_home":
                        if not cfg.args.epaper:
                            switch_state("home")
                        else:
                            switch_state("new_game")
                    else:
                        switch_state("calibration_menu")

            elif STATE == "resume_game":
                if not action:
                    pass
                elif action == "back":
                    switch_state("home")
                elif action == "delete-game":
                    switch_state("delete_game")
                elif action == "resume_game":
                    filename = SETTINGS["_saved_games"]["filenames"][
                        SETTINGS["_saved_games"]["selected_idx"]
                    ]
                    game_filepath = os.path.join(CERTABO_SAVE_PATH, filename)
                    with open(game_filepath, "r", encoding="utf-8") as f:
                        saved_game = chess.pgn.read_game(f)
                    if saved_game:
                        SETTINGS["virtual_chessboard"] = saved_game.end().board()
                        node = saved_game
                        while node.variations:
                            node = node.variations[0]
                        SETTINGS["play_white"] = saved_game.headers["White"] == "Human"
                        SETTINGS["starting_position"] = saved_game.board().fen()

                        move_history = [
                            move.uci() for move in saved_game.mainline_moves()
                        ]
                        log.info(
                            f"Resuming game {filename}: Move history - {move_history}"
                        )

                        RESUMING_NEW_GAME = True
                        switch_state("new_game")
                else:
                    raise ValueError(action)

            elif STATE == "delete_game":

                if not action:
                    pass
                elif action == "back":
                    switch_state("resume_game")
                elif action == "confirm":
                    deleted_file = SETTINGS["_saved_games"]["filenames"][
                        SETTINGS["_saved_games"]["selected_idx"]
                    ]
                    log.info(f"Deleted game: {deleted_file}")
                    os.unlink(
                        os.path.join(
                            CERTABO_SAVE_PATH,
                            deleted_file,
                        )
                    )
                    SETTINGS["_saved_games"].update(get_saved_games())
                    switch_state("resume_game")
                else:
                    raise ValueError(action)

            elif STATE == "save":
                # name_to_save is edited by the display
                if action == "save":
                    saved_file = f"{SETTINGS['name_to_save']}.pgn"
                    log.info(f"Saved game: {saved_file}")
                    output_pgn_path = os.path.join(
                        CERTABO_SAVE_PATH,
                        saved_file,
                    )
                    with open(output_pgn_path, "w", encoding="utf-8") as file:
                        file.write(generate_pgn(SETTINGS))
                    switch_state("game_resume")

            elif STATE in (
                "game_resume",
                "game_waiting_user_move",
                "game_do_user_move",
                "game_request_ai_move",
                "game_waiting_ai_move",
                "game_do_ai_move",
                "game_do_take_back",
                "game_pieces_wrong_place_ai_move",
                "game_pieces_wrong_place_resume",
                "game_pieces_wrong_place_invalid_position",
                "game_pieces_wrong_place_take_back",
                "game_exit",
                "game_over",
            ):
                GAME_CLOCK.update(SETTINGS["virtual_chessboard"])

                if not action:
                    pass

                elif action == "hint":
                    if HINT_ENGINE is None:
                        log.info(
                            f'Starting Hint Engine with settings: {SETTINGS["_analysis_engine"]}'
                        )
                        # Not using multipv in epaper mode, so no need to compute them
                        HINT_ENGINE = HintEngine(
                            SETTINGS["_analysis_engine"],
                            multipv=3 if not cfg.args.epaper else 1,
                        )

                    hint_root_moves = SETTINGS.get("hint_root_moves", None)
                    HINT_ENGINE.request_analysis(
                        SETTINGS["virtual_chessboard"], root_moves=hint_root_moves
                    )
                    SETTINGS["show_hint"] = True

                elif action == "analysis":
                    # Instantiate analysis engine
                    if ANALYSIS_ENGINE is None:
                        log.info(
                            f"Starting Analysis Engine with settings: "
                            f'{SETTINGS["_analysis_engine"]}'
                        )
                        ANALYSIS_ENGINE = AnalysisEngine(SETTINGS["_analysis_engine"])
                    # Call new analysis
                    ANALYSIS_ENGINE.request_analysis(SETTINGS["virtual_chessboard"])
                    SETTINGS["show_analysis"] = True

                elif action == "extended_analysis":
                    SETTINGS["show_extended_analysis"] = not SETTINGS[
                        "show_extended_analysis"
                    ]
                    SETTINGS["show_extended_hint"] = False

                elif action == "extended_hint":
                    SETTINGS["show_extended_hint"] = not SETTINGS["show_extended_hint"]
                    SETTINGS["show_extended_analysis"] = False

                elif action == "save":
                    switch_state("save")

                elif action == "exit":
                    # There are two actions called "exit", one to go to the exit menu
                    # and the other to confirm the exit
                    if STATE != "game_exit":
                        switch_state("game_exit")
                    else:
                        log.info("Exited game")
                        switch_state("home")
                        LED_MANAGER.set_leds()

                elif action == "new_game":
                    switch_state("new_game")
                    LED_MANAGER.set_leds()

                elif action == "take_back":
                    switch_state("game_do_take_back")

                elif action == "force-move":
                    if (
                        not SETTINGS["_game_engine"]["is_rom"]
                        and GAME_ENGINE.interrupt_bestmove()
                    ):
                        log.info("Forcing AI move")
                        switch_state("game_do_ai_move")
                    else:
                        log.info(
                            "Cannot force AI move yet, no moves have been suggested"
                        )

                else:
                    raise ValueError(action)

                rotated_physical_chessboard_fen = USB_READER.read_board(
                    SETTINGS["rotate180"], update=False
                )

                # Check if game over (but not if in exit dialog)
                # TODO: Move this to a completely separate state, similar to save_game
                if STATE != "game_exit" and STATE.startswith("game"):
                    if STATE != "game_over" and (
                        SETTINGS["virtual_chessboard"].is_game_over()
                        or GAME_CLOCK.game_overtime
                    ):
                        switch_state("game_over")

                if "game_pieces_wrong_place" in STATE:
                    if (
                        rotated_physical_chessboard_fen
                        == SETTINGS["virtual_chessboard"].board_fen()
                    ):
                        # Disable wrong position leds
                        LED_MANAGER.set_leds()
                        switch_state("game_resume")

                elif STATE == "game_resume":
                    if (
                        rotated_physical_chessboard_fen
                        != SETTINGS["virtual_chessboard"].board_fen()
                    ):
                        LED_MANAGER.highlight_misplaced_pieces(
                            rotated_physical_chessboard_fen,
                            SETTINGS["virtual_chessboard"],
                            rotate180=SETTINGS["rotate180"],
                            display_leds_immediately=True,
                        )
                        switch_state("game_pieces_wrong_place_resume")
                    elif (
                        not SETTINGS["human_game"]
                        and SETTINGS["virtual_chessboard"].turn
                        != SETTINGS["play_white"]
                    ):
                        switch_state("game_request_ai_move")
                    else:
                        switch_state("game_waiting_user_move")

                elif STATE == "game_waiting_user_move":
                    if (
                        rotated_physical_chessboard_fen
                        != SETTINGS["virtual_chessboard"].board_fen()
                        # Check if not trying to exit game / program
                        and not sum(REMOTE_CONTROL.exit_command_initiated.values())
                    ):

                        MOVES = get_moves(
                            SETTINGS["virtual_chessboard"],
                            rotated_physical_chessboard_fen,
                            check_double_moves=SETTINGS["human_game"],
                        )
                        if MOVES:
                            switch_state("game_do_user_move")
                        else:
                            if not SETTINGS["_game_engine"]["is_rom"] and is_move_back(
                                SETTINGS["virtual_chessboard"],
                                rotated_physical_chessboard_fen,
                            ):
                                log.debug("Implicit take back recognized")
                                switch_state("game_do_take_back")
                            else:
                                # TODO: Add main clock and manage time here not
                                #  inside highlighted_leds
                                highligted_leds = (
                                    LED_MANAGER.highlight_misplaced_pieces(
                                        rotated_physical_chessboard_fen,
                                        SETTINGS["virtual_chessboard"],
                                        SETTINGS["rotate180"],
                                    )
                                )
                                # TODO: We don't want to change this state too quickly because
                                #  there is some inherent noise in the board. But we should
                                #  probably use a clock in main, and not rely in the one in
                                #  led_manager!
                                if highligted_leds:
                                    terminal_print(
                                        SETTINGS["terminal_lines"], "Invalid move"
                                    )
                                    switch_state(
                                        "game_pieces_wrong_place_invalid_position"
                                    )

                    else:
                        # Manage leds
                        # Show leds for king in check
                        if (
                            SETTINGS["virtual_chessboard"].is_check()
                            and not SETTINGS["human_game"]
                        ):
                            checked_king_square = chess.SQUARE_NAMES[
                                SETTINGS["virtual_chessboard"].king(
                                    SETTINGS["virtual_chessboard"].turn
                                )
                            ]
                            LED_MANAGER.set_leds(
                                checked_king_square, SETTINGS["rotate180"]
                            )

                        # Show time warning leds
                        elif not SETTINGS["human_game"] and GAME_CLOCK.time_warning(
                            SETTINGS["virtual_chessboard"]
                        ):
                            LED_MANAGER.flash_leds("corners")

                        # Show hint leds
                        elif SETTINGS["show_hint"]:
                            bestmove = HINT_ENGINE.get_latest_bestmove()
                            if bestmove is not None:
                                other_moves = [
                                    chess.square_name(move.to_square)
                                    for move in SETTINGS.get("hint_root_moves", [])
                                    if move.uci() != bestmove
                                ]
                                LED_MANAGER.set_and_flash_leds(
                                    set_message=other_moves,
                                    flash_message=bestmove[
                                        2:4
                                    ],  # Only target square of best move
                                    rotate180=SETTINGS["rotate180"],
                                )
                            else:
                                LED_MANAGER.flash_leds(SETTINGS["_led"]["thinking"])

                        # No leds
                        else:
                            LED_MANAGER.set_leds()

                elif STATE == "game_request_ai_move":
                    # Try fast ai move search in book
                    if SETTINGS["book"] and not DEPLETED_BOOK:
                        finder = pypolyglot.Finder(
                            SETTINGS["book"],
                            SETTINGS["virtual_chessboard"],
                            SETTINGS["_game_engine"]["Depth"] + 1,
                        )
                        best_move = finder.bestmove()
                        if best_move is not None:
                            AI_MOVE = best_move.lower()
                            log.info("Found book ai move")
                            switch_state("game_do_ai_move")
                        else:
                            DEPLETED_BOOK = True

                    if STATE == "game_request_ai_move":
                        if GAME_ENGINE is None:
                            log.info(
                                f'Starting Game Engine with settings: {SETTINGS["_game_engine"]}'
                            )
                            GAME_ENGINE = GameEngine(SETTINGS["_game_engine"])
                        log.debug("Searching in engine")
                        GAME_ENGINE.go(SETTINGS["virtual_chessboard"])
                        WAITING_AI_TIMER = (
                            time.time() + GAME_CLOCK.sample_ai_move_duration()
                        )
                        switch_state("game_waiting_ai_move")

                elif STATE == "game_waiting_ai_move":
                    if GAME_ENGINE.waiting_bestmove() or (
                        time.time() < WAITING_AI_TIMER
                    ):
                        LED_MANAGER.flash_leds(SETTINGS["_led"]["thinking"])
                    else:
                        WAITING_AI_TIMER = None
                        log.debug("Found engine ai move")
                        switch_state("game_do_ai_move")

                elif STATE == "game_do_user_move":
                    # Perform user move (and animate move on pygamedisp)
                    # In human games we can do a double move: white immediately followed by black
                    for move in MOVES:
                        turn = SETTINGS["virtual_chessboard"].turn
                        SETTINGS["virtual_chessboard"].push_uci(move)
                        log.info(f"User move: {move}")
                        terminal_print_move(SETTINGS["terminal_lines"], turn, move)
                    PUBLISHER.publish_pgn(SETTINGS)
                    switch_state("game_resume")

                elif STATE == "game_do_ai_move":
                    turn = SETTINGS["virtual_chessboard"].turn
                    try:
                        AI_MOVE = str(GAME_ENGINE.bestmove)
                        SETTINGS["virtual_chessboard"].push_uci(AI_MOVE)
                    except ValueError:
                        # TODO: Test this branch
                        log.error(f"Invalid AI move: {AI_MOVE}")
                        terminal_print(
                            SETTINGS["terminal_lines"], f"Invalid AI move: {AI_MOVE}!"
                        )
                    else:
                        log.info(f"AI move: {AI_MOVE}")
                        terminal_print_move(SETTINGS["terminal_lines"], turn, AI_MOVE)
                        LED_MANAGER.set_leds(AI_MOVE, SETTINGS["rotate180"])
                        PUBLISHER.publish_pgn(SETTINGS)
                        switch_state("game_pieces_wrong_place_ai_move")

                elif STATE == "game_do_take_back":
                    original_len_moves = len(SETTINGS["virtual_chessboard"].move_stack)
                    if original_len_moves:
                        take_back_moves = []
                        log.debug(
                            f'Take back: Before - {SETTINGS["virtual_chessboard"].fen()}'
                        )
                        move_list = [
                            str(move)
                            for move in SETTINGS["virtual_chessboard"].move_stack
                        ]
                        log.debug(f"Take back: Before - {move_list}")
                        take_back_moves.append(SETTINGS["virtual_chessboard"].pop())
                        # Take back two moves if human game
                        if not SETTINGS["human_game"] and original_len_moves >= 2:
                            take_back_moves.append(SETTINGS["virtual_chessboard"].pop())
                        log.debug(
                            f'Take back: After - {SETTINGS["virtual_chessboard"].fen()}'
                        )
                        move_list = [
                            str(move)
                            for move in SETTINGS["virtual_chessboard"].move_stack
                        ]
                        log.debug(f"Take back: After - {move_list}")
                        LED_MANAGER.highlight_misplaced_pieces(
                            rotated_physical_chessboard_fen,
                            SETTINGS["virtual_chessboard"],
                            rotate180=SETTINGS["rotate180"],
                            display_leds_immediately=True,
                        )
                        DEPLETED_BOOK = False
                        log.info(
                            f"Took back move(s): {[str(move) for move in take_back_moves]}"
                        )
                        switch_state("game_pieces_wrong_place_take_back")
                    else:
                        log.info("Not enough moves to take back")
                        switch_state("game_resume")

                # States that do not require any internal logic
                elif STATE in (
                    "game_over",
                    "game_exit",
                    "save",
                    "home",
                    "new_game",
                ):
                    pass

                else:
                    raise ValueError(STATE)

                # Game state changed
                if STATE in (
                    "game_do_user_move",
                    "game_do_ai_move",
                    "game_do_take_back",
                ):
                    if not SETTINGS["show_extended_hint"]:
                        SETTINGS["show_hint"] = False
                    if not SETTINGS["show_extended_analysis"]:
                        SETTINGS["show_analysis"] = False

            elif STATE in (
                "new_game",
                "new_game_wrong_place",
                "new_game_start_remove_kings",
                "new_game_start_place_pieces",
            ):
                if not action:
                    pass
                elif action == "wrong_place":
                    switch_state("new_game_wrong_place")
                elif action == "pieces_placed":
                    switch_state("new_game")
                elif action == "kings_removed":
                    if STATE == "new_game_start_remove_kings":
                        switch_state("new_game_start_place_pieces")
                elif action == "start_position":
                    switch_state("new_game_start_remove_kings")
                elif action == "calibration_remote":
                    switch_state("calibration_return_home")
                elif action == "human_game":
                    SETTINGS["human_game"] = True

                elif action == "computer_game":
                    SETTINGS["human_game"] = False

                elif action == "flip_board":
                    SETTINGS["rotate180"] = not SETTINGS["rotate180"]

                elif action == "use_board_position":
                    SETTINGS["use_board_position"] = not SETTINGS["use_board_position"]

                elif SETTINGS["use_board_position"] and action == "side_to_move":
                    SETTINGS["side_to_move"] = (
                        "white" if SETTINGS["side_to_move"] == "black" else "black"
                    )

                elif action.startswith("time_"):
                    SETTINGS["time_constraint"] = {
                        "time_unlimited": "unlimited",
                        "time_blitz": "blitz",
                        "time_rapid": "rapid",
                        "time_classical": "classical",
                        "time_custom": "custom",
                    }[action]

                    if SETTINGS["time_constraint"] == "custom":
                        switch_state("select_time")

                elif action == "chess960":
                    SETTINGS["chess960"] = not SETTINGS["chess960"]

                elif action == "syzygy" and SETTINGS["syzygy_available"]:
                    SETTINGS["syzygy_enabled"] = not SETTINGS["syzygy_enabled"]

                elif action.startswith("depth_") and not SETTINGS["human_game"]:
                    if action == "depth_less":
                        if SETTINGS["_game_engine"]["Depth"] > 1:
                            SETTINGS["_game_engine"]["Depth"] -= 1
                        else:
                            SETTINGS["_game_engine"]["Depth"] = cfg.args.max_depth
                    else:
                        if SETTINGS["_game_engine"]["Depth"] < cfg.args.max_depth:
                            SETTINGS["_game_engine"]["Depth"] += 1
                        else:
                            SETTINGS["_game_engine"]["Depth"] = 1

                elif action == "select_engine" and not SETTINGS["human_game"]:
                    SETTINGS["_game_engine"]["engine_list"] = get_engine_list()
                    switch_state("select_engine")

                elif action == "select_book" and not SETTINGS["human_game"]:
                    SETTINGS["book_list"] = get_book_list()
                    switch_state("select_book")

                elif action in ("white", "black") and not SETTINGS["human_game"]:
                    SETTINGS["play_white"] = not SETTINGS["play_white"]

                elif action == "back":
                    switch_state("home")

                elif action == "start":
                    SETTINGS["terminal_lines"] = []
                    if RESUMING_NEW_GAME:
                        RESUMING_NEW_GAME = False
                        # Print every move in the stack to the terminal
                        # Calculate the first player that moved
                        f = (
                            int(SETTINGS["virtual_chessboard"].turn)
                            - len(SETTINGS["virtual_chessboard"].move_stack)
                        ) % 2
                        for i, move in enumerate(
                            SETTINGS["virtual_chessboard"].move_stack
                        ):
                            # Figuring if white or black move based on first player
                            # + eveness of turn
                            turn = (f + i) % 2
                            terminal_print_move(
                                SETTINGS["terminal_lines"], turn, str(move)
                            )
                    else:
                        if not SETTINGS["use_board_position"]:
                            SETTINGS["virtual_chessboard"] = chess.Board()
                            SETTINGS["starting_position"] = chess.STARTING_FEN
                        else:
                            SETTINGS["virtual_chessboard"] = chess.Board(
                                fen=SETTINGS["physical_chessboard_fen"].split()[0],
                                chess960=SETTINGS["chess960"],
                            )
                            SETTINGS["virtual_chessboard"].turn = (
                                SETTINGS["side_to_move"] == "white"
                            )
                            SETTINGS["virtual_chessboard"].set_castling_fen("KQkq")
                            SETTINGS["starting_position"] = SETTINGS[
                                "virtual_chessboard"
                            ].fen()
                            if (
                                SETTINGS["virtual_chessboard"].status()
                                != chess.STATUS_VALID
                                and SETTINGS["virtual_chessboard"].status()
                                != chess.STATUS_BAD_CASTLING_RIGHTS
                            ):
                                log.warning("Board position is not valid")
                                log.warning(
                                    f'{SETTINGS["virtual_chessboard"].status().__repr__()}'
                                )
                                continue
                        SETTINGS["initial_chessboard"] = SETTINGS[
                            "virtual_chessboard"
                        ].copy()

                    if SETTINGS["human_game"]:
                        IS_ROM = False
                    else:
                        IS_ROM = SETTINGS["_game_engine"]["engine"].startswith("rom")

                    SETTINGS["_game_engine"]["is_rom"] = IS_ROM
                    if IS_ROM:
                        GAME_ENGINE = RomEngine(
                            depth=SETTINGS["_game_engine"]["Depth"] + 1,
                            rom=SETTINGS["_game_engine"]["engine"].replace("rom-", ""),
                        )

                    if PUBLISHER is None:
                        PUBLISHER = Publisher(
                            cfg.args.publish,
                            cfg.args.game_id,
                            cfg.args.game_key,
                        )

                    DEPLETED_BOOK = False
                    GAME_CLOCK.start(SETTINGS["virtual_chessboard"], SETTINGS)
                    SETTINGS["show_hint"] = False
                    SETTINGS["show_analysis"] = False

                    if not SETTINGS["use_board_position"]:
                        log.info("Starting game for initial position")
                    else:
                        log.info("Starting game from custom position")

                    # ----- E-PAPER Settings OVERRIDE ------
                    if cfg.args.epaper:
                        SETTINGS["_game_engine"]["engine"] = "maia"
                        SETTINGS["_game_engine"]["Depth"] = {
                            "easy": 3,
                            "medium": 4,
                            "hard": 5,
                        }[SETTINGS["difficulty"]]
                        SETTINGS["_analysis_engine"]["engine"] = "stockfish"
                        SETTINGS["_analysis_engine"]["Depth"] = 12
                    switch_state("game_resume")

                else:
                    raise ValueError(action)

            elif STATE == "select_time":
                TIME_TOTAL_MINUTES = SETTINGS["time_total_minutes"]
                TIME_INCREMENT_SECONDS = SETTINGS["time_increment_seconds"]

                if action == "done":
                    switch_state("new_game")
                else:
                    if action == "minutes_less":
                        TIME_TOTAL_MINUTES -= 1
                    elif action == "minutes_less2":
                        TIME_TOTAL_MINUTES -= 10
                    elif action == "minutes_more":
                        TIME_TOTAL_MINUTES += 1
                    elif action == "minutes_more2":
                        TIME_TOTAL_MINUTES += 10
                    elif action == "seconds_less":
                        TIME_INCREMENT_SECONDS -= 1
                    elif action == "seconds_less2":
                        TIME_INCREMENT_SECONDS -= 10
                    elif action == "seconds_more":
                        TIME_INCREMENT_SECONDS += 1
                    elif action == "seconds_more2":
                        TIME_INCREMENT_SECONDS += 10

                    SETTINGS["time_total_minutes"] = max(TIME_TOTAL_MINUTES, 1)
                    SETTINGS["time_increment_seconds"] = max(TIME_INCREMENT_SECONDS, 0)

            elif STATE == "select_engine":
                if not action:
                    pass
                elif action == "done":
                    # Erase previous Avatar weights selection if different engine is chosen
                    if SETTINGS["_game_engine"]["engine"] != "avatar":
                        SETTINGS["_game_engine"]["weights"] = None
                    switch_state("new_game")
                elif action == "avatar":
                    avatar_weights_list = get_avatar_weights_list()
                    if not avatar_weights_list:
                        log.warning(
                            "Did not find any weights for avatar engine. Make "
                            'sure there is a folder called "avatar_weights" in the'
                            " engine folder, with at least one weight zip file."
                        )
                        SETTINGS["_game_engine"]["engine"] = "stockfish"
                    else:
                        SETTINGS["_game_engine"]["weights_list"] = avatar_weights_list
                        SETTINGS["_game_engine"]["weights"] = avatar_weights_list[0]
                        switch_state("select_weights")
                else:
                    raise ValueError(action)

            elif STATE == "select_weights":
                if not action:
                    pass
                elif action == "done":
                    switch_state("new_game")
                else:
                    raise ValueError(action)

            elif STATE == "select_book":
                if not action:
                    pass
                elif action == "done":
                    switch_state("new_game")
                else:
                    raise ValueError(action)

            elif STATE == "options":
                if action is None:
                    pass
                elif action == "done":
                    save_game_settings()
                    save_certabo_settings()
                    switch_state("home")
                else:
                    # We don't raise a ValueError, because all actions are handled
                    # internally via PygameDisp
                    pass
            else:
                raise ValueError(STATE)

            if quit_program:
                do_poweroff(method=quit_program)

            DISPLAY.process_finish()

    except KeyboardInterrupt:
        do_poweroff(method="interrupt")
