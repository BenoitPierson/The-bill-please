"""A phone photo carries its rotation in EXIF: the model must see it upright,
as the browser displays it, or the doubt boxes land in the wrong frame."""
import io

from PIL import Image

import extraction


def _rotated_jpeg(width, height):
    img = Image.new("RGB", (width, height), "white")
    exif = Image.Exif()
    exif[0x0112] = 6  # Orientation: rotate 90° clockwise to display
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif.tobytes())
    return buf.getvalue()


def _size(data):
    with Image.open(io.BytesIO(data)) as img:
        return img.size


def test_large_rotated_photo_is_sent_upright():
    pages = extraction.file_to_page_images("photo.jpg", _rotated_jpeg(4032, 3024), "image/jpeg")
    width, height = _size(pages[0][0])
    assert height > width  # portrait, as displayed


def test_small_rotated_photo_is_sent_upright():
    pages = extraction.file_to_page_images("photo.jpg", _rotated_jpeg(1200, 900), "image/jpeg")
    assert _size(pages[0][0]) == (900, 1200)


def test_upright_photo_is_passed_through():
    buf = io.BytesIO()
    Image.new("RGB", (900, 1200), "white").save(buf, format="JPEG")
    pages = extraction.file_to_page_images("photo.jpg", buf.getvalue(), "image/jpeg")
    assert pages[0][0] == buf.getvalue()
