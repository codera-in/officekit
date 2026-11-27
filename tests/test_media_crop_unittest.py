from fractions import Fraction

import pytest

from officekit.engines.engine_media_crop import crop_rectangle, parse_crop_aspect_ratio, smart_crop_rectangle


@pytest.mark.parametrize("ratio", [None, "", "1", "1:1:1", "1e2:1", "1.12345:1", "-1:1", "0:1", "1:0", "100:1", "1:100", "1.0001:1"])
def test_crop_ratio_rejects_ambiguous_unbounded_or_degenerate_targets(ratio):
    with pytest.raises(ValueError):
        parse_crop_aspect_ratio(ratio)


def test_crop_ratio_preserves_orientation_and_reduces_decimal_sides():
    assert parse_crop_aspect_ratio("1.50:1") == Fraction(3, 2)
    assert parse_crop_aspect_ratio("1:1.50") == Fraction(2, 3)


@pytest.mark.parametrize("width,height", [(True, 100), (0, 100), (100, -1), (40_001, 100)])
def test_crop_geometry_rejects_invalid_source_bounds(width, height):
    with pytest.raises(ValueError):
        crop_rectangle(width, height, "1:1")


@pytest.mark.parametrize("ratio", [0, Fraction(0), None])
def test_crop_geometry_rejects_invalid_preparsed_ratio(ratio):
    with pytest.raises(ValueError):
        crop_rectangle(100, 200, ratio)


def test_centered_crop_never_upscales_or_escapes_source_even_at_one_pixel():
    for width in (1, 2, 32, 10_000):
        for height in (1, 2, 32, 10_000):
            for ratio in ("1:10", "1:1", "10:1"):
                crop = crop_rectangle(width, height, ratio)
                assert 1 <= crop["width"] <= width and 1 <= crop["height"] <= height
                assert 0 <= crop["x"] <= width - crop["width"]
                assert 0 <= crop["y"] <= height - crop["height"]


@pytest.mark.parametrize("saliency", [None, {}, {"detected": 1}, {"detected": True},
    {"detected": True, "x": float("nan"), "y": 0, "width": 0.1, "height": 0.1},
    {"detected": True, "x": 0.9, "y": 0, "width": 0.2, "height": 0.1},
    {"detected": True, "x": 0, "y": 0, "width": 0, "height": 0.1},
])
def test_smart_crop_rejects_untrusted_or_out_of_source_focus(saliency):
    with pytest.raises(ValueError):
        smart_crop_rectangle(200, 100, "1:1", saliency)


def test_smart_crop_uses_bottom_left_vision_coordinates_and_clamps_subject_edges():
    focus = {"detected": True, "x": 0.8, "y": 0.8, "width": 0.2, "height": 0.2}
    assert smart_crop_rectangle(100, 200, "1:1", focus) == {"x": 0, "y": 0, "width": 100, "height": 100}
    assert smart_crop_rectangle(200, 100, "1:1", focus) == {"x": 100, "y": 0, "width": 100, "height": 100}
    assert smart_crop_rectangle(200, 100, "1:1", {"detected": False}) == crop_rectangle(200, 100, "1:1")
