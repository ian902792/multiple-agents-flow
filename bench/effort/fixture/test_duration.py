import unittest

from duration import format_duration, parse_duration


class ParseDuration(unittest.TestCase):
    def test_compact_units(self):
        cases = {"90s": 90, "1h30m": 5400, "2d 4h": 187200, "1H 5S": 3605, "1d2h3m4s": 93784,
                 " 45m ": 2700, "0s": 0}
        for text, seconds in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_duration(text), seconds)

    def test_iso_8601(self):
        cases = {"PT1H30M": 5400, "P2DT3H": 183600, "PT45S": 45, "P1D": 86400, "pt2m": 120}
        for text, seconds in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_duration(text), seconds)

    def test_plain_seconds(self):
        self.assertEqual(parse_duration("120"), 120)
        self.assertEqual(parse_duration("0"), 0)

    def test_rejects_invalid_input(self):
        for text in ("", "   ", "-5", "-1h", "1.5h", "30m1h", "1h1h", "1w", "h", "1h 30", "P", "PT",
                     "P1H", "PT1D", "1h-30m", "abc", "1 h"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_duration(text)

    def test_rejects_non_strings(self):
        for value in (None, 90, b"90s"):
            with self.subTest(value=value):
                with self.assertRaises((ValueError, TypeError)):
                    parse_duration(value)


class FormatDuration(unittest.TestCase):
    def test_compact_output(self):
        cases = {0: "0s", 59: "59s", 60: "1m", 5400: "1h30m", 86400: "1d", 93784: "1d2h3m4s", 90061: "1d1h1m1s"}
        for seconds, text in cases.items():
            with self.subTest(seconds=seconds):
                self.assertEqual(format_duration(seconds), text)

    def test_rejects_bad_values(self):
        for value in (-1, 1.5, True, "60", None):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    format_duration(value)

    def test_round_trip(self):
        for seconds in list(range(0, 200)) + [3599, 3600, 3661, 86399, 86400, 172861, 1000000]:
            with self.subTest(seconds=seconds):
                self.assertEqual(parse_duration(format_duration(seconds)), seconds)


if __name__ == "__main__":
    unittest.main()
