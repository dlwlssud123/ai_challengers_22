"""Folium map layers for risk, shelters, blind spots, and recommendations."""

from __future__ import annotations

from html import escape

import folium
import geopandas as gpd
from branca.colormap import LinearColormap
from branca.element import MacroElement, Template
from folium.plugins import MarkerCluster
from shapely.geometry import Point, mapping

from src.analysis.accessibility import build_coverage_union


class PriorityLegend(MacroElement):
    """Responsive Leaflet legend whose endpoint labels stay inside the map."""

    _template = Template(
        """
        {% macro header(this, kwargs) %}
        <style>
          .priority-legend {
            box-sizing: border-box;
            width: min(280px, calc(100vw - 56px));
            max-width: calc(100% - 20px);
            padding: 10px 12px 8px;
            overflow: visible;
            border: 1px solid rgba(15, 23, 42, 0.18);
            border-radius: 8px;
            background: rgba(255, 255, 255, 0.96);
            box-shadow: 0 1px 5px rgba(15, 23, 42, 0.20);
            color: #111827;
            font: 12px/1.25 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          }
          .priority-legend__title {
            margin-bottom: 7px;
            overflow-wrap: anywhere;
            font-weight: 600;
          }
          .priority-legend__bar {
            box-sizing: border-box;
            width: 100%;
            height: 11px;
            border: 1px solid rgba(15, 23, 42, 0.18);
            background: linear-gradient(90deg, #2C7BB6 0%, #FFFFBF 50%, #D7191C 100%);
          }
          .priority-legend__ticks {
            display: flex;
            width: 100%;
            margin-top: 3px;
            justify-content: space-between;
            font-variant-numeric: tabular-nums;
            white-space: nowrap;
          }
          .priority-legend__ticks span:first-child { text-align: left; }
          .priority-legend__ticks span:last-child { text-align: right; }
          @media (max-width: 480px) {
            .priority-legend {
              width: min(230px, calc(100vw - 48px));
              padding: 8px 10px 7px;
              font-size: 11px;
            }
          }
        </style>
        {% endmacro %}
        {% macro script(this, kwargs) %}
        var {{ this.get_name() }} = L.control({position: "topright"});
        {{ this.get_name() }}.onAdd = function (map) {
          var div = L.DomUtil.create("div", "priority-legend leaflet-control");
          div.setAttribute("role", "img");
          div.setAttribute("aria-label", "폭염 대응 정책 우선순위 범례: 0에서 100");
          div.innerHTML = [
            '<div class="priority-legend__title">폭염 대응 정책 우선순위</div>',
            '<div class="priority-legend__bar"></div>',
            '<div class="priority-legend__ticks"><span>0</span><span>50</span><span>100</span></div>'
          ].join("");
          L.DomEvent.disableClickPropagation(div);
          return div;
        };
        {{ this.get_name() }}.addTo({{ this._parent.get_name() }});
        {% endmacro %}
        """
    )

    def __init__(self) -> None:
        super().__init__()
        self._name = "PriorityLegend"


def _coverage_geojson(shelters: gpd.GeoDataFrame, radius_m: float) -> dict:
    geometry = build_coverage_union(shelters, radius_m)
    display = gpd.GeoSeries([geometry], crs="EPSG:5179").to_crs("EPSG:4326").iloc[0]
    return mapping(display)


def nearest_area_name(areas: gpd.GeoDataFrame, latitude: float, longitude: float) -> str | None:
    """Resolve a clicked WGS84 point to its containing demo/actual area."""

    display = areas.to_crs("EPSG:4326")
    point = Point(longitude, latitude)
    contained = display[display.geometry.covers(point)]
    if not contained.empty:
        return str(contained.iloc[0]["adm_name"])
    distances = display.geometry.distance(point)
    return str(display.loc[distances.idxmin(), "adm_name"]) if len(display) else None


def build_map(
    areas: gpd.GeoDataFrame,
    shelters: gpd.GeoDataFrame,
    blindspots: gpd.GeoDataFrame,
    *,
    radius_m: float,
    selected_candidates: gpd.GeoDataFrame | None = None,
    after_shelters: gpd.GeoDataFrame | None = None,
    dark_mode: bool = False,
) -> folium.Map:
    """Build an operational layer-controlled map."""

    display_areas = areas.to_crs("EPSG:4326")
    center = display_areas.geometry.union_all().centroid
    fmap = folium.Map(
        location=[center.y, center.x],
        zoom_start=12,
        tiles="CartoDB dark_matter" if dark_mode else "CartoDB positron",
        control_scale=True,
    )
    colormap = LinearColormap(["#2C7BB6", "#FFFFBF", "#D7191C"], vmin=0, vmax=100)
    PriorityLegend().add_to(fmap)
    folium.GeoJson(
        display_areas,
        name="1. 폭염 대응 우선도",
        style_function=lambda feature: {
            "fillColor": colormap(feature["properties"]["priority_score"]),
            "color": "#374151",
            "weight": 1,
            "fillOpacity": 0.58,
        },
        highlight_function=lambda _: {"weight": 3, "color": "#111827"},
        tooltip=folium.GeoJsonTooltip(
            fields=[
                "adm_name", "priority_score", "heat_score", "vulnerability_score", "access_score",
            ],
            aliases=["행정동", "정책 우선순위", "기상 위험", "고령 취약성", "접근성 부족"],
            localize=True,
        ),
    ).add_to(fmap)

    marker_group = MarkerCluster(name="2. 기존 무더위쉼터")
    for row in shelters.to_crs("EPSG:4326").itertuples():
        name = escape(str(row.name))
        address = escape(str(getattr(row, "address", "")))
        shelter_type = escape(str(getattr(row, "shelter_type", "미분류")))
        weekend = "운영" if bool(getattr(row, "weekend_open", False)) else "미운영"
        night = "운영" if bool(getattr(row, "night_open", False)) else "미운영"
        details = (
            f"<b>{name}</b><br>{shelter_type}<br>{address}<br>"
            f"수용인원 {float(row.capacity):,.0f}명<br>주말 {weekend} · 야간 {night}"
        )
        folium.CircleMarker(
            location=[row.latitude, row.longitude],
            radius=4,
            color="#075985",
            fill=True,
            fill_opacity=0.9,
            tooltip=f"{name} · 수용인원 {float(row.capacity):,.0f}명",
            popup=folium.Popup(details, max_width=320),
        ).add_to(marker_group)
    marker_group.add_to(fmap)
    folium.GeoJson(
        _coverage_geojson(shelters, radius_m),
        name="3. 기존 접근권역",
        style_function=lambda _: {
            "color": "#38BDF8", "weight": 1, "fillColor": "#7DD3FC", "fillOpacity": 0.12
        },
    ).add_to(fmap)
    if not blindspots.empty:
        folium.GeoJson(
            blindspots.to_crs("EPSG:4326"),
            name="4. 고위험 사각지대",
            style_function=lambda _: {
                "color": "#991B1B", "weight": 1, "fillColor": "#EF4444", "fillOpacity": 0.6
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["cell_id", "adm_name", "estimated_elderly", "priority_score", "nearest_shelter_distance"],
                aliases=["셀", "행정동", "추정 고령인구", "정책 우선순위", "최근접 쉼터(m)"],
                localize=True,
            ),
        ).add_to(fmap)
    if selected_candidates is not None and not selected_candidates.empty:
        group = folium.FeatureGroup(name="5. AI 추천 후보", show=True)
        for rank, row in enumerate(selected_candidates.to_crs("EPSG:4326").itertuples(), 1):
            folium.Marker(
                [row.latitude, row.longitude],
                tooltip=f"추천 {rank}: {row.name}",
                popup=(
                    f"{row.name}<br>비용 {float(row.cost):,.0f}원<br>"
                    f"신규 보호 추정 {float(row.incremental_covered_elderly):,.0f}명"
                ),
                icon=folium.Icon(color="red", icon="plus", prefix="fa"),
            ).add_to(group)
        group.add_to(fmap)
    if after_shelters is not None and len(after_shelters) > len(shelters):
        folium.GeoJson(
            _coverage_geojson(after_shelters, radius_m),
            name="6. 추천 적용 후 접근권역",
            style_function=lambda _: {
                "color": "#16A34A", "weight": 2, "fillColor": "#4ADE80", "fillOpacity": 0.12
            },
        ).add_to(fmap)
    folium.LayerControl(collapsed=False).add_to(fmap)
    return fmap
