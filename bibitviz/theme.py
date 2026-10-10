"""Chart palette.

Both modes are selected (the dark column is the same hues re-stepped for the dark
surface, not an automatic flip). Every set here was checked with the data-viz
validator: the In/Out pair passes all-pairs in both modes, and the 8 categorical
slots pass the adjacent gates in both modes. Three light-mode categorical slots
sit below 3:1 against the light surface, so the "relief" rule applies -- the app
ships the ledger table as the always-available table view of every value.

Categorical slots are assigned in fixed order and never cycled: a 9th category
folds into "Other" rather than inventing a hue.
"""

LIGHT = {
    "name": "light",
    "surface": "#fcfcfb",
    "plane": "#f9f9f7",
    "ink": "#0b0b0b",
    "ink_2": "#52514e",
    "muted": "#898781",
    "grid": "#e1e0d9",
    "axis": "#c3c2b7",
    "inflow": "#2a78d6",
    "outflow": "#e34948",
    "cumulative": "#4a3aa7",
    "series": [
        "#2a78d6", "#eb6834", "#1baf7a", "#eda100",
        "#e87ba4", "#008300", "#4a3aa7", "#e34948",
    ],
    "other": "#898781",
    # Tk chrome
    "ui_bg": "#f9f9f7",
    "ui_field": "#ffffff",
    "ui_text": "#0b0b0b",
    "ui_border": "#dedcd4",
    # Ledger row text. Green/red is the ledger convention and is safe here in a
    # way it would not be in the chart: the In / Out column spells the direction
    # out, so colour repeats the answer rather than being the only way to read
    # it. Both clear 4.5:1 on the row background and on the untagged tint, and
    # are within 0.3 of each other so neither reads as the heavier colour.
    "row_in": "#1a7f37",
    "row_out": "#cf222e",
}

DARK = {
    "name": "dark",
    "surface": "#1a1a19",
    "plane": "#0d0d0d",
    "ink": "#ffffff",
    "ink_2": "#c3c2b7",
    "muted": "#898781",
    "grid": "#2c2c2a",
    "axis": "#383835",
    "inflow": "#3987e5",
    "outflow": "#e66767",
    "cumulative": "#9085e9",
    "series": [
        "#3987e5", "#d95926", "#199e70", "#c98500",
        "#d55181", "#008300", "#9085e9", "#e66767",
    ],
    "other": "#898781",
    "ui_bg": "#0d0d0d",
    "ui_field": "#242422",
    "ui_text": "#ffffff",
    "ui_border": "#383835",
    "row_in": "#3fb950",
    "row_out": "#ff7b72",
}

THEMES = {"light": LIGHT, "dark": DARK}
MAX_SERIES_SLOTS = 8


def theme(name):
    return THEMES.get(name, LIGHT)


def category_colors(categories, palette):
    """Map categories to hues by their fixed position, so a filter never repaints
    the survivors. Everything past slot 8 shares the neutral "Other" swatch."""
    slots = palette["series"]
    colors = {}
    for index, name in enumerate(categories):
        colors[name] = slots[index] if index < MAX_SERIES_SLOTS else palette["other"]
    return colors


def purpose_colors(purposes, palette, untagged="Untagged"):
    """Same fixed-slot rule as categories, but "Untagged" is never given a hue.

    Untagged is the absence of an answer, not another kind of spending, so it
    wears a neutral grey and stacks last. Past eight real purposes the tail
    shares the "Other" grey -- that is the point at which the list wants
    consolidating rather than a ninth invented colour.
    """
    named = [name for name in purposes if name != untagged]
    colors = category_colors(named, palette)
    colors[untagged] = palette["axis"]
    return colors
