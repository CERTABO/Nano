architecture = {
    "init": {
        # the first state loaded, sets up connections, blank screen
        "connects_to": {"init_connection", "startup_leds"},
    },
    "init_connection": {
        # init sub-state with RadioOption to choose `connection_method`
        "connects_to": {"startup_leds"},
        "actions": {"connection_method"},
    },
    "startup_leds": {
        # startup sub-state that sets up leds
        # When there is no calibration file for this connection it should go directly
        # to "calibration_return_home" state
        "connects_to": {"home", "calibration_return_home"},
    },
    "home": {
        "connects_to": {
            "new_game",
            "resume_game",
            "calibration_menu",
            "calibration_return_home",
            "options",
            "lichess",
        },
        "actions": {
            "new_game",
            "resume_game",
            "calibration",
            "calibration_remote",
            "options",
            "lichess",
        },
    },
    "calibration_menu": {
        "connects_to": {"home", "calibration", "calibration_partial"},
        "actions": {"add_piece", "setup", "done"},
    },
    "calibration": {
        "connects_to": {"calibration_menu"},
        "actions": {},
    },
    "calibration_return_home": {
        "connects_to": {"home"},
        "actions": {},
    },
    "calibration_partial": {
        "connects_to": {"calibration_menu"},
        "actions": {},
    },
    "new_game": {
        "connects_to": {
            "home",
            "select_time",
            "select_engine",
            "select_weights",
            "select_book",
            "game",
        },
        "actions": {
            "human_game",
            "computer_game",
            "flip_board",
            "use_board_position",
            "side_to_move",
            "time_unlimed",
            "time_blitz",
            "time_rapid",
            "time_classical",
            "time_custom",
            "chess960",
            "syzygy_enabled",
            "depth_less",
            "depth_more",
            ("white", "black"),  # Two buttons for the flip action
            "select_engine",
            "select_book",
            "back",
            "start",
        },
        "state_variables": {"game_settings"},
    },
    "select_time": {
        "connects_to": {"new_game"},
        "actions": {
            "done",
            "minutes_less",
            "minutes_less2",
            "minutes_more",
            "minutes_more2",
            "seconds_less",
            "seconds_less2",
            "seconds_more",
            "seconds_more2",
        },
        "state_variables": {"game_settings"},
    },
    "select_engine": {
        "connects_to": {"new_game", "select_weights"},
        "actions": {"done", "avatar"},
        "state_variables": {"game_settings"},
    },
    "select_weights": {
        "connects_to": {"new_game"},
        "actions": {"done"},
        "state_variables": {"game_settings"},
    },
    "select_book": {
        "connects_to": {"new_game"},
        "actions": {"done"},
        "state_variables": {"game_settings"},
    },
    "resume_game": {
        "connects_to": {"home", "new_game", "delete_game"},
        "actions": {
            "back",
            "delete",
            "resume_game",
        },
        "state_variables": {"saved_games"},
    },
    "delete_game": {
        "connects_to": {"resume_game"},
        "actions": {"back", "confirm"},
        "state_variables": {},
    },
    "options": {
        "connects_to": {"home"},
        "actions": {"done"},
        "state_variables": {"game_settings"},
    },
    "game": {  # TODO: in-progress, needs a lot of refactoring
        "connects_to": {},  # fill this in
        "actions": {
            "save",
            "exit",
            "take_back",
            "hint",
            "analysis",
            "extended_analysis",
            "extended_hint",
        },
        "state_variables": {"game_settings"},  # add any new ones
    },
}
