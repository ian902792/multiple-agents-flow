import os
import unittest

from storage import resolve


class ResolveTest(unittest.TestCase):
    root = os.path.abspath("data")

    def test_inside(self):
        self.assertEqual(resolve(self.root, "a/b.txt"), os.path.join(self.root, "a", "b.txt"))

    def test_rejects_parent(self):
        with self.assertRaises(ValueError):
            resolve(self.root, "../etc/passwd")

    def test_rejects_absolute(self):
        with self.assertRaises(ValueError):
            resolve(self.root, "/etc/passwd")


if __name__ == "__main__":
    unittest.main()
