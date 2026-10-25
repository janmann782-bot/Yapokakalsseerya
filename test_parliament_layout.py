from __future__ import annotations

import math
import tempfile
import unittest
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path
from unittest.mock import AsyncMock, patch

from PIL import Image

from config import Config
from db import Db
from models import Page
from parliament_layout import fitted_hemicycle, seat_colors, PARLIAMENT_LAYOUT_VERSION
from renderer import _parliament_svg
from page_handlers import render_saved
from test_bot import fake_message


class ParliamentLayoutTests(unittest.TestCase):
    def test_exact_count_and_full_bounds_for_small_and_large_chambers(self):
        for total in (0, 1, 2, 3, 4, 8, 60, 240, 500, 1000, 3000, 10000):
            for width, scale in ((300, 1), (428 * 3.5, 3.5), (428 * 4, 4)):
                with self.subTest(total=total, width=width):
                    diagram = fitted_hemicycle(total, width, scale)
                    self.assertEqual(len(diagram.seats), total)
                    for seat in diagram.seats:
                        self.assertGreaterEqual(seat.x - seat.radius, 0)
                        self.assertLessEqual(seat.x + seat.radius, width)
                        self.assertGreaterEqual(seat.y - seat.radius, 0)
                        self.assertLessEqual(seat.y + seat.radius, diagram.height)

    def test_both_circle_and_square_seats_have_physical_gaps(self):
        for total in (1, 2, 240, 1000, 3000):
            diagram = fitted_hemicycle(total, 428, 1)
            radius = diagram.seats[0].radius
            grid = defaultdict(list)
            cell = 2 * radius
            for seat in diagram.seats:
                gx, gy = int(seat.x // cell), int(seat.y // cell)
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        for other in grid[(gx + dx, gy + dy)]:
                            self.assertGreater(math.hypot(seat.x - other.x, seat.y - other.y), 2 * radius)
                            self.assertTrue(abs(seat.x - other.x) > 2 * radius or abs(seat.y - other.y) > 2 * radius)
                grid[(gx, gy)].append(seat)

    def test_parties_form_sectors_across_rows_in_input_order(self):
        for total in (240, 1000, 3000):
            seats = fitted_hemicycle(total, 428).seats
            first = total * 2 // 5
            second = total // 3
            parties = [{'seats': first, 'color': '#aa0000'}, {'seats': second, 'color': '#0000aa'}]
            colors = seat_colors(parties, total)
            self.assertEqual(Counter(colors), {'#aa0000': first, '#0000aa': second, '#C8CCD1': total - first - second})
            first_angles = [s.angle for s in seats[:first]]
            next_angles = [s.angle for s in seats[first:]]
            self.assertGreaterEqual(min(first_angles), max(next_angles))
            self.assertEqual({s.row for s in seats[:first]}, {s.row for s in seats})
            self.assertGreater(seats[0].angle, math.pi / 2)
            self.assertLess(seats[-1].angle, math.pi / 2)

    def test_svg_has_exact_counts_and_every_circle_inside_viewbox(self):
        for total in (1, 2, 240, 1000, 3000):
            parties = [{'seats': total // 3, 'color': '#aa0000'}, {'seats': total - total // 3, 'color': '#0000aa'}]
            root = ET.fromstring(_parliament_svg(parties, total))
            _, _, width, height = map(float, root.attrib['viewBox'].split())
            self.assertEqual(len(root), total)
            self.assertEqual(Counter(node.attrib['fill'] for node in root), {c: n for c, n in (('#aa0000', total // 3), ('#0000aa', total - total // 3)) if n})
            for node in root:
                x, y, r = (float(node.attrib[k]) for k in ('cx', 'cy', 'r'))
                stroke = float(node.attrib['stroke-width']) / 2
                self.assertGreaterEqual(x - r - stroke, 0)
                self.assertLessEqual(x + r + stroke, width)
                self.assertGreaterEqual(y - r - stroke, 0)
                self.assertLessEqual(y + r + stroke, height)


class ParliamentPreviewTests(unittest.IsolatedAsyncioTestCase):
    async def test_old_cached_parliament_is_redrawn_and_new_cache_is_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = Db(root / 'test.db')
            await db.init()
            old = root / 'preview_old.png'
            Image.new('RGB', (100, 20), 'white').save(old)
            page = await db.save_page(Page(10, 'parliament', 'Тест', data={'total_seats': '1000', 'parties': 'А, 400, #ff0000\nБ, 600, #0000ff'}, preview_path=old.name))
            cfg = Config('test-token', root, root / 'test.db')
            with patch('page_handlers.send_png', AsyncMock()), patch('page_handlers.spawn_created_page_log'):
                result = await render_saved(fake_message(), page, db, cfg)
            self.assertNotEqual(result, old)
            saved = await db.get_page(page.id, 10)
            self.assertEqual(saved.data['_parliament_layout'], PARLIAMENT_LAYOUT_VERSION)
            with patch('page_handlers.render_page', AsyncMock()) as render, patch('page_handlers.send_png', AsyncMock()):
                await render_saved(fake_message(), saved, db, cfg)
            render.assert_not_called()
