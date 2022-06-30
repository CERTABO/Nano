import os
import platform
import stat
import time

from utils.logger import create_folder_if_needed

if platform.system() == "Windows":
    import ctypes.wintypes

    CSIDL_PERSONAL = 5  # My Documents
    SHGFP_TYPE_CURRENT = 0  # Get current, not default value
    buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
    ctypes.windll.shell32.SHGetFolderPathW(
        None, CSIDL_PERSONAL, None, SHGFP_TYPE_CURRENT, buf
    )
    MY_DOCUMENTS = buf.value
else:
    MY_DOCUMENTS = os.path.expanduser("~/Documents")

# TODO: This should be somewhere else?
CERTABO_SAVE_PATH = os.path.join(MY_DOCUMENTS, "Certabo Saved Games")
ENGINE_PATH = os.path.join(
    os.path.abspath(os.path.dirname(os.path.dirname(__file__))), "engines"
)
WEIGHTS_FOLDERNAME = "avatar_weights"
WEIGHTS_PATH = os.path.join(ENGINE_PATH, WEIGHTS_FOLDERNAME)
BOOK_PATH = os.path.join(
    os.path.abspath(os.path.dirname(os.path.dirname(__file__))), "books"
)

create_folder_if_needed(CERTABO_SAVE_PATH)
create_folder_if_needed(ENGINE_PATH)
create_folder_if_needed(WEIGHTS_PATH)
create_folder_if_needed(BOOK_PATH)

if platform.system() == "Windows":

    def is_executable(filepath):
        # Dumb, but it works
        return filepath.endswith(".exe")


else:

    def is_executable(filepath):
        return os.stat(filepath).st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def get_engine_list():
    result_engines = []
    result_roms = []
    for filename in os.listdir(ENGINE_PATH):
        if filename == "MessChess":
            roms = os.path.join(ENGINE_PATH, filename, "roms")
            for rom in os.listdir(roms):
                if rom.endswith(".zip"):
                    result_roms.append("rom-" + os.path.splitext(rom)[0])

        elif filename == WEIGHTS_FOLDERNAME:
            continue

        elif is_executable(os.path.join(ENGINE_PATH, filename)):
            result_engines.append(os.path.splitext(filename)[0])

    result_engines.sort()
    result_roms.sort()
    return result_engines + result_roms


def get_avatar_weights_list():
    result_weights = []
    for filename in os.listdir(WEIGHTS_PATH):
        if filename.endswith(".zip"):
            result_weights.append(os.path.splitext(filename)[0])

    result_weights.sort()

    if "default" in result_weights:
        result_weights.remove("default")
        result_weights.insert(0, "default")

    return result_weights


def get_book_list():
    result = []
    for filename in os.listdir(BOOK_PATH):
        result.append(filename)
    result.sort()
    return result


def get_saved_games() -> dict:
    files = os.listdir(CERTABO_SAVE_PATH)
    saved_games = {}
    saved_games["filenames"] = [v for v in files if ".pgn" in v]
    saved_games["datetimes"] = [
        time.gmtime(os.stat(os.path.join(CERTABO_SAVE_PATH, name)).st_mtime)
        for name in saved_games["filenames"]
    ]
    return saved_games
