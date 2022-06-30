import os

import pygame

import cfg
from utils.logger import get_logger

COLORS = {
    "green": (129, 187, 0),
    "darkergreen": (129, 187, 0),
    # 'darkergreen': (0, 180, 0),
    "red": (200, 0, 0),
    "black": (0, 0, 0),
    "blue": (0, 0, 200),
    "niceblue": (65, 146, 207),
    "white": (255, 255, 255),
    "terminal_text_color": (0xCF, 0xE0, 0x9A),
    "grey": (100, 100, 100),
    "lightgrey": (190, 190, 190),
    "lightestgrey": (230, 230, 230),
    "lightestgrey2": (250, 250, 250),
}
SPRITE_NAMES = (
    "black_bishop",
    "black_king",
    "black_knight",
    "black_pawn",
    "black_queen",
    "black_rook",
    "white_bishop",
    "white_king",
    "white_knight",
    "white_pawn",
    "white_queen",
    "white_rook",
    "terminal",
    "logo",
    "chessboard_xy",
    "new_game",
    "resume_game",
    "save",
    "exit",
    "analysis",
    "hint",
    "setup",
    "take_back",
    "resume_back",
    "analysing",
    "back",
    "black",
    "confirm",
    "delete-game",
    "done",
    "force-move",
    "select-depth",
    "start",
    "welcome",
    "white",
    "hide_back",
    "start-up-logo",
    "do-your-move",
    "move-certabo",
    "place-pieces",
    "place-pieces-on-chessboard",
    "new-setup",
    "please-wait",
    "check-mate-banner",
    "stale-mate-banner",
    "five-fold-repetition-banner",
    "seventy-five-moves-banner",
    "insufficient-material-banner",
    "lichess",
    "lichess_gray",
    "options",
    "calibration",
)
SOUND_NAMES = ("move",)


def coords_in(x, y, area):
    if not area:
        return False
    left, top, right, bottom = area
    return left < x < right and top < y < bottom


def create_button(
    text,
    x,
    y,
    padding=(5, 5, 5, 5),
    color=COLORS["white"],
    text_color=COLORS["grey"],
    font=None,
    font_size=22,
    align="center",
):
    if font is None:
        font = cfg.font_very_large

    x_multiplier = cfg.x_multiplier
    y_multiplier = cfg.y_multiplier

    ptop, pleft, pbottom, pright = padding
    text_width, text_height = font.size(text)
    widget_width = pleft * x_multiplier + text_width + pright * x_multiplier
    widget_height = ptop * y_multiplier + text_height + pbottom * y_multiplier

    if align == "right":
        x -= widget_width / x_multiplier

    pygame.draw.rect(
        cfg.scr,
        color,
        (x * x_multiplier, y * y_multiplier, widget_width, widget_height),
    )
    img = font.render(text, font_size, text_color)
    pos = (x + pleft) * x_multiplier, (y + ptop) * y_multiplier
    cfg.scr.blit(img, pos)

    return (
        x,
        y,
        x + int(widget_width // x_multiplier),
        y + int(widget_height // y_multiplier),
    )


def show_text(
    string, x, y, color, font=None, fontsize=None, centerx=False, centery=False
):
    if font is None:
        font = cfg.font
        if fontsize == "large":
            font = cfg.font_very_large
        elif fontsize == "small":
            font = cfg.font_small
        elif fontsize == "verysmall":
            font = cfg.font_very_small

    img = font.render(string, 22, color)  # string, blend, color, background color
    posx, posy = x * cfg.x_multiplier, y * cfg.y_multiplier

    text_width, text_height = img.get_size()
    if centerx:
        posx -= text_width / 2
    if centery:
        posy -= text_height / 2

    cfg.scr.blit(img, (posx, posy))

    # TODO: Fix this when centerX or CenterY is True
    return (
        x + int(text_width / cfg.x_multiplier),
        y + int(text_height / cfg.y_multiplier),
    )


def load_sprites(xresolution):
    sprite_path = os.path.join("sprites", f"sprites_{xresolution}")
    cfg.sprites = {}
    for name in SPRITE_NAMES:
        cfg.sprites[name] = pygame.image.load(os.path.join(sprite_path, f"{name}.png"))
    # cfg.sprites = {name: pygame.image.load(os.path.join(sprite_path, f'{name}.png'))
    #                for name in SPRITE_NAMES}


def show_sprite(name, x, y):
    """
    Show sprite, by name
    """
    img = cfg.sprites[name]
    cfg.scr.blit(img, (x * cfg.x_multiplier, y * cfg.y_multiplier))
    widget_width, widget_height = img.get_size()
    return (
        x,
        y,
        x + int(widget_width // cfg.x_multiplier),
        y + int(widget_height // cfg.y_multiplier),
    )


def load_audio():
    cfg.audiofiles = {}
    for name in SOUND_NAMES:
        try:
            cfg.audiofiles[name] = pygame.mixer.Sound(
                os.path.join("sounds", f"{name}.wav")
            )
        except pygame.error as error:
            log = get_logger()
            log.error(f'Unable to load "{name}" sound: {error}')


def play_audio(audio):
    try:
        cfg.audiofiles[audio].play()
    except KeyError:
        return


def load_fonts():
    cfg.font_very_small = pygame.font.Font(
        "fonts/OpenSans-Regular.ttf", int(6.5 * cfg.y_multiplier)
    )
    cfg.font_small = pygame.font.Font(
        "fonts/OpenSans-Regular.ttf", int(9 * cfg.y_multiplier)
    )
    cfg.font = pygame.font.Font(
        "fonts/OpenSans-Regular.ttf", int(13 * cfg.y_multiplier)
    )
    cfg.font_large = pygame.font.Font(
        "fonts/OpenSans-Regular.ttf", int(16 * cfg.y_multiplier)
    )
    cfg.font_very_large = pygame.font.Font(
        "fonts/OpenSans-Regular.ttf", int(19 * cfg.y_multiplier)
    )


class RangeOption:
    def __init__(
        self, label, settings_dict, settings_key, min_, max_, x0, x1, y1, subtitle=None
    ):
        self.label = label
        self.subtitle = subtitle

        self.settings_dict = settings_dict
        self.settings_key = settings_key
        self.min = min_
        self.max = max_
        self.x0 = x0
        self.x1 = x1
        self.y1 = y1

        self.less_button_area = None
        self.less2_button_area = None
        self.more_button_area = None
        self.more2_button_area = None

        self.value = self.settings_dict[self.settings_key]
        assert min_ <= self.value <= max_
        self.large_step = (max_ - min_) // 5

    def draw(self):
        # Show label
        label_pos = show_text(
            self.label, self.x0, self.y1, COLORS["black"], fontsize="normal"
        )

        if self.subtitle:
            show_text(
                self.subtitle,
                self.x0,
                label_pos[1] - 1,
                COLORS["grey"],
                fontsize="small",
            )

        # Show value and buttons
        value_area = create_button(
            str(self.value),
            self.x1,
            self.y1,
            color=COLORS["green"],
            text_color=COLORS["white"],
            font=cfg.font,
            padding=(2, 2, 2, 2),
        )
        self.less_button_area = create_button(
            "<",
            value_area[0] - 4,
            self.y1,
            text_color=COLORS["white"],
            color=COLORS["lightgrey"],
            font=cfg.font,
            align="right",
            padding=(2, 2, 2, 2),
        )
        self.less2_button_area = create_button(
            "<<",
            self.less_button_area[0] - 4,
            self.y1,
            text_color=COLORS["white"],
            color=COLORS["lightgrey"],
            font=cfg.font,
            align="right",
            padding=(2, 0, 2, 0),
        )
        self.more_button_area = create_button(
            ">",
            value_area[2] + 4,
            self.y1,
            text_color=COLORS["white"],
            color=COLORS["lightgrey"],
            font=cfg.font,
            padding=(2, 2, 2, 2),
        )
        self.more2_button_area = create_button(
            ">>",
            self.more_button_area[2] + 4,
            self.y1,
            text_color=COLORS["white"],
            color=COLORS["lightgrey"],
            font=cfg.font,
            padding=(2, 0, 2, 0),
        )

    def click(self, x, y):
        if coords_in(x, y, self.less_button_area):
            self.value -= 1
        elif coords_in(x, y, self.more_button_area):
            self.value += 1
        elif coords_in(x, y, self.less2_button_area):
            self.value -= self.large_step
        elif coords_in(x, y, self.more2_button_area):
            self.value += self.large_step
        else:
            return False

        self.value = min(self.max, max(self.min, self.value))
        self.settings_dict[self.settings_key] = self.value
        return True


class RadioOption:
    def __init__(
        self,
        label,
        settings_dict,
        settings_key,
        options,
        x1,
        y1,
        x0=None,
        y0=None,
        vertical=False,
        font=None,
        subtitle=None,
    ):
        self.label = label
        self.subtitle = subtitle
        self.settings_dict = settings_dict
        self.settings_key = settings_key
        self.options = options
        if x0 is None:
            x0 = x1
        if y0 is None:
            y0 = y1
        self.x0 = x0
        self.y0 = y0
        self.x1 = x1
        self.y1 = y1
        self.vertical = vertical
        self.font = font if font is not None else cfg.font

        self.button_areas = None
        self.value = self.settings_dict[self.settings_key]
        if self.value not in self.options:
            self.value = self.options[0]

    def draw(self):
        self.button_areas = []

        if not self.vertical:
            if self.label:
                label_pos = show_text(
                    self.label, self.x0, self.y0, COLORS["black"], font=self.font
                )

                if self.subtitle:
                    show_text(
                        self.subtitle,
                        self.x0,
                        label_pos[1] - 1,
                        COLORS["grey"],
                        fontsize="small",
                    )

            prev_x = self.x1 - 5
            for label in self.options:
                color = COLORS["green"] if label == self.value else COLORS["lightgrey"]
                button_area = create_button(
                    str(label),
                    prev_x + 5,
                    self.y1,
                    text_color=COLORS["white"],
                    color=color,
                    font=self.font,
                    padding=(2, 2, 2, 2),
                )
                prev_x = button_area[2]
                self.button_areas.append(button_area)

        else:
            if self.label:
                show_text(self.label, self.x0, self.y0, COLORS["black"], font=self.font)

            prev_y = self.y1 - 5
            for label in self.options:
                color = COLORS["green"] if label == self.value else COLORS["lightgrey"]
                button_area = create_button(
                    str(label),
                    self.x1,
                    prev_y + 5,
                    text_color=COLORS["white"],
                    color=color,
                    font=self.font,
                    padding=(2, 2, 2, 2),
                )
                prev_y = button_area[3]
                self.button_areas.append(button_area)

    def click(self, x, y):
        for label, button_area in zip(self.options, self.button_areas):
            if coords_in(x, y, button_area):
                self.value = label
                self.settings_dict[self.settings_key] = label
                return True

        return False


class ListOption:
    def __init__(
        self,
        label,
        settings_dict,
        settings_key,
        options,
        x0,
        y0,
        x1,
        y1,
        font=None,
        null_value=None,
    ):
        self.label = label
        self.settings_dict = settings_dict
        self.settings_key = settings_key
        self.options = options
        self.x0 = x0
        self.y0 = y0
        self.x1 = x1
        self.y1 = y1
        self.font = font if font is not None else cfg.font
        self.null_value = null_value

        self.items_per_page = 6
        self.button_vertical_margin = 5
        self.option_char_limit = 26

        self.current_page = 0
        self.open = False
        self.current_page_slice = None
        self.has_next = None
        self.has_prev = None
        self.button_areas = None
        self.switch_button_area = None
        self.next_button_area = None
        self.prev_button_area = None
        # This checks if the existing value is valid
        self._update_state()

    @property
    def value(self):
        return self.settings_dict[self.settings_key]

    @value.setter
    def value(self, value):
        assert value in self.options or value == self.null_value
        self.settings_dict[self.settings_key] = value

    def update_options(self, new_options):
        self.options = new_options
        if self.value not in self.options:
            if self.options != []:
                self.value = self.options[0]
            else:
                self.value = self.null_value

    def _update_state(self):
        self.current_page_slice = slice(
            self.current_page * self.items_per_page,
            (self.current_page + 1) * self.items_per_page,
        )
        self.has_next = (
            len(self.options) > (self.current_page + 1) * self.items_per_page
        )
        self.has_prev = self.current_page > 0

    def draw(self):
        self.open = True
        show_sprite("hide_back", 0, 0)
        show_text(self.label, self.x0, self.y0, COLORS["black"], font=self.font)

        y = self.y1
        self.button_areas = []
        for option in self.options[self.current_page_slice]:
            color = COLORS["darkergreen"] if self.value == option else COLORS["grey"]

            if len(option) > self.option_char_limit:
                option = f"{option[:self.option_char_limit]}..."

            button_area = create_button(
                option,
                self.x1,
                y,
                text_color=COLORS["white"],
                color=color,
                font=self.font,
            )
            self.button_areas.append(button_area)
            y = button_area[-1] + self.button_vertical_margin

        if self.has_next:
            self.next_button_area = create_button(
                " > ", 415, 150, color=COLORS["darkergreen"], text_color=COLORS["white"]
            )

        if self.has_prev:
            self.prev_button_area = create_button(
                " < ", 115, 150, color=COLORS["darkergreen"], text_color=COLORS["white"]
            )

        self.switch_button_area = show_sprite("done", 360, 275)

    def click(self, x, y):
        for option, button_area in zip(
            self.options[self.current_page_slice], self.button_areas
        ):
            if coords_in(x, y, button_area):
                if self.null_value is not None and self.value == option:
                    self.value = self.null_value
                else:
                    self.value = option
                return True

        if self.has_prev and coords_in(x, y, self.prev_button_area):
            self.current_page -= 1
            self._update_state()
            return True
        if self.has_next and coords_in(x, y, self.next_button_area):
            self.current_page += 1
            self._update_state()
            return True

        if coords_in(x, y, self.switch_button_area):
            self.open = not self.open
            return True

        return False
