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

from epaper_dithering import ColorPalette, ColorScheme, DitherMode, dither_image
from PIL import Image

from .models import TagType

# epaper-dithering's schemes, by the colours a tag type lists.
_SCHEMES: dict[frozenset[str], ColorScheme] = {
    frozenset({"white", "black"}): ColorScheme.MONO,
    frozenset({"white", "black", "red"}): ColorScheme.BWR,
    frozenset({"white", "black", "yellow"}): ColorScheme.BWY,
    frozenset({"white", "black", "red", "yellow"}): ColorScheme.BWRY,
    frozenset({"white", "black", "red", "yellow", "green", "blue"}): ColorScheme.BWGBRY,
}


def color_scheme(tag_type: TagType) -> ColorScheme | None:
    """The epaper-dithering scheme with the colours of *tag_type*, if there is one."""
    return _SCHEMES.get(frozenset(tag_type.color_table))


def palette(tag_type: TagType) -> ColorPalette:
    """The palette to dither for *tag_type*: its colours as the panel shows them.

    With a scheme, the colours are listed in the scheme's order rather than the
    colortable's. epaper-dithering up to 6.1.1 gives pixels that exactly match a
    scheme colour the scheme's index, so any other order mixes up their inks.
    """
    scheme = color_scheme(tag_type)
    shown = tag_type.display_colors
    names = list(scheme.palette.colors) if scheme else list(shown)
    return ColorPalette(
        colors={name: (shown[name][0], shown[name][1], shown[name][2]) for name in names},
        accent=tag_type.accent_color or "black",
        scheme=scheme,
    )


def dither_for_tag(
    image: Image.Image,
    tag_type: TagType,
    mode: DitherMode = DitherMode.FLOYD_STEINBERG,
) -> Image.Image:
    """Dither *image* for *tag_type*, ready to upload.

    Returns a palette-mode image in the tag type's ``colortable`` colours. Its
    indices follow :func:`palette`, not the colortable. Use :func:`as_displayed`
    on it to see how the panel will show it.
    """
    dithered = dither_image(image, palette(tag_type), mode=mode)
    dithered.putpalette(_flatten(_in_palette_order(tag_type.color_table, tag_type)))
    return dithered


def as_displayed(image: Image.Image, tag_type: TagType) -> Image.Image:
    """How the panel shows *image*, an image from :func:`dither_for_tag`."""
    shown = image.copy()
    shown.putpalette(_flatten(_in_palette_order(tag_type.display_colors, tag_type)))
    return shown


def _in_palette_order(colors: dict[str, list[int]], tag_type: TagType) -> list[list[int]]:
    """*colors*, by name, in the order of :func:`palette`'s indices."""
    return [colors[name] for name in palette(tag_type).colors]


def _flatten(colors: object) -> list[int]:
    return [channel for rgb in colors for channel in rgb[:3]]  # type: ignore[attr-defined]
