"""Draw the monthly cash-flow chart.

Two stacked panels share one x-axis instead of one crowded plot:

  * top    -- monthly flow: In and Out bars, with the net line over them
  * bottom -- cumulative capital deployed

They are split because the running total outgrows the monthly bars by roughly 2x
over a couple of years; drawn together on one scale the bars flatten into noise,
and putting the total on a second y-axis would invent a relationship that is not
in the data. Two panels, each with a single honest axis.

Colours come from theme.py and were checked with the data-viz validator. Values
are direct-labelled selectively (the extremes and the endpoint) -- the ledger
table beside the chart is the complete, always-available table view, so no number
is ever reachable only by hovering.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from matplotlib.patches import Patch
from matplotlib.path import Path as MplPath
from matplotlib.patches import PathPatch
from matplotlib.lines import Line2D
from matplotlib.ticker import FuncFormatter

from . import theme as theme_module
from .model import Summary

SCALES = {
    "raw": (1.0, "IDR"),
    "thousand": (1_000.0, "IDR thousands (rb)"),
    "million": (1_000_000.0, "IDR millions (jt)"),
}
SCALE_ORDER = ("raw", "thousand", "million")

MODE_FLOW = "flow"
MODE_CATEGORY = "category"
MODE_PURPOSE = "purpose"

_BAR_WIDTH = 0.38
_BAR_GAP = 0.02          # data-unit gap so adjacent bars are separated by surface, not a stroke
_CORNER_PX = 4.0
_SEGMENT_GAP_PX = 2.0


@dataclass
class ChartOptions:
    theme: str = "light"
    mode: str = MODE_FLOW
    scale: str = "million"
    show_cumulative: bool = True
    label_every_month: bool = False
    title: str = "Monthly cash flow"


@dataclass
class RenderResult:
    """What the app needs to wire up hover and read back what was drawn."""

    summary: Summary
    flow_axes: object = None
    cumulative_axes: object = None
    #: The axes whose x-position is a month index, so hover can map a pointer to
    #: a month. Excludes the purpose-mode totals panel, which is ranked by
    #: purpose rather than laid out over time.
    month_axes: tuple = ()
    scale: float = 1.0
    unit: str = "IDR"
    colors: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- helpers


def format_amount(value: float, decimals: int = 1) -> str:
    if value == 0:
        return "0"
    if abs(value) >= 100:
        return f"{value:,.0f}"
    return f"{value:,.{decimals}f}".rstrip("0").rstrip(".")


def _tick_formatter(_value, _pos=None):
    return f"{_value:,.0f}"


def _pixels_to_data(axes, dx_px, dy_px):
    """Convert a pixel distance into x and y data units for the current axes box."""
    inverse = axes.transData.inverted()
    x0, y0 = inverse.transform((0.0, 0.0))
    x1, y1 = inverse.transform((dx_px, dy_px))
    return abs(x1 - x0), abs(y1 - y0)


def _rounded_bar(axes, left, right, base, tip, radius_x, radius_y, color, zorder=2):
    """A bar whose data-end corners are rounded and whose baseline stays square."""
    height = tip - base
    if height == 0:
        return None
    sign = 1.0 if height > 0 else -1.0
    radius_y = min(abs(radius_y), abs(height))
    radius_x = min(abs(radius_x), (right - left) / 2.0)
    if radius_x <= 0 or radius_y <= 0:
        vertices = [(left, base), (left, tip), (right, tip), (right, base), (left, base)]
        codes = [MplPath.MOVETO] + [MplPath.LINETO] * 3 + [MplPath.CLOSEPOLY]
    else:
        shoulder = tip - sign * radius_y
        vertices = [
            (left, base),
            (left, shoulder),
            (left, tip), (left + radius_x, tip),          # rounded corner
            (right - radius_x, tip),
            (right, tip), (right, shoulder),              # rounded corner
            (right, base),
            (left, base),
        ]
        codes = [
            MplPath.MOVETO,
            MplPath.LINETO,
            MplPath.CURVE3, MplPath.CURVE3,
            MplPath.LINETO,
            MplPath.CURVE3, MplPath.CURVE3,
            MplPath.LINETO,
            MplPath.CLOSEPOLY,
        ]
    patch = PathPatch(MplPath(vertices, codes), facecolor=color, edgecolor="none", zorder=zorder)
    axes.add_patch(patch)
    return patch


def _style_axes(axes, palette, show_x=True):
    axes.set_facecolor(palette["surface"])
    axes.grid(axis="y", color=palette["grid"], linewidth=0.8, linestyle="-", zorder=0)
    axes.set_axisbelow(True)
    for side in ("top", "right", "left"):
        axes.spines[side].set_visible(False)
    axes.spines["bottom"].set_color(palette["axis"])
    axes.spines["bottom"].set_linewidth(0.8)
    axes.tick_params(axis="both", colors=palette["muted"], length=0, labelsize=8)
    axes.yaxis.set_major_formatter(FuncFormatter(_tick_formatter))
    if not show_x:
        axes.tick_params(axis="x", labelbottom=False)


def _month_ticks(axes, months, palette):
    """Thin the tick labels when the window is long, so they never collide."""
    count = len(months)
    step = max(1, math.ceil(count / 26))
    positions = list(range(0, count, step))
    if positions and positions[-1] != count - 1 and count - 1 - positions[-1] >= step / 2:
        positions.append(count - 1)
    axes.set_xticks(positions)
    axes.set_xticklabels(
        [months[i] for i in positions], rotation=45, ha="right", fontsize=8, color=palette["muted"]
    )


def _annotate(axes, x, y, text, color, above=True, weight="normal", size=8, dx=0, ha="center"):
    axes.annotate(
        text,
        xy=(x, y),
        xytext=(dx, 6 if above else -6),
        textcoords="offset points",
        ha=ha,
        va="bottom" if above else "top",
        fontsize=size,
        color=color,
        fontweight=weight,
        zorder=6,
        clip_on=False,
    )


def _headroom(low, high, pad=0.16):
    if high == low:
        span = abs(high) or 1.0
        return low - span * 0.5, high + span * 0.5
    span = high - low
    return low - span * (pad * 0.35), high + span * pad


# --------------------------------------------------------------------------- panels


def _draw_flow(axes, summary, palette, options, scale, colors):
    months = summary.months
    count = len(months)
    positions = list(range(count))
    inflow = [v / scale for v in summary.inflow]
    outflow = [v / scale for v in summary.outflow]
    net = [v / scale for v in summary.net]
    category_mode = options.mode == MODE_CATEGORY

    if category_mode:
        stack_in = {k: [v / scale for v in row] for k, row in summary.inflow_by_category.items()}
        stack_out = {k: [v / scale for v in row] for k, row in summary.outflow_by_category.items()}
        low = min([0.0] + [-v for v in outflow])
        high = max([0.0] + inflow + net)
        low = min(low, min(net) if net else 0.0)
    else:
        low = min([0.0] + net)
        high = max([0.0] + inflow + outflow + net)

    bottom, top = _headroom(low, high)
    # a little slack on the right so the net end-label has somewhere to sit
    axes.set_xlim(-0.7, count - 0.3 + 0.55)
    axes.set_ylim(bottom, top)

    corner_x, corner_y = _pixels_to_data(axes, _CORNER_PX, _CORNER_PX)
    _, segment_gap = _pixels_to_data(axes, 0, _SEGMENT_GAP_PX)

    if category_mode:
        for index in positions:
            for direction, stack in (("up", stack_in), ("down", stack_out)):
                cursor = 0.0
                names = [n for n in summary.categories if stack.get(n, [0])[index]]
                for order, name in enumerate(names):
                    value = stack[name][index]
                    sign = 1.0 if direction == "up" else -1.0
                    start = cursor
                    end = cursor + sign * value
                    # a 2px surface gap between touching marks -- between stacked
                    # segments, and across zero where the In and Out stacks meet
                    draw_start = start + sign * segment_gap / 2
                    _rounded_bar(
                        axes, index - 0.32, index + 0.32, draw_start, end,
                        corner_x, corner_y if order == len(names) - 1 else 0,
                        colors.get(name, palette["other"]),
                    )
                    cursor = end
        axes.axhline(0, color=palette["axis"], linewidth=0.8, zorder=1)
    else:
        offset = _BAR_WIDTH / 2 + _BAR_GAP / 2
        for index in positions:
            _rounded_bar(
                axes, index - offset - _BAR_WIDTH / 2, index - offset + _BAR_WIDTH / 2,
                0.0, inflow[index], corner_x, corner_y, palette["inflow"],
            )
            _rounded_bar(
                axes, index + offset - _BAR_WIDTH / 2, index + offset + _BAR_WIDTH / 2,
                0.0, outflow[index], corner_x, corner_y, palette["outflow"],
            )

    axes.plot(
        positions, net,
        color=palette["ink_2"], linewidth=2.0, solid_capstyle="round", solid_joinstyle="round",
        marker="o", markersize=5, markerfacecolor=palette["ink_2"],
        markeredgecolor=palette["surface"], markeredgewidth=1.6, zorder=5,
    )

    # Selective direct labels: the two extremes and the latest month.
    if count:
        if options.label_every_month:
            for index in positions:
                if inflow[index]:
                    _annotate(axes, index - 0.2, inflow[index], format_amount(inflow[index]), palette["ink_2"])
                if outflow[index]:
                    _annotate(axes, index + 0.2, outflow[index], format_amount(outflow[index]), palette["ink_2"])
        elif not category_mode:
            peak_in = max(positions, key=lambda i: inflow[i])
            peak_out = max(positions, key=lambda i: outflow[i])
            if inflow[peak_in]:
                _annotate(axes, peak_in - 0.2, inflow[peak_in], format_amount(inflow[peak_in]), palette["ink_2"], weight="bold")
            # When both peaks land in the same month their labels can overlap.
            # Two stacked numbers read worse than one, so drop the second.
            crowded = peak_out == peak_in and abs(inflow[peak_in] - outflow[peak_out]) < (top - bottom) * 0.15
            if outflow[peak_out] and not crowded:
                _annotate(axes, peak_out + 0.2, outflow[peak_out], format_amount(outflow[peak_out]), palette["ink_2"], weight="bold")
        # The net endpoint sits clear of the last month's bars, not on top of them.
        last = count - 1
        _annotate(
            axes, last, net[last], format_amount(net[last]), palette["ink_2"],
            above=net[last] >= 0, weight="bold", dx=10, ha="left",
        )

    handles = []
    if category_mode:
        handles = [
            Patch(facecolor=colors.get(name, palette["other"]), edgecolor="none", label=name)
            for name in summary.categories
        ]
        handles.append(Line2D([], [], color=palette["ink_2"], linewidth=2.0, marker="o", markersize=5, label="Net"))
    else:
        handles = [
            Patch(facecolor=palette["inflow"], edgecolor="none", label="In"),
            Patch(facecolor=palette["outflow"], edgecolor="none", label="Out"),
            Line2D([], [], color=palette["ink_2"], linewidth=2.0, marker="o", markersize=5, label="Net (In - Out)"),
        ]
    legend = axes.legend(
        handles=handles, loc="upper left", frameon=False, fontsize=8,
        ncol=min(len(handles), 4), handlelength=1.4, handleheight=0.9, columnspacing=1.4,
        borderpad=0.0, labelspacing=0.3,
    )
    for text in legend.get_texts():
        text.set_color(palette["ink_2"])

    # The panel subtitle is drawn at figure level in render(), where the gap to the
    # main title can be held at a fixed number of points regardless of figure size.


def _rounded_hbar(axes, bottom, top, base, tip, radius_x, radius_y, color, zorder=2):
    """A horizontal bar with its far end rounded and its baseline square."""
    width = tip - base
    if width == 0:
        return None
    sign = 1.0 if width > 0 else -1.0
    radius_x = min(abs(radius_x), abs(width))
    radius_y = min(abs(radius_y), (top - bottom) / 2.0)
    if radius_x <= 0 or radius_y <= 0:
        vertices = [(base, bottom), (tip, bottom), (tip, top), (base, top), (base, bottom)]
        codes = [MplPath.MOVETO] + [MplPath.LINETO] * 3 + [MplPath.CLOSEPOLY]
    else:
        shoulder = tip - sign * radius_x
        vertices = [
            (base, bottom),
            (shoulder, bottom),
            (tip, bottom), (tip, bottom + radius_y),
            (tip, top - radius_y),
            (tip, top), (shoulder, top),
            (base, top),
            (base, bottom),
        ]
        codes = [
            MplPath.MOVETO, MplPath.LINETO,
            MplPath.CURVE3, MplPath.CURVE3,
            MplPath.LINETO,
            MplPath.CURVE3, MplPath.CURVE3,
            MplPath.LINETO, MplPath.CLOSEPOLY,
        ]
    patch = PathPatch(MplPath(vertices, codes), facecolor=color, edgecolor="none", zorder=zorder)
    axes.add_patch(patch)
    return patch


def _draw_purpose(axes, summary, palette, options, scale, colors):
    """Monthly outflow, stacked by what it was spent on."""
    months = summary.months
    count = len(months)
    positions = list(range(count))
    stacks = {
        name: [value / scale for value in row]
        for name, row in summary.outflow_by_purpose.items()
    }
    outflow = [v / scale for v in summary.outflow]

    # extra headroom so the single-row legend clears the tallest stack
    bottom, top = _headroom(0.0, max([0.0] + outflow), pad=0.24)
    axes.set_xlim(-0.7, count - 0.3 + 0.55)
    axes.set_ylim(bottom, top)
    corner_x, corner_y = _pixels_to_data(axes, _CORNER_PX, _CORNER_PX)
    _, segment_gap = _pixels_to_data(axes, 0, _SEGMENT_GAP_PX)

    for index in positions:
        cursor = 0.0
        present = [name for name in summary.purposes if stacks.get(name, [0])[index]]
        for order, name in enumerate(present):
            value = stacks[name][index]
            start = cursor + (segment_gap / 2 if order else 0)
            end = cursor + value
            _rounded_bar(
                axes, index - 0.32, index + 0.32, start, end,
                corner_x, corner_y if order == len(present) - 1 else 0,
                colors.get(name, palette["other"]),
            )
            cursor = end

    if count:
        peak = max(positions, key=lambda i: outflow[i])
        if outflow[peak]:
            _annotate(axes, peak, outflow[peak], format_amount(outflow[peak]),
                      palette["ink_2"], weight="bold")

    handles = [
        Patch(facecolor=colors.get(name, palette["other"]), edgecolor="none", label=name)
        for name in summary.purposes
    ]
    legend = axes.legend(
        handles=handles, loc="upper left", frameon=False, fontsize=8,
        # one row: a wrapped legend drops into the plot area and covers bars
        ncol=max(len(handles), 1), handlelength=1.2, handleheight=0.9,
        columnspacing=1.1, borderpad=0.0, labelspacing=0.3,
    )
    for text in legend.get_texts():
        text.set_color(palette["ink_2"])


def _draw_purpose_totals(axes, summary, palette, scale, colors):
    """Where the money went over the whole window, biggest first."""
    totals = [(name, value / scale) for name, value in summary.purpose_totals()]
    if not totals:
        axes.axis("off")
        return
    # Drawn top-down, so the largest sits at the top of the panel.
    slots = list(range(len(totals)))[::-1]
    widest = max(value for _name, value in totals)
    axes.set_ylim(-0.7, len(totals) - 0.3)
    axes.set_xlim(0, widest * 1.24)

    corner_x, corner_y = _pixels_to_data(axes, _CORNER_PX, _CORNER_PX)
    _, thickness = _pixels_to_data(axes, 0, 22.0)   # cap the bar at 22px thick
    half = min(0.36, thickness / 2)

    grand = sum(value for _name, value in totals) or 1.0
    for slot, (name, value) in zip(slots, totals):
        _rounded_hbar(axes, slot - half, slot + half, 0.0, value,
                      corner_x, corner_y, colors.get(name, palette["other"]))
        axes.annotate(
            f"{format_amount(value)}   {value / grand:.0%}",
            xy=(value, slot), xytext=(8, 0), textcoords="offset points",
            va="center", ha="left", fontsize=8, color=palette["ink_2"], clip_on=False,
        )

    axes.set_yticks(slots)
    axes.set_yticklabels([name for name, _value in totals], fontsize=8, color=palette["ink_2"])
    axes.grid(axis="y", visible=False)
    axes.grid(axis="x", color=palette["grid"], linewidth=0.8, linestyle="-", zorder=0)
    axes.set_title(
        "Total by purpose over the whole window",
        loc="left", fontsize=9, color=palette["muted"], pad=6,
    )


def _draw_cumulative(axes, summary, palette, scale):
    months = summary.months
    positions = list(range(len(months)))
    values = [v / scale for v in summary.cumulative]
    color = palette["cumulative"]

    low, high = min([0.0] + values), max([0.0] + values)
    bottom, top = _headroom(low, high, pad=0.22)
    axes.set_ylim(bottom, top)

    axes.fill_between(positions, 0, values, color=color, alpha=0.10, linewidth=0, zorder=1)
    # A marker on every month, matching the net line above, so each point reads
    # as something you can put the pointer on. The surface-coloured ring keeps
    # them legible where they sit close together on a long window.
    axes.plot(
        positions, values, color=color, linewidth=2.0,
        solid_capstyle="round", solid_joinstyle="round",
        marker="o", markersize=5, markerfacecolor=color,
        markeredgecolor=palette["surface"], markeredgewidth=1.6, zorder=3,
    )
    if positions:
        last = positions[-1]
        axes.plot(
            [last], [values[last]], marker="o", markersize=7, color=color,
            markeredgecolor=palette["surface"], markeredgewidth=1.8, zorder=4,
        )
        _annotate(axes, last, values[last], format_amount(values[last]), palette["ink_2"], weight="bold", size=9)
    # One series -- the panel title names it, so no legend box.
    axes.set_title(
        "Cumulative capital deployed (running total of net)",
        loc="left", fontsize=9, color=palette["muted"], pad=6,
    )


def _draw_empty(figure, palette, message):
    axes = figure.add_subplot(111)
    axes.set_facecolor(palette["surface"])
    axes.axis("off")
    axes.text(
        0.5, 0.5, message, ha="center", va="center",
        fontsize=11, color=palette["muted"], transform=axes.transAxes,
    )
    return axes


# --------------------------------------------------------------------------- entry point


def render(figure, ledger, options: ChartOptions, month_from=None, month_to=None, categories=None):
    """Draw the whole figure and return what was drawn."""
    palette = theme_module.theme(options.theme)
    figure.clear()
    figure.patch.set_facecolor(palette["plane"])

    summary = ledger.summarize(month_from=month_from, month_to=month_to, categories=categories)
    scale, unit = SCALES.get(options.scale, SCALES["raw"])
    colors = theme_module.category_colors(ledger.categories, palette)

    if not summary:
        message = (
            "No rows yet.\n\nFile > Import Bibit report to load an export,\n"
            "or Add row to start typing months in by hand."
            if not ledger.entries
            else "Nothing matches the current filters."
        )
        _draw_empty(figure, palette, message)
        return RenderResult(summary=summary, scale=scale, unit=unit, colors=colors)

    # Title block height is expressed in points, then converted, so the gap between
    # the title and the subtitle stays constant whatever size the window is.
    height_points = max(figure.get_figheight(), 1.0) * 72.0
    title_y = 1.0 - 16.0 / height_points
    subtitle_y = 1.0 - 34.0 / height_points
    top_margin = 1.0 - 58.0 / height_points
    # rotated month labels need ~62pt; anything more is dead space at the bottom
    bottom_margin = 62.0 / height_points
    left = 0.095

    purpose_mode = options.mode == MODE_PURPOSE
    if purpose_mode:
        # The lower panel is a ranked horizontal bar chart with its own scale and
        # its own labels, so it must not share the month axis.
        left = 0.135

    if options.show_cumulative:
        figure.subplots_adjust(left=left, right=0.975, top=top_margin, bottom=bottom_margin, hspace=0.34)
        flow_axes = figure.add_subplot(2, 1, 1)
        cumulative_axes = figure.add_subplot(2, 1, 2, sharex=None if purpose_mode else flow_axes)
    else:
        figure.subplots_adjust(left=left, right=0.975, top=top_margin, bottom=bottom_margin)
        flow_axes = figure.add_subplot(1, 1, 1)
        cumulative_axes = None

    months_on_top = purpose_mode or cumulative_axes is None
    _style_axes(flow_axes, palette, show_x=months_on_top)
    if cumulative_axes is not None:
        _style_axes(cumulative_axes, palette, show_x=True)

    figure.text(
        left, title_y, options.title, ha="left", va="top",
        fontsize=13, fontweight="semibold", color=palette["ink"],
    )
    subtitles = {
        MODE_CATEGORY: "In above the line, Out below, by category",
        MODE_PURPOSE: "Where each month's outflow went",
        MODE_FLOW: "Money in vs money out, per month",
    }
    figure.text(
        left, subtitle_y, subtitles.get(options.mode, subtitles[MODE_FLOW]),
        ha="left", va="top", fontsize=9, color=palette["muted"],
    )

    if purpose_mode:
        purpose_palette = theme_module.purpose_colors(ledger.purposes, palette)
        _draw_purpose(flow_axes, summary, palette, options, scale, purpose_palette)
        colors = purpose_palette
    else:
        _draw_flow(flow_axes, summary, palette, options, scale, colors)
    flow_axes.set_ylabel(unit, fontsize=8, color=palette["muted"])

    if cumulative_axes is not None:
        if purpose_mode:
            _draw_purpose_totals(cumulative_axes, summary, palette, scale, colors)
            cumulative_axes.set_xlabel(unit, fontsize=8, color=palette["muted"])
        else:
            _draw_cumulative(cumulative_axes, summary, palette, scale)
            cumulative_axes.set_ylabel(unit, fontsize=8, color=palette["muted"])

    _month_ticks(flow_axes if months_on_top else cumulative_axes, summary.months, palette)

    month_axes = [flow_axes]
    if cumulative_axes is not None and not purpose_mode:
        month_axes.append(cumulative_axes)

    return RenderResult(
        summary=summary,
        flow_axes=flow_axes,
        cumulative_axes=cumulative_axes,
        month_axes=tuple(month_axes),
        scale=scale,
        unit=unit,
        colors=colors,
    )


# --------------------------------------------------------------------------- projection


@dataclass
class ProjectionRender:
    """What the projection window needs for hover: the axes and the month layout."""

    projection: object
    months: list = field(default_factory=list)
    #: index of the first projected month in `months`; everything before is actual
    split: int = 0
    flow_axes: object = None
    balance_axes: object = None
    scale: float = 1.0
    unit: str = "IDR"


def render_projection(figure, projection, theme="light", scale_name="million", show_history=True):
    """Two panels over one month axis: what goes in each month, and where the balance gets to.

    Actual history is drawn first, in solid strokes and neutral bars; the
    projection follows it in the series colours with a dashed balance line, and
    a rule marks where one stops and the other starts -- a forecast should never
    be mistakable for a record.
    """
    palette = theme_module.theme(theme)
    figure.clear()
    figure.patch.set_facecolor(palette["plane"])
    scale, unit = SCALES.get(scale_name, SCALES["raw"])

    if not projection:
        _draw_empty(figure, palette, "Nothing to project yet.")
        return ProjectionRender(projection, scale=scale, unit=unit)

    history = len(projection.history_months) if show_history else 0
    past_months = projection.history_months[-history:] if history else []
    months = past_months + list(projection.months)
    split = history
    count = len(months)
    positions = list(range(count))
    bonus_color = palette["series"][3]

    height_points = max(figure.get_figheight(), 1.0) * 72.0
    title_y = 1.0 - 16.0 / height_points
    subtitle_y = 1.0 - 34.0 / height_points
    left = 0.095
    figure.subplots_adjust(left=left, right=0.975, top=1.0 - 58.0 / height_points,
                           bottom=62.0 / height_points, hspace=0.34)
    flow_axes = figure.add_subplot(2, 1, 1)
    balance_axes = figure.add_subplot(2, 1, 2, sharex=flow_axes)
    _style_axes(flow_axes, palette, show_x=False)
    _style_axes(balance_axes, palette, show_x=True)

    figure.text(left, title_y, f"Projection - next {len(projection.months)} months",
                ha="left", va="top", fontsize=13, fontweight="semibold", color=palette["ink"])
    figure.text(left, subtitle_y,
                "What each month saves from salary and bonus, and the balance it builds",
                ha="left", va="top", fontsize=9, color=palette["muted"])

    # -- top: monthly saving under the salary line --------------------------
    past_net = [v / scale for v in projection.history_net[-history:]] if history else []
    past_salary = [v / scale for v in projection.history_salary[-history:]] if history else []
    from_salary = [v / scale for v in projection.saved_salary]
    from_bonus = [v / scale for v in projection.saved_bonus]
    salary = past_salary + [v / scale for v in projection.salary]

    low = min([0.0] + past_net)
    high = max([0.0] + past_net + salary + [a + b for a, b in zip(from_salary, from_bonus)])
    bottom, top = _headroom(low, high, pad=0.24)
    # room on the right for the end labels, which sit beside the last month
    flow_axes.set_xlim(-0.7, count - 0.3 + max(1.5, count * 0.07))
    flow_axes.set_ylim(bottom, top)
    corner_x, corner_y = _pixels_to_data(flow_axes, _CORNER_PX, _CORNER_PX)
    _, segment_gap = _pixels_to_data(flow_axes, 0, _SEGMENT_GAP_PX)

    for index, value in enumerate(past_net):
        _rounded_bar(flow_axes, index - 0.32, index + 0.32, 0.0, value, corner_x, corner_y, palette["axis"])
    for offset, (base, extra) in enumerate(zip(from_salary, from_bonus)):
        index = split + offset
        _rounded_bar(flow_axes, index - 0.32, index + 0.32, 0.0, base,
                     corner_x, 0 if extra else corner_y, palette["inflow"])
        if extra:
            _rounded_bar(flow_axes, index - 0.32, index + 0.32, base + segment_gap / 2, base + extra,
                         corner_x, corner_y, bonus_color)
    if any(salary):
        flow_axes.step(positions, salary, where="mid", color=palette["ink_2"], linewidth=1.4, zorder=4)
        _annotate(flow_axes, count - 1, salary[-1], format_amount(salary[-1]), palette["ink_2"],
                  weight="bold", dx=10, ha="left")
    flow_axes.set_ylabel(unit, fontsize=8, color=palette["muted"])

    handles = []
    if history:
        handles.append(Patch(facecolor=palette["axis"], edgecolor="none", label="Actual net"))
    handles += [
        Patch(facecolor=palette["inflow"], edgecolor="none", label="Saved from salary"),
        Patch(facecolor=bonus_color, edgecolor="none", label="Saved from bonus"),
        Line2D([], [], color=palette["ink_2"], linewidth=1.4, label="Monthly salary"),
    ]
    legend = flow_axes.legend(handles=handles, loc="upper left", frameon=False, fontsize=8,
                              ncol=len(handles), handlelength=1.4, handleheight=0.9,
                              columnspacing=1.4, borderpad=0.0)
    for text in legend.get_texts():
        text.set_color(palette["ink_2"])

    # -- bottom: balance ----------------------------------------------------
    color = palette["cumulative"]
    past = [v / scale for v in projection.history_balance[-history:]] if history else []
    ahead = [v / scale for v in projection.balance]
    contributed = [v / scale for v in projection.contributed]
    grows = any(projection.growth)
    low, high = min([0.0] + past + ahead), max([0.0] + past + ahead)
    bottom, top = _headroom(low, high, pad=0.22)
    balance_axes.set_ylim(bottom, top)

    if past:
        balance_axes.fill_between(range(split), 0, past, color=color, alpha=0.10, linewidth=0, zorder=1)
        # no per-month markers here: next to the dashed projection they read as
        # dots, and the solid/dashed contrast is the point of the panel
        balance_axes.plot(range(split), past, color=color, linewidth=2.0,
                          solid_joinstyle="round", zorder=3)
    # The projected line starts from the last actual point, so the two join up.
    lead_x = [split - 1] if past else []
    lead_y = [past[-1]] if past else []
    ahead_x = lead_x + list(range(split, count))
    balance_axes.plot(ahead_x, lead_y + ahead, color=color, linewidth=2.0,
                      linestyle=(0, (4, 2.5)), dash_capstyle="round", zorder=3)
    if grows:
        balance_axes.plot(ahead_x, lead_y + contributed, color=palette["muted"], linewidth=1.2,
                          linestyle=(0, (1.5, 2)), zorder=2)
        _annotate(balance_axes, count - 1, contributed[-1], f"{format_amount(contributed[-1])} saved",
                  palette["muted"], above=False, dx=10, ha="left")
    balance_axes.plot([count - 1], [ahead[-1]], marker="o", markersize=7, color=color,
                      markeredgecolor=palette["surface"], markeredgewidth=1.8, zorder=4)
    _annotate(balance_axes, count - 1, ahead[-1], format_amount(ahead[-1]), palette["ink_2"],
              weight="bold", size=9)
    if past:
        _annotate(balance_axes, split - 1, past[-1], format_amount(past[-1]), palette["ink_2"])
    balance_axes.set_title(
        "Balance - actual capital deployed, then projected (dashed)"
        + ("; dotted grey is what you put in, without growth" if grows else ""),
        loc="left", fontsize=9, color=palette["muted"], pad=6,
    )
    balance_axes.set_ylabel(unit, fontsize=8, color=palette["muted"])

    if split:
        for axes in (flow_axes, balance_axes):
            axes.axvline(split - 0.5, color=palette["axis"], linewidth=1.0, zorder=1)
        flow_axes.annotate("projected", xy=(split - 0.5, 0.0), xycoords=("data", "axes fraction"),
                           xytext=(5, 4), textcoords="offset points", ha="left", va="bottom",
                           fontsize=8, color=palette["muted"])

    _month_ticks(balance_axes, months, palette)
    return ProjectionRender(projection, months=months, split=split, flow_axes=flow_axes,
                            balance_axes=balance_axes, scale=scale, unit=unit)
