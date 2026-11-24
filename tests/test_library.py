import tempfile
import unittest
from pathlib import Path

from app.library import Library, build_rotation, dwell_seconds, greeting_for, with_live_greeting


class LibraryTests(unittest.TestCase):
    def test_rotation_alternates_text_image_and_weather(self):
        texts = [{"id": "a"}, {"id": "b"}]
        images = [{"id": "pic"}]
        items = build_rotation(texts, images, True)
        kinds = [kind for kind, _item in items]
        self.assertEqual(kinds, ["text", "image", "weather", "text", "image", "weather"])
        self.assertEqual(items[0][1]["id"], "a")
        self.assertEqual(items[3][1]["id"], "b")
        self.assertEqual(items[1][1]["id"], "pic")
        self.assertEqual(items[4][1]["id"], "pic")

    def test_rotation_skips_empty_categories(self):
        self.assertEqual([kind for kind, _item in build_rotation([{"id": "a"}], [], False)], ["text"])
        self.assertEqual([kind for kind, _item in build_rotation([], [], True)], ["weather"])
        self.assertEqual(build_rotation([], [], False), [])

    def test_default_slides_are_added_once(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            library = Library(root, root / "library.json")
            names = [item["name"] for item in library.snapshot()["images"]]
            self.assertEqual(
                names,
                ["Jagwire", "A&M San Antonio", "A&M San Antonio banner", "A&M San Antonio banner offset"],
            )
            library.remove("image", "jagwire")
            again = Library(root, root / "library.json")
            ids = [item["id"] for item in again.snapshot()["images"]]
            self.assertNotIn("jagwire", ids)
            self.assertEqual(len(ids), 3)

    def test_greeting_follows_the_part_of_day(self):
        self.assertEqual(greeting_for(5)[0], "GOOD MORNING")
        self.assertEqual(greeting_for(11)[0], "GOOD MORNING")
        self.assertEqual(greeting_for(12)[0], "GOOD AFTERNOON")
        self.assertEqual(greeting_for(16)[0], "GOOD AFTERNOON")
        self.assertEqual(greeting_for(17)[0], "GOOD EVENING")
        self.assertEqual(greeting_for(2)[0], "GOOD EVENING")

    def test_live_greeting_replaces_only_the_default_line(self):
        shown = with_live_greeting(
            [
                {"id": "greeting", "kind": "greeting", "text": "GOOD MORNING"},
                {"id": "custom", "text": "HELLO GOOD DAY"},
            ],
            hour=15,
        )
        self.assertEqual(shown[0]["text"], "GOOD AFTERNOON")
        self.assertEqual(shown[1]["text"], "HELLO GOOD DAY")

    def test_dwell_covers_one_scroll_pass(self):
        self.assertEqual(dwell_seconds("text", 10, 100, 12), 12)
        self.assertEqual(dwell_seconds("text", 40, 500, 12), 20)
        self.assertEqual(dwell_seconds("weather", 1, 500, 12), 12)
