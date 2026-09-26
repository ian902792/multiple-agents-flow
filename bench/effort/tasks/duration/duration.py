"""Parse and format durations. Implement both functions; see test_duration.py for the contract."""


def parse_duration(text):
    """Return the number of whole seconds in text.

    Accepted forms:
    - compact units d, h, m, s (case-insensitive), largest first, each unit at most once,
      optional spaces between parts: "1h30m", "2d 4h", "90s"
    - ISO 8601 subset with days, hours, minutes and seconds: "PT1H30M", "P2DT3H", "P1D"
    - a plain non-negative integer string, meaning seconds: "120"
    Raise ValueError for anything else.
    """
    raise NotImplementedError


def format_duration(seconds):
    """Return the compact form of a non-negative int, e.g. 5400 -> "1h30m", 0 -> "0s".

    Omit zero parts. Raise ValueError for negative numbers or non-int values (bool included).
    """
    raise NotImplementedError
