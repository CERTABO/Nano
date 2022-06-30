architecture = {
    "home": {
        "connects_to": {"new_game", "calibration"},
        "actions": {
            {"new_game": "spare queens in D4/D5"},
            {"calibration_remote": "spare queens in  D3/D6 + filled 1, 2, 7, 8 ranks"},
        },
    },
    "calibration": {
        "connects_to": {"home"},
        "actions": {},
    },
    # TODO: below here it was all copy pasted from architecture.py,
    #  please correct or remove what is not needed
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
}
