import unittest

from PIL import Image

from app.font import glyph
from app.protocol import build_program, unwrap, wrap
from app.render import PANEL_H, PANEL_W, SIGN_W, fit_frames, layout_runs, layout_text, render_weather, split_sign


def _first_lit_x(image: Image.Image):
    pixels = image.load()
    for x in range(image.width):
        for y in range(image.height):
            if pixels[x, y] != (0, 0, 0):
                return x
    return None


class ProtocolTests(unittest.TestCase):
    def test_escape_roundtrip(self):
        payload = bytes([0x04, 0x01, 0x02, 0x03, 0x10])
        packet = wrap(payload)
        self.assertEqual(packet[0], 0x01)
        self.assertEqual(packet[-1], 0x03)
        self.assertEqual(unwrap(packet), payload)

    def test_program_contains_every_pixel(self):
        frame = Image.new("RGB", (4, 2), (255, 0, 0))
        program = build_program([frame], [100], 4, 2)
        self.assertGreater(len(program), 16)
        self.assertEqual(program[8], 1)


class RenderTests(unittest.TestCase):
    def test_glyphs_are_five_wide(self):
        for char, rows in {"A": glyph("A"), "0": glyph("0")}.items():
            self.assertEqual(len(rows), 7, char)
            self.assertTrue(all(len(row) == 5 for row in rows))

    def test_short_text_is_one_centered_frame(self):
        frames = fit_frames(layout_text("HI", (255, 255, 255), (0, 0, 0), scale=1), PANEL_W, (0, 0, 0))
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].size, (PANEL_W, PANEL_H))
        self.assertTrue(any(pixel != (0, 0, 0) for pixel in frames[0].get_flattened_data()))

    def test_text_travels_left_to_right(self):
        frames = fit_frames(
            layout_text("HI", (255, 255, 255), (0, 0, 0), scale=1),
            SIGN_W,
            (0, 0, 0),
            step=8,
            travel=True,
        )
        self.assertGreater(len(frames), 1)
        self.assertLessEqual(len(frames), 48)
        lit = [spot for spot in (_first_lit_x(frame) for frame in frames) if spot is not None]
        self.assertGreater(lit[-1], lit[0])
        self.assertLess(lit[0], PANEL_W)
        left, right = split_sign(frames[len(frames) // 2])
        self.assertEqual(left.size, (PANEL_W, PANEL_H))
        self.assertEqual(right.size, (PANEL_W, PANEL_H))

    def test_runs_keep_separate_colors(self):
        image = layout_runs([("NO", (255, 0, 0)), (" GO", (0, 255, 0))], (0, 0, 0), scale=1)
        pixels = image.load()
        red_x = green_x = None
        for x in range(image.width):
            for y in range(image.height):
                red, green, blue = pixels[x, y]
                if red > 200 and green < 40 and red_x is None:
                    red_x = x
                if green > 200 and red < 40 and green_x is None:
                    green_x = x
        self.assertIsNotNone(red_x)
        self.assertIsNotNone(green_x)
        self.assertLess(red_x, green_x)

    def test_weather_board_splits_cleanly(self):
        image = render_weather(
            {
                "temperature": 72,
                "code": 1,
                "high": 80,
                "low": 61,
                "units": "fahrenheit",
                "place": "Austin",
                "clock": "3:04",
            }
        )
        self.assertEqual(image.size, (SIGN_W, PANEL_H))
        left, right = split_sign(image)
        self.assertEqual(left.size, (PANEL_W, PANEL_H))
        self.assertEqual(right.size, (PANEL_W, PANEL_H))
        self.assertTrue(any(pixel != (0, 0, 0) for pixel in left.get_flattened_data()))
        self.assertTrue(any(pixel != (0, 0, 0) for pixel in right.get_flattened_data()))

    def test_local_air_shows_humidity_instead_of_a_forecast(self):
        image = render_weather(
            {
                "temperature": 96,
                "humidity": 60,
                "kind": "storm",
                "feel": "STEAMY",
                "units": "fahrenheit",
                "place": "San Antonio",
                "clock": "3:04",
            }
        )
        self.assertEqual(image.size, (SIGN_W, PANEL_H))
        self.assertTrue(any(pixel == (214, 186, 255) for pixel in image.get_flattened_data()))


if __name__ == "__main__":
    unittest.main()
