from io import BytesIO
from pathlib import Path
import tempfile
import unittest

import fitz
from PIL import Image

from combined_pipeline import (
    LOGO_WATERMARK_OPACITY,
    _add_watermark_to_page,
    convert_to_secure_image_pdf,
    _logo_watermark_png,
)


class LogoWatermarkTest(unittest.TestCase):
    def test_logo_png_has_transparent_background_and_limited_opacity(self):
        image = Image.open(BytesIO(_logo_watermark_png(1600, 2200))).convert("RGBA")
        alpha = image.getchannel("A")

        self.assertEqual(alpha.getpixel((0, 0)), 0)
        self.assertGreater(alpha.getextrema()[1], 0)
        self.assertLessEqual(alpha.getextrema()[1], round(255 * LOGO_WATERMARK_OPACITY) + 1)

    def test_logo_is_drawn_over_a_page_without_an_opaque_square(self):
        source = fitz.open()
        page = source.new_page(width=800, height=1100)
        page.insert_text((80, 550), "Noi dung van ban phai doc ro", fontsize=20, color=(0, 0, 0))
        pix = page.get_pixmap(alpha=False)
        rendered = _add_watermark_to_page(pix, "Nguyen Van A", "a@example.com", "Ban quyen HVHN")
        image = Image.open(BytesIO(rendered.tobytes("png"))).convert("RGB")
        source.close()

        # Góc logo không được nhuộm nền navy; phần nền vẫn gần trắng.
        corner = image.getpixel((250, 250))
        self.assertGreater(min(corner), 220)
        # Đồng thời phải còn ít nhất một nét logo hiện diện ở vùng trung tâm.
        centre = image.crop((260, 410, 540, 690))
        self.assertLess(min(centre.getextrema()[0]), 245)

    def test_full_secure_conversion_works_with_logo_watermark(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "source.pdf"
            output_path = Path(temp_dir) / "watermarked.pdf"
            source = fitz.open()
            page = source.new_page(width=600, height=840)
            page.insert_text((72, 220), "Tai lieu thu nghiem", fontsize=18)
            source.save(source_path)
            source.close()

            convert_to_secure_image_pdf(
                str(source_path),
                str(output_path),
                "Nguyen Van A",
                "a@example.com",
                "Ban quyen HVHN",
                dpi=72,
            )

            self.assertTrue(output_path.is_file())
            with fitz.open(output_path) as rendered:
                self.assertEqual(rendered.page_count, 1)
                self.assertGreater(rendered[0].get_pixmap().width, 0)


if __name__ == "__main__":
    unittest.main()
