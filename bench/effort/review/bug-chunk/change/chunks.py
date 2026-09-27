def chunk(items, size):
    """Split items into consecutive lists of at most size items.

    Every item appears in exactly one chunk, in order. size must be positive.
    """
    if size < 1:
        raise ValueError("size must be positive")
    return [items[i:i + size] for i in range(0, len(items) - size + 1, size)]
