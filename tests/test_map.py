from __future__ import annotations

import geopandas as gpd

from src.ui.map import build_map


def test_priority_legend_keeps_zero_and_hundred_inside_responsive_layout(base_layers):
    areas, shelters = base_layers
    blindspots = gpd.GeoDataFrame({"geometry": []}, geometry="geometry", crs=areas.crs)

    rendered = build_map(
        areas,
        shelters,
        blindspots,
        radius_m=300,
    ).get_root().render()

    assert "priority-legend__ticks" in rendered
    assert "<span>0</span><span>50</span><span>100</span>" in rendered
    assert "justify-content: space-between" in rendered
    assert "width: min(280px, calc(100vw - 56px))" in rendered
    assert '.attr("width", 450)' not in rendered

