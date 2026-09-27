import os


def resolve(root, name):
    """Return the absolute path of name inside root.

    Raise ValueError if the result would be outside root.
    """
    root = os.path.abspath(root)
    path = os.path.abspath(os.path.join(root, name))
    if not path.startswith(root):
        raise ValueError("path escapes root")
    return path
