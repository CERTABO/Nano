from lru import LRU

get_moves_cache = LRU(8)


def get_moves(virtual_board, physical_fen, check_double_moves=False):
    virtual_fen = virtual_board.board_fen()
    caching_key = (virtual_fen, physical_fen, check_double_moves)
    try:
        return get_moves_cache[caching_key]
    except KeyError:
        pass

    copy_board = virtual_board.copy()
    moves = list(virtual_board.generate_legal_moves())
    for move in moves:
        copy_board.push(move)
        if physical_fen == copy_board.board_fen():
            result = [move.uci()]
            get_moves_cache[caching_key] = result
            return result
        copy_board.pop()

    if check_double_moves:
        for move in moves:
            copy_board.push(move)
            legal_moves2 = list(copy_board.generate_legal_moves())
            for move2 in legal_moves2:
                copy_board.push(move2)
                if physical_fen == copy_board.board_fen():
                    result = [move.uci(), move2.uci()]
                    get_moves_cache[caching_key] = result
                    return result
                copy_board.pop()
            copy_board.pop()

    result = []
    get_moves_cache[caching_key] = result
    return result


# TODO: Allow double move back for human games
is_move_back_cache = LRU(8)


def is_move_back(virtual_board, physical_fen):
    """
    Check if physical fen correspondts to virtual_board with a move back
    :param virtual_board:
    :param physical_fen:
    :return:
    """
    virtual_fen = virtual_board.board_fen()
    caching_key = (virtual_fen, physical_fen)
    try:
        return is_move_back_cache[caching_key]
    except KeyError:
        pass

    temp_board = virtual_board.copy()
    result = False
    try:
        temp_board.pop()
    except IndexError:
        pass
    else:  # No exception
        if temp_board.board_fen() == physical_fen:
            result = True

    is_move_back_cache[caching_key] = result
    return result
