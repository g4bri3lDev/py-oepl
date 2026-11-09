"""Dithering against how a panel shows its colours, sending what the AP expects."""

import pytest
from PIL import Image

from oepl.image import _bitmap_to_image
from oepl.models import TagType

dithering = pytest.importorskip("oepl.dithering")
from epaper_dithering import ColorScheme, DitherMode  # noqa: E402

WHITE, BLACK, RED, YELLOW = [255, 255, 255], [0, 0, 0], [255, 0, 0], [255, 255, 0]
# As the M3 BWRY tag types have it.
SEEN_YELLOW = [200, 200, 0]


def bwry(**overrides) -> TagType:
    data = {
        "width": 8,
        "height": 8,
        "bpp": 3,
        "colortable": {"white": WHITE, "black": BLACK, "red": RED, "yellow": YELLOW},
        "perceptual": {"white": WHITE, "black": BLACK, "red": RED, "yellow": SEEN_YELLOW},
        **overrides,
    }
    return TagType.from_dict(0x4C, data)


def colors(image: Image.Image) -> set[tuple[int, int, int]]:
    return {rgb for _count, rgb in image.convert("RGB").getcolors()}


def test_perceptual_is_read_from_the_tag_type():
    assert bwry().perceptual["yellow"] == SEEN_YELLOW


def test_display_colors_fall_back_to_the_colortable_per_colour():
    """The Opticon 2.2" lists red in its colortable but not in perceptual."""
    tag_type = bwry(perceptual={"white": WHITE, "black": BLACK, "yellow": SEEN_YELLOW})
    assert tag_type.display_colors == {
        "white": WHITE,
        "black": BLACK,
        "red": RED,
        "yellow": SEEN_YELLOW,
    }


def test_without_perceptual_the_panel_shows_the_colortable():
    data = {"width": 8, "height": 8, "colortable": {"white": WHITE, "black": BLACK, "red": RED}}
    tag_type = TagType.from_dict(0x01, data)
    assert tag_type.display_colors == tag_type.color_table


@pytest.mark.parametrize(
    ("names", "scheme"),
    [
        (("white", "black"), ColorScheme.MONO),
        (("white", "black", "red"), ColorScheme.BWR),
        (("white", "black", "yellow"), ColorScheme.BWY),
        (("white", "black", "red", "yellow"), ColorScheme.BWRY),
        (("white", "black", "gray"), None),
    ],
)
def test_color_scheme_follows_the_colortable(names, scheme):
    tag_type = bwry(colortable={name: BLACK for name in names}, perceptual={})
    assert dithering.color_scheme(tag_type) is scheme


def test_the_palette_is_how_the_panel_looks():
    palette = dithering.palette(bwry())
    assert palette.colors["yellow"] == tuple(SEEN_YELLOW)
    assert palette.accent == "red"
    assert palette.scheme is ColorScheme.BWRY


def test_a_black_and_white_palette_accents_in_black():
    tag_type = bwry(colortable={"white": WHITE, "black": BLACK}, perceptual={})
    assert dithering.palette(tag_type).accent == "black"


def test_the_colour_the_panel_shows_is_drawn_with_that_ink_alone():
    """An area of the panel's real yellow needs no black mixed in."""
    image = Image.new("RGB", (8, 8), tuple(SEEN_YELLOW))

    dithered = dithering.dither_for_tag(image, bwry(), DitherMode.FLOYD_STEINBERG)

    # Sent as the colortable's yellow, which the AP inks as yellow exactly.
    assert colors(dithered) == {tuple(YELLOW)}
    assert colors(dithering.as_displayed(dithered, bwry())) == {tuple(SEEN_YELLOW)}


def test_idealised_dithering_mixes_black_into_the_same_area():
    """What the colortable alone would do, for contrast."""
    from epaper_dithering import dither_image

    image = Image.new("RGB", (8, 8), tuple(SEEN_YELLOW))
    dithered = dither_image(image, ColorScheme.BWRY, mode=DitherMode.FLOYD_STEINBERG)

    assert len(colors(dithered)) > 1


def test_tag_images_are_shown_in_the_colours_the_panel_shows():
    """As the AP's web UI draws them."""
    tag_type = TagType.from_dict(
        0x60,
        {
            "width": 8,
            "height": 8,
            "bpp": 2,
            "colortable": {"white": WHITE, "black": BLACK, "yellow": YELLOW},
            "perceptual": {"white": WHITE, "black": BLACK, "yellow": SEEN_YELLOW},
        },
    )
    plane = 8  # one byte per row, eight rows
    # Nothing in the black plane, everything in the colour plane.
    image = _bitmap_to_image(b"\x00" * plane + b"\xff" * plane, tag_type)

    assert colors(image) == {tuple(SEEN_YELLOW)}


def bwr_white_first() -> TagType:
    """M2 2.9" (type 01): white first, as the AP lists it; no perceptual colours."""
    data = {"width": 16, "height": 8, "colortable": {"white": WHITE, "black": BLACK, "red": RED}}
    return TagType.from_dict(0x01, data)


@pytest.mark.parametrize("mode", [DitherMode.NONE, DitherMode.ORDERED, DitherMode.FLOYD_STEINBERG])
@pytest.mark.parametrize("tag_type", [bwr_white_first(), bwry()], ids=["bwr", "bwry"])
def test_black_on_white_stays_black_on_white(tag_type, mode):
    """Exact colours keep their ink, whatever order the colortable lists them in."""
    image = Image.new("RGB", (8, 8), tuple(WHITE))
    image.paste(tuple(BLACK), (0, 0, 4, 4))

    for result in (
        dithering.dither_for_tag(image, tag_type, mode),
        dithering.as_displayed(dithering.dither_for_tag(image, tag_type, mode), tag_type),
    ):
        rgb = result.convert("RGB")
        assert rgb.getpixel((6, 6)) == tuple(WHITE)
        assert rgb.getpixel((1, 1)) == tuple(BLACK)


@pytest.mark.parametrize("mode", [DitherMode.NONE, DitherMode.ORDERED, DitherMode.FLOYD_STEINBERG])
def test_red_and_yellow_keep_their_inks(mode):
    """BWRY lists red before yellow; epaper-dithering's own order is the reverse."""
    image = Image.new("RGB", (8, 8), tuple(YELLOW))
    image.paste(tuple(RED), (0, 0, 4, 4))

    rgb = dithering.dither_for_tag(image, bwry(), mode).convert("RGB")

    assert rgb.getpixel((6, 6)) == tuple(YELLOW)
    assert rgb.getpixel((1, 1)) == tuple(RED)
