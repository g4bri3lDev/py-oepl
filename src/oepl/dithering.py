"""Dithering images for a tag, against the colours its panel really shows.

A tag type's ``colortable`` holds the colours the AP expects in an image, and
``perceptual`` how the panel shows them. Dithering against the idealised
colours treats a BWRY panel's yellow as pure yellow, when it is a good deal
darker. These dither against :attr:`TagType.display_colors` instead and hand
back the image in ``colortable`` colours, which the AP gives exactly the ink
they name.

Requires the ``dither`` extra (epaper-dithering).
"""

from __future__ import annotations

from epaper_dithering import DitherMode, DitherOptions, Palette, dither_image
from PIL import Image

from .models import TagType


def palette(tag_type: TagType) -> Palette:
    """The palette to dither for *tag_type*: its colours as the panel shows them.

    One ink per colortable colour, in colortable order, so an output index is
    the colour's position in the colortable. Each ink looks as
    :attr:`TagType.display_colors` says, and its colortable colour asks for
    it: a pixel of exactly that colour is drawn with that ink alone.
    """
    shown = tag_type.display_colors
    return Palette.from_srgb([(_rgb(shown[name]), name, _rgb(rgb)) for name, rgb in tag_type.color_table.items()])


def dither_for_tag(
    image: Image.Image,
    tag_type: TagType,
    mode: DitherMode = DitherMode.FLOYD_STEINBERG,
) -> Image.Image:
    """Dither *image* for *tag_type*, ready to upload.

    Returns a palette-mode image in the tag type's ``colortable`` colours,
    whose indices follow the colortable. Use :func:`as_displayed` on it to
    see how the panel will show it.
    """
    dithered = dither_image(image, palette(tag_type), DitherOptions(mode=mode))
    dithered.putpalette(_flatten(tag_type.color_table.values()))
    return dithered


def as_displayed(image: Image.Image, tag_type: TagType) -> Image.Image:
    """How the panel shows *image*, an image from :func:`dither_for_tag`."""
    shown = image.copy()
    shown.putpalette(_flatten(tag_type.display_colors.values()))
    return shown


def _rgb(color: list[int]) -> tuple[int, int, int]:
    return (color[0], color[1], color[2])


def _flatten(colors: object) -> list[int]:
    return [channel for rgb in colors for channel in rgb[:3]]  # type: ignore[attr-defined]
