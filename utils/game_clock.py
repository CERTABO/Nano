from collections import deque
from random import gauss

import pygame


class GameClock:
    def __init__(self):
        self.time_warning_threshold = 60
        self.time_constraint = "unlimited"
        self.time_total_minutes = 5
        self.time_increment_seconds = 8
        self.time_white_left = None
        self.time_black_left = None
        self.waiting_for_player = -99
        self.game_overtime = False
        self.game_overtime_winner = -99
        self.initial_moves = 0
        self.human_color = None
        self.move_duration = 0
        self.moves_duration = deque(maxlen=10)
        self.clock = pygame.time.Clock()

    def start(self, chessboard, settings):
        self.time_constraint = settings["time_constraint"]
        self.time_total_minutes = settings["time_total_minutes"]
        self.time_increment_seconds = settings["time_increment_seconds"]

        if self.time_constraint == "blitz":
            self.time_total_minutes = 5
            self.time_increment_seconds = 0
        elif self.time_constraint == "rapid":
            self.time_total_minutes = 10
            self.time_increment_seconds = 0
        elif self.time_constraint == "classical":
            self.time_total_minutes = 15
            self.time_increment_seconds = 15

        self.time_white_left = float(self.time_total_minutes * 60)
        self.time_black_left = float(self.time_total_minutes * 60)
        self.waiting_for_player = -99
        self.game_overtime = False
        self.game_overtime_winner = -99
        self.initial_moves = len(chessboard.move_stack)
        self.human_color = settings["play_white"]
        self.move_duration = 0
        self.moves_duration.clear()
        self.clock.tick()

    def update(self, chessboard):

        if self.time_constraint == "unlimited":
            return

        if self.game_overtime:
            return

        # Let time only start after both players do x moves
        moves = len(chessboard.move_stack)
        if moves - self.initial_moves > -1:  # Set > 1 to start only after 2 moves

            turn = chessboard.turn
            # If player changed
            if not self.waiting_for_player == turn:
                # Increment timer
                if self.waiting_for_player == 1:
                    self.time_white_left += self.time_increment_seconds
                elif self.waiting_for_player == 0:
                    self.time_black_left += self.time_increment_seconds

                # Store move duration for human player
                if not turn == self.human_color:
                    if self.move_duration > 0.01:
                        self.moves_duration.append(self.move_duration)
                self.move_duration = 0

                # Resume clock for other player
                self.waiting_for_player = turn
                self.clock.tick()

            else:
                self.clock.tick()
                change = float(self.clock.get_time()) / 1000
                self.move_duration += change
                if turn == 1:
                    self.time_white_left -= change
                    if self.time_white_left <= 0:
                        self.game_overtime = True
                        self.game_overtime_winner = 0
                        self.time_white_left = 0
                else:
                    self.time_black_left -= change
                    if self.time_black_left <= 0:
                        self.game_overtime = True
                        self.game_overtime_winner = 1
                        self.time_black_left = 0

    def time_warning(self, chessboard):
        if self.time_constraint == "unlimited":
            return False

        if chessboard.turn:
            return self.time_white_left < self.time_warning_threshold
        return self.time_black_left < self.time_warning_threshold

    def sample_ai_move_duration(self):
        # pylint: disable=invalid-name
        if self.time_constraint == "unlimited":
            return 0

        n = len(self.moves_duration)
        mean = 3
        std = 1.5

        if n > 0:
            mean = sum(self.moves_duration) / float(n)

        if n > 1:
            ss = sum((x - mean) ** 2 for x in self.moves_duration)
            std = (ss / (n - 1)) ** 0.5

        return gauss(mean, std)
        # pylint: enable=invalid-name
        # pylint: enable=invalid-name
