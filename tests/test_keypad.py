import unittest
from pathlib import Path

from app.keypad import Keypad, library_slots, normalize_key, previous_index


class KeypadTests(unittest.TestCase):
    def test_defaults_cover_the_number_pad(self):
        pad = Keypad(path=self._path())
        self.assertEqual(pad.binding("1")["action"], "item")
        self.assertEqual(pad.binding("1")["slot"], 1)
        self.assertEqual(pad.binding("0")["action"], "weather")
        self.assertEqual(pad.binding("+")["action"], "brighter")
        self.assertEqual(pad.binding("enter")["action"], "next")
        self.assertEqual(pad.binding("kp_enter")["action"], "next")

    def test_replace_rejects_an_unknown_command(self):
        pad = Keypad(path=self._path())
        with self.assertRaises(ValueError):
            pad.replace([{"key": "1", "action": "shutdown", "label": "Off"}])

    def test_library_slots_are_texts_then_pictures(self):
        slots = library_slots({"texts": [{"id": "a"}], "images": [{"id": "b"}]})
        self.assertEqual([kind for kind, _item in slots], ["text", "image"])

    def test_previous_wraps_the_rotation(self):
        self.assertEqual(previous_index(1, 3), 2)
        self.assertEqual(previous_index(2, 3), 0)
        self.assertEqual(normalize_key("KP9"), "9")

    def _path(self):
        return Path(self.id().replace(".", "_") + ".json")
