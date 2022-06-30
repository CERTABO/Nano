import os
import queue
import threading

import chess
import pygame

import cfg
from utils.get_books_engines import ENGINE_PATH, WEIGHTS_PATH
from utils.logger import get_logger
from utils.media import COLORS, show_text

log = get_logger()


class AnalysisObject:
    """
    Data Class that holds analysis status and results
    """

    def __init__(self, chessboard, multipv=1, root_moves=None, *, name: str):
        self.index = len(chessboard.move_stack)
        # To indentify move in case of take back
        self.move = str(chessboard.move_stack[-1]) if self.index else ""
        self.turn = 1 - chessboard.turn if self.index else 1
        self.multipv = multipv
        self.root_moves = root_moves
        self.data = []
        self.complete = False
        self.interrupted = False
        self.chessboard = chessboard.copy()
        self.default_value = 0
        self.name = name

    def get_score(self, idx=0):
        try:
            return int(self.data[idx]["score"].white().score())
        # Either data is still None or it returned None as a score
        except (TypeError, KeyError, IndexError):
            return self.default_value

    def get_bestmove(self):
        try:
            return self.data[0]["pv"][0]
        except (IndexError, TypeError, KeyError):
            return None


def analysis_thread(engine_settings: dict, analysis_queue: queue.Queue):
    """
    Analysis thread for game hint and evaluation

    It reads evaluation requests from main_to_thread and returns online results
    via thread_to_main. It automatically interrupts previous analysis if new one
    is requested  (it checks if this is the case every time  the engine returns).
    In the case of interrupt it still sends the latest results.

    :param engine_settings: dict (details with engine and settings)
    :param analysis_queue: queue ((index, python-chess chessboard object, number
    of branches to consider))
    """

    engine_path = os.path.join(ENGINE_PATH, engine_settings["engine"])
    if os.name == "nt":
        engine_path += ".exe"
    cmd = [engine_path]

    if engine_settings["engine"] == "avatar":
        weights = engine_settings["weights"]
        if weights is not None:
            weights_path = os.path.join(WEIGHTS_PATH, weights)
            cmd += ["--weights", weights_path + ".zip"]

    engine = chess.engine.SimpleEngine.popen_uci(cmd, debug=False)
    # Hack to allow setting of ponder
    try:
        chess.engine.MANAGED_OPTIONS.remove("ponder")
    except ValueError:
        pass

    for option, value in engine_settings.items():
        if option in ("engine", "Depth"):
            continue
        if engine.options.get(option, None):
            engine.configure({option: value})
            if cfg.DEBUG_ANALYSIS:
                log.debug(f"Analysis: setting engine option {option}:{value}")
        else:
            if cfg.DEBUG_ANALYSIS:
                log.debug(f"Analysis: ignoring engine option {option}:{value}")

    depth = engine_settings["Depth"]
    analysis = None
    analysis_request = None

    while True:
        # Check for new request
        try:
            # Block only if there is no current analysis being performed
            if analysis is None:
                new_analysis_request = analysis_queue.get()
            else:
                new_analysis_request = analysis_queue.get_nowait()
        except queue.Empty:
            pass
        # Process request
        else:
            if new_analysis_request is None:  # Quit
                if cfg.DEBUG_ANALYSIS:
                    log.debug("Analysis: Quitting analysis thread")
                engine.close()
                return

            # Deal with previous request
            if analysis is not None:
                analysis.stop()
                analysis_request.data = analysis.multipv
                analysis_request.interrupted = True
                if cfg.DEBUG_ANALYSIS:
                    log.debug(
                        f"Analysis: Stopped previous request number {analysis_request.index}"
                    )

            # Ellipsis is used for interruption of analysis (but not killing of the engine)
            if new_analysis_request is ...:
                continue

            # Create new analysis from requset
            if cfg.DEBUG_ANALYSIS:
                log.debug(
                    f"{new_analysis_request.name}: Got new request number "
                    f"{new_analysis_request.index}"
                )
            analysis_request = new_analysis_request
            request_board = analysis_request.chessboard
            request_multipv = analysis_request.multipv
            request_root_moves = analysis_request.root_moves
            analysis = engine.analysis(
                request_board,
                multipv=request_multipv,
                root_moves=request_root_moves,
                limit=chess.engine.Limit(depth=depth),
                info=chess.engine.Info.ALL,
            )
            if cfg.DEBUG_ANALYSIS:
                log.debug(
                    f"{new_analysis_request.name}: Starting request number {analysis_request.index}"
                )
                log.debug(
                    f"{new_analysis_request.name} settings: multipv={request_multipv}, "
                    f"root_moves={request_root_moves}"
                )
                log.debug(
                    f"{new_analysis_request.name} result: {analysis_request.data}"
                )

        # Block until next analysis update
        try:
            analysis.get()
            analysis_request.data = analysis.multipv
        except chess.engine.AnalysisComplete:
            analysis_request.data = analysis.multipv
            analysis_request.complete = True
            analysis = None
            if cfg.DEBUG_ANALYSIS:
                log.debug(
                    f"{analysis_request.name}: Request number {analysis_request.index} is done"
                )
                log.debug(
                    f"{analysis_request.name} final data: {analysis_request.data}"
                )


class Engine:
    """
    This base class interacts with engine threads, sending and reading analysis requests
    """

    def __init__(self, engine_settings, multipv=1):
        self.analysis_queue = queue.Queue()
        self.thread = threading.Thread(
            target=analysis_thread,
            args=(engine_settings, self.analysis_queue),
            daemon=True,
        )
        self.thread.start()
        self.analysis_counter = 0
        self.analysis_history = {}
        self.history_limit = 1
        self.multipv = multipv

    def request_analysis(self, chessboard, latest=True, root_moves=None):
        analysis_object = AnalysisObject(
            chessboard=chessboard,
            multipv=self.multipv,
            root_moves=root_moves,
            name=self.__class__.__name__,
        )
        index = analysis_object.index
        self.analysis_history[index] = analysis_object
        self.analysis_queue.put(analysis_object)

        # Set default value to previous (if available)
        if latest:
            try:
                prev_analysis = self.analysis_history[index - 1]
            except KeyError:
                pass
            else:
                analysis_object.default_value = prev_analysis.get_score()

        # Delete old keys
        if latest:
            self.analysis_counter = index
            delete_keys = [
                key for key in self.analysis_history if key < index - self.history_limit
            ]
            for key in delete_keys:
                del self.analysis_history[key]

    def kill(self):
        self.analysis_queue.put(None)
        self.thread.join(timeout=5)

    def interrupt(self):
        self.analysis_queue.put(...)


class GameEngine(Engine):
    """
    Extended Engine class with special methods to interrupt move and return best move
    """

    def __init__(self, engine_settings):
        super().__init__(engine_settings)
        self.lastfen = None
        self.bestmove = None

    def go(self, chessboard):
        """
        Request new moves and return if they are completed
        """
        # If new move is being requested
        if chessboard.fen() != self.lastfen:
            self.request_analysis(chessboard)
            self.lastfen = chessboard.fen()
            self.bestmove = None

    def waiting_bestmove(self):
        """
        Return True if analysis is completed, False otherwise
        """
        analysis = self.analysis_history[self.analysis_counter]
        self.bestmove = analysis.get_bestmove()

        if analysis.complete:
            return False
        return True

    def interrupt_bestmove(self):
        """
        Interrupt bestmove search provided at least one bestmove has been recorded
        :return:
        """
        self.waiting_bestmove()
        if self.bestmove is not None:
            self.interrupt()
            return True
        return False


class AnalysisEngine(Engine):
    """
    Extended Engine class with special methods to analyze multiple positions and plot the results
    """

    def __init__(self, engine_settings):
        super().__init__(engine_settings)
        self.history_limit = 9
        self.extended_analysis_completed = False
        self.plot = None

    def update_extended_analysis(self, chessboard):
        self.extended_analysis_completed = False
        current_index = len(chessboard.move_stack)

        # Delete newer keys (in case of take back)
        delete_keys = [key for key in self.analysis_history if key > current_index]
        if delete_keys:
            for key in delete_keys:
                del self.analysis_history[key]

            # Update analysis_counter
            if self.analysis_history:
                self.analysis_counter = max(self.analysis_history.keys())
            else:
                self.analysis_counter = 0

        # Check if most recent analysis was launched already
        if current_index not in self.analysis_history:
            self.request_analysis(chessboard)
            return

        # If so, check if it is still ongoing
        if not self.analysis_history[current_index].complete:
            return

        # Check whether a previous analysis should be run
        board = chessboard.copy()
        for i in reversed(range(current_index)):
            # Limit retroactive analysis to history limit
            if current_index - i > self.history_limit:
                return

            board.pop()
            # If analysis was not launched, launch it
            if i not in self.analysis_history:
                self.request_analysis(board, latest=False)
                return

            analysis = self.analysis_history[i]
            # If analysis was interrupted, resume it
            if analysis.interrupted:
                analysis.interrupted = False
                self.analysis_queue.put(analysis)
                return

            # If analysis is still ongoing, return
            if not analysis.complete:
                return

        # Analysis is complete
        self.extended_analysis_completed = True

    @staticmethod
    def format_score(score):
        """
        Return '+score' for positive scores and '-score' for negative scores.
        Limit to 4 characters (add k if larger)
        """
        text_sign = "+" if score > 0 else ""

        if abs(score) < 10_000:
            text_score = f"{text_sign}{score}"
        else:
            score = score // 1000
            text_score = f"{text_sign}{score}k"

        return text_score

    def get_latest_score(self, return_incomplete=False):
        analysis = self.analysis_history[self.analysis_counter]
        if analysis.complete or return_incomplete:
            return f"{self.format_score(analysis.get_score())}(Cp)".center(9)
        return "...".center(9)

    def plot_extended_analysis(self, chessboard, clear_previous=False):
        """
        :param chessboard:
        :param clear_previous: Whether background needs to be cleared (used during inner AI loop)
        :return:
        """
        if self.plot is None:
            self.plot = AnalysisPlot(self.history_limit)
        self.update_extended_analysis(chessboard)
        self.plot.draw(
            self.analysis_history,
            self.analysis_counter,
            self.history_limit,
            self.extended_analysis_completed,
            clear_previous,
        )

    def get_analysis_history(self, chessboard):
        self.update_extended_analysis(chessboard)
        return self.analysis_history


class HintEngine(Engine):
    """
    Extended engine class with special methods to analize future position and plot results
    """

    def __init__(self, engine_settips, multipv=3):
        super().__init__(engine_settips, multipv)
        self.extended_hint_completed = False
        self.plot = None
        self.bestmove = None

    def update_extended_hint(self, chessboard):
        self.extended_hint_completed = False
        current_index = len(chessboard.move_stack)

        # Check if most recent analysis was launched already
        if current_index not in self.analysis_history:
            self.request_analysis(chessboard)
            return

        # If so, check if it is still ongoing
        if not self.analysis_history[current_index].complete:
            return

        # Analysis is complete
        self.extended_hint_completed = True

    def get_latest_bestmove(self, return_incomplete=False):
        self.bestmove = None

        analysis = self.analysis_history[self.analysis_counter]
        if analysis.complete or return_incomplete:
            bestmove = analysis.get_bestmove()
            if bestmove is not None:
                if analysis.complete:
                    self.bestmove = str(bestmove)
                return str(bestmove)
        return None

    def get_hint_bestmove_score(self):
        analysis = self.analysis_history[self.analysis_counter]
        if analysis.complete:
            return analysis.get_score()
        else:
            return None

    def get_hint_bestmove_pv(self):
        analysis = self.analysis_history[self.analysis_counter]
        if analysis.complete:
            return analysis.data[0]["pv"]
        else:
            return None

    def plot_extended_hint(self, chessboard, clear_previous=False):
        """
        :param chessboard:
        :param clear_previous: Whether background needs to be cleared (used during inner AI loop)
        :return:
        """
        if self.plot is None:
            self.plot = HintPlot()
        self.update_extended_hint(chessboard)
        self.plot.draw(
            self.analysis_history[self.analysis_counter],
            self.extended_hint_completed,
            clear_previous,
        )


class AnalysisPlot:
    """
    Takes care of plotting extended postion evaluation
    """

    def __init__(self, history_limit):
        self.height = 35
        self.middle_y_coord_raw = 198
        self.start_y_coord_raw = self.middle_y_coord_raw - self.height
        self.end_y_coord_raw = self.middle_y_coord_raw + self.height

        self.start_x_coord_raw = 10
        self.end_x_coord_raw = 150

        self.middle_y_coord = int(self.middle_y_coord_raw * cfg.y_multiplier)
        self.start_y_coord = int(self.start_y_coord_raw * cfg.y_multiplier)
        self.end_y_coord = int(self.end_y_coord_raw * cfg.y_multiplier)
        self.start_x_coord = int(self.start_x_coord_raw * cfg.x_multiplier)
        self.end_x_coord = int(self.end_x_coord_raw * cfg.x_multiplier)
        self.x_step = (
            (self.end_x_coord_raw - self.start_x_coord_raw + 10)
            / history_limit
            * cfg.x_multiplier
        )

        self.marker_radius = int(2 * cfg.x_multiplier)
        self.label_min_y_distance = 5 * cfg.y_multiplier

        self.plot_area = pygame.Rect(
            self.start_x_coord - 5 * cfg.x_multiplier,
            self.start_y_coord - 3 * cfg.x_multiplier,
            self.end_x_coord - self.start_x_coord + 33 * cfg.x_multiplier,
            self.end_y_coord - self.start_y_coord + 14 * cfg.x_multiplier,
        )

        self.plot_freeze = None

    def draw(
        self,
        analysis_history,
        analysis_counter,
        history_limit,
        extended_analysis_completed,
        clear_previous,
    ):
        # pygame.draw.rect(cfg.scr, COLORS['red'], self.plot_area)

        # Return frozen plot if nothing has changed, erase otherwise
        if not extended_analysis_completed:
            self.plot_freeze = None
        elif self.plot_freeze is not None:
            cfg.scr.blit(self.plot_freeze, self.plot_area)
            return

        # Erase plot area
        if clear_previous:
            pygame.draw.rect(cfg.scr, COLORS["white"], self.plot_area)

        # Get scores and colors
        scores, colors, moves = [], [], []
        current_index = analysis_counter
        start_index = current_index - history_limit + 1
        for index in range(max(0, start_index), current_index + 1):
            try:
                analysis_object = analysis_history[index]
                scores.append(analysis_object.get_score())
                moves.append(analysis_object.move)
                color = COLORS["grey"] if analysis_object.turn else COLORS["black"]
                colors.append(color)
            except KeyError:
                scores.append(0)
                moves.append("")
                colors.append(COLORS["white"])
        colors[-1] = COLORS["niceblue"]

        # Define coordinates
        min_score = min(scores)
        max_score = max(scores)
        range_normalizer = max(abs(min_score), abs(max_score), 1) / (self.height - 2)
        points = []
        for i, score in enumerate(scores, 0):
            x_coord = int(self.start_x_coord + 5 + i * self.x_step)
            y_coord = int(
                self.middle_y_coord - score / range_normalizer * cfg.y_multiplier
            )
            points.append((x_coord, y_coord))

        # Draw background
        pygame.draw.rect(
            cfg.scr,
            COLORS["lightestgrey2"],
            pygame.Rect(
                self.start_x_coord,
                self.start_y_coord,
                self.end_x_coord - self.start_x_coord,
                self.middle_y_coord - self.start_y_coord,
            ),
        )
        pygame.draw.rect(
            cfg.scr,
            COLORS["lightestgrey"],
            pygame.Rect(
                self.start_x_coord,
                self.middle_y_coord,
                self.end_x_coord - self.start_x_coord,
                self.middle_y_coord - self.start_y_coord,
            ),
        )

        # Draw graph lines
        if len(points) > 1:
            pygame.draw.aalines(cfg.scr, COLORS["black"], False, points)

        # Draw guiding lines
        min_score_y = points[scores.index(min_score)][1]
        max_score_y = points[scores.index(max_score)][1]
        pygame.draw.line(
            cfg.scr,
            COLORS["lightgrey"],
            (self.start_x_coord, min_score_y),
            (self.end_x_coord, min_score_y),
            1,
        )
        pygame.draw.line(
            cfg.scr,
            COLORS["lightgrey"],
            (self.start_x_coord, max_score_y),
            (self.end_x_coord, max_score_y),
            1,
        )
        pygame.draw.line(
            cfg.scr,
            COLORS["niceblue"],
            (self.start_x_coord, points[-1][1]),
            (self.end_x_coord, points[-1][1]),
            1,
        )

        # Draw points
        for point, color in zip(points, colors):
            pygame.draw.circle(cfg.scr, color, point, self.marker_radius)

        # Yaxis ticks
        show_text(
            AnalysisEngine.format_score(scores[-1]),
            self.end_x_coord_raw + 2,
            points[-1][1] / cfg.y_multiplier,
            COLORS["niceblue"],
            fontsize="small",
            centery=True,
        )
        # Only show other ticks if they are not too close to latest
        if abs(min_score_y - points[-1][1]) > self.label_min_y_distance:
            show_text(
                AnalysisEngine.format_score(min_score),
                self.end_x_coord_raw + 2,
                min_score_y / cfg.y_multiplier,
                COLORS["grey"],
                fontsize="small",
                centery=True,
            )
        if abs(max_score_y - points[-1][1]) > self.label_min_y_distance:
            show_text(
                AnalysisEngine.format_score(max_score),
                self.end_x_coord_raw + 2,
                max_score_y / cfg.y_multiplier,
                COLORS["grey"],
                fontsize="small",
                centery=True,
            )

        # Xaxis ticks
        if cfg.xresolution != 480:
            for move, color, point in zip(moves, colors, points):
                # Ticks
                pygame.draw.line(
                    cfg.scr,
                    COLORS["black"],
                    (point[0], self.end_y_coord - 1 * cfg.y_multiplier),
                    (point[0], self.end_y_coord + 1 * cfg.y_multiplier),
                )
                # Labels
                show_text(
                    move,
                    point[0] / cfg.x_multiplier,
                    self.end_y_coord_raw + 5,
                    color,
                    fontsize="verysmall",
                    centerx=True,
                    centery=True,
                )
        else:
            for move, color, point in zip(moves[::-2], colors[::-2], points[::-2]):
                # Ticks
                pygame.draw.line(
                    cfg.scr,
                    COLORS["black"],
                    (point[0], self.end_y_coord - 2 * cfg.y_multiplier),
                    (point[0], self.end_y_coord + 0.5 * cfg.y_multiplier),
                )
                # Labels
                show_text(
                    move,
                    point[0] / cfg.x_multiplier,
                    self.end_y_coord_raw + 5,
                    color,
                    fontsize="small",
                    centerx=True,
                    centery=True,
                )

        # Freeze plot if its complete
        if extended_analysis_completed:
            self.plot_freeze = cfg.scr.subsurface(self.plot_area).copy()


class HintPlot:
    """
    Takes care of plotting extended hint evaluation
    """

    def __init__(self):
        height = 35
        middle_y_coord = 198
        end_y_coord = middle_y_coord + height
        self.limit_moves = 5
        self.start_y_coord = middle_y_coord - height

        self.start_x_coord = 10
        self.end_x_coord = 150

        self.x_step = (self.end_x_coord - self.start_x_coord + 10) / 6
        self.y_step = (end_y_coord - self.start_y_coord + 15) / 3.2

        self.plot_backgronud_area = pygame.Rect(
            self.start_x_coord * cfg.x_multiplier,
            self.start_y_coord * cfg.y_multiplier,
            (self.end_x_coord - self.start_x_coord) * cfg.x_multiplier,
            (end_y_coord - self.start_y_coord) * cfg.y_multiplier,
        )

        self.plot_area = pygame.Rect(
            (self.start_x_coord - 5) * cfg.x_multiplier,
            (self.start_y_coord - 3) * cfg.y_multiplier,
            (self.end_x_coord - self.start_x_coord + 33) * cfg.x_multiplier,
            (end_y_coord - self.start_y_coord + 14) * cfg.y_multiplier,
        )

        self.plot_freeze = None

    def draw(self, analysis_object, extended_hint_completed, clear_previous):
        # pygame.draw.rect(cfg.scr, COLORS['red'], self.plot_area)

        # Return frozen plot if nothing has changed, erase otherwise
        if not extended_hint_completed:
            self.plot_freeze = None
        elif self.plot_freeze is not None:
            cfg.scr.blit(self.plot_freeze, self.plot_area)
            return

        # Erase plot area
        if clear_previous:
            pygame.draw.rect(cfg.scr, COLORS["white"], self.plot_area)

        # Draw background
        pygame.draw.rect(cfg.scr, COLORS["lightestgrey2"], self.plot_backgronud_area)

        if not analysis_object.data:
            return

        # Get moves, colors, and scores
        next_move = analysis_object.turn
        moves, colors, scores = [], [], []
        for i, branch in enumerate(analysis_object.data):
            branch_moves = []
            branch_colors = []
            for j, pv in enumerate(branch.get("pv")):
                # Do not show more than limit moves
                if j >= self.limit_moves:
                    break

                branch_moves.append(str(pv))
                color = COLORS["grey"] if (next_move + j) % 2 else COLORS["black"]
                branch_colors.append(color)

            moves.append(branch_moves)
            colors.append(branch_colors)
            scores.append(analysis_object.get_score(i))

        # Best move is shown in blue
        colors[0][0] = COLORS["niceblue"]

        # Draw data
        for y, (branch_score, branch_moves, branch_colors) in enumerate(
            zip(scores, moves, colors)
        ):
            y_coord = int(self.start_y_coord + self.y_step * y)

            # Draw moves
            for x, (move, color) in enumerate(zip(branch_moves, branch_colors)):
                x_coord = int(self.start_x_coord + 5 + self.x_step * x)
                show_text(move, x_coord, y_coord, color, fontsize="small")

            # Draw scores
            score = AnalysisEngine.format_score(branch_score)
            show_text(
                score, self.end_x_coord + 2, y_coord, branch_colors[0], fontsize="small"
            )

        # Freeze plot if its complete
        if extended_hint_completed:
            self.plot_freeze = cfg.scr.subsurface(self.plot_area).copy()
