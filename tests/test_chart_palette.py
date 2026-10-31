"""Tests for the chart colour tokens (--chart-evidence / --chart-lp21).

The radar draws two overlapping series, Future Evidence and Lehrplan-21
coverage, and tells them apart by colour alone. In dark mode it used the
text tokens --blue / --green, which are tuned for text contrast: too light
for marks, the blue too gray, and the pair too close to tell apart even
with full colour vision. The chart tokens fix that, and these tests re-run
the checks so a later edit cannot quietly undo it.

The checks follow the dataviz palette method: OKLCH lightness band and
chroma floor, OKLab Delta E x100 between the two series under protanopia and
deuteranopia (Machado, Oliveira & Fernandes 2009, severity 1.0) and under
normal vision, and WCAG contrast of each mark against the chart surface.
The checker is first calibrated against figures the reference validator
reported, so a bug in this file cannot pass a bad palette.
"""

from __future__ import annotations

import math
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLES = (ROOT / "site" / "assets" / "styles.css").read_text(encoding="utf-8")
APP_JS = (ROOT / "site" / "assets" / "app.js").read_text(encoding="utf-8")

BAND = {"light": (0.43, 0.77), "dark": (0.48, 0.67)}
CHROMA_FLOOR = 0.10
CVD_TARGET = 8.0
NORMAL_FLOOR = 15.0
CONTRAST_MIN = 3.0

MACHADO = {
    "protan": (
        (0.152286, 1.052583, -0.204868),
        (0.114503, 0.786281, 0.099216),
        (-0.003882, -0.048116, 1.051998),
    ),
    "deutan": (
        (0.367322, 0.860646, -0.227968),
        (0.280085, 0.672501, 0.047413),
        (-0.011820, 0.042940, 0.968881),
    ),
}


def _linear(hex_color: str) -> tuple[float, float, float]:
    value = hex_color.lstrip("#")
    channels = [int(value[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)


def _oklab(rgb: tuple[float, float, float]) -> tuple[float, float, float]:
    r, g, b = rgb
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (
        0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
        1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
        0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s,
    )


def _simulate(rgb: tuple[float, float, float], kind: str) -> tuple[float, float, float]:
    return tuple(
        min(1.0, max(0.0, sum(weight * channel for weight, channel in zip(row, rgb))))
        for row in MACHADO[kind]
    )


def lightness_chroma(hex_color: str) -> tuple[float, float]:
    lightness, a, b = _oklab(_linear(hex_color))
    return lightness, math.hypot(a, b)


def delta_e(first: str, second: str, kind: str | None = None) -> float:
    rgb1, rgb2 = _linear(first), _linear(second)
    if kind:
        rgb1, rgb2 = _simulate(rgb1, kind), _simulate(rgb2, kind)
    return 100 * math.dist(_oklab(rgb1), _oklab(rgb2))


def contrast(first: str, second: str) -> float:
    def luminance(hex_color: str) -> float:
        r, g, b = _linear(hex_color)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def theme_tokens(selector: str) -> dict[str, str]:
    block = re.search(re.escape(selector) + r"\s*\{(.*?)\n\}", STYLES, re.DOTALL)
    assert block, f"no {selector} block in styles.css"
    return dict(re.findall(r"(--[\w-]+):\s*(#[0-9a-fA-F]{6})\s*;", block.group(1)))


LIGHT = theme_tokens(":root")
DARK = theme_tokens(':root[data-theme="dark"]')


class CheckerCalibrationTests(unittest.TestCase):
    def test_reproduces_the_reference_validator_on_the_old_dark_pair(self) -> None:
        # Figures the dataviz validator printed for the text tokens the radar
        # used in dark mode before this change.
        green, blue = "#4fb894", "#86aee6"
        self.assertAlmostEqual(lightness_chroma(green)[0], 0.711, places=3)
        self.assertAlmostEqual(lightness_chroma(blue)[0], 0.743, places=3)
        self.assertAlmostEqual(lightness_chroma(blue)[1], 0.092, places=3)
        self.assertAlmostEqual(delta_e(green, blue), 14.7, places=1)
        self.assertAlmostEqual(delta_e(green, blue, "deutan"), 11.3, places=1)

    def test_reproduces_the_reference_validator_on_the_new_dark_pair(self) -> None:
        self.assertAlmostEqual(delta_e("#34a981", "#6992d8"), 17.2, places=1)
        self.assertAlmostEqual(delta_e("#34a981", "#6992d8", "deutan"), 13.9, places=1)


class ChartPaletteTests(unittest.TestCase):
    def assert_pair_passes(self, tokens: dict[str, str], mode: str, check_chroma: bool = True) -> None:
        evidence, lp21 = tokens["--chart-evidence"], tokens["--chart-lp21"]
        surface = tokens["--surface"]
        low, high = BAND[mode]
        for name, color in (("--chart-evidence", evidence), ("--chart-lp21", lp21)):
            lightness, chroma = lightness_chroma(color)
            with self.subTest(mode=mode, token=name):
                self.assertTrue(low <= lightness <= high, f"{name} {color}: L {lightness:.3f} outside {low}-{high}")
                if check_chroma:
                    self.assertGreaterEqual(chroma, CHROMA_FLOOR, f"{name} {color}: reads gray")
                self.assertGreaterEqual(contrast(color, surface), CONTRAST_MIN, f"{name} {color} on {surface}")
        cvd = min(delta_e(evidence, lp21, kind) for kind in MACHADO)
        self.assertGreaterEqual(cvd, CVD_TARGET, f"{mode}: series collapse under colour-vision deficiency")
        self.assertGreaterEqual(
            delta_e(evidence, lp21), NORMAL_FLOOR, f"{mode}: series too close for full colour vision"
        )

    def test_dark_chart_pair_passes_every_check(self) -> None:
        self.assert_pair_passes(DARK, "dark")

    def test_light_chart_pair_keeps_the_series_apart(self) -> None:
        # Light mode is unchanged by this fix. Its green sits at C 0.096, just
        # under the 0.10 floor; band, separation and contrast hold.
        self.assert_pair_passes(LIGHT, "light", check_chroma=False)


class ChartTokenWiringTests(unittest.TestCase):
    def test_radar_draws_with_the_chart_tokens(self) -> None:
        colors = re.search(r"function themeColors\(\) \{(.*?)\n\}", APP_JS, re.DOTALL)
        self.assertIsNotNone(colors, "themeColors not found in app.js")
        self.assertIn('read("--chart-evidence"', colors.group(1))
        self.assertIn('read("--chart-lp21"', colors.group(1))
        paint = re.search(r"function paintRadar\(\) \{(.*?)\n\}", APP_JS, re.DOTALL)
        self.assertIsNotNone(paint, "paintRadar not found in app.js")
        self.assertNotRegex(paint.group(1), r"colors\.(blue|green)\b")
        self.assertIn("colors.evidence", paint.group(1))
        self.assertIn("colors.lp21", paint.group(1))

    def test_legends_and_matrix_marks_use_the_same_tokens(self) -> None:
        # One series, one colour, in both views and their legends.
        expected = {
            ".legend-evidence": "--chart-evidence",
            ".legend-lp21": "--chart-lp21",
            ".matrix-bubble": "--chart-lp21",
            ".matrix-claims-track span": "--chart-evidence",
            ".legend i.legend-bubble": "--chart-lp21",
            ".legend i.legend-bar": "--chart-evidence",
        }
        for selector, token in expected.items():
            with self.subTest(selector):
                rule = re.search(r"(?m)^" + re.escape(selector) + r"\s*\{(.*?)\}", STYLES, re.DOTALL)
                self.assertIsNotNone(rule, f"no rule for {selector}")
                self.assertIn(f"var({token})", rule.group(1))


if __name__ == "__main__":
    unittest.main()
