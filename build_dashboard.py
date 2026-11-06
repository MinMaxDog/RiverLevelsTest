from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


BASE_URL = "https://environment.data.gov.uk/flood-monitoring"

# Explicitly ordered upstream to downstream.
STATIONS = {
    "0009": "Richmond",
    "0006": "Westminster",
    "0007": "Tower Pier",
    "0003": "Charlton",
    "0001": "Silvertown",
    "0020": "Tilbury",
}

# Retry temporary connection and server failures.
session = requests.Session()
retries = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
)
session.mount("https://", HTTPAdapter(max_retries=retries))

run_time = pd.Timestamp.now(tz="UTC")
since = (run_time - pd.Timedelta(days=2)).strftime(
    "%Y-%m-%dT%H:%M:%SZ"
)

rows = []

for station_id, station_name in STATIONS.items():
    print(f"Fetching {station_name}...")

    measure_id = (
        f"{station_id}-level-tidal_level-i-15_min-mAOD"
    )

    response = session.get(
        f"{BASE_URL}/id/measures/{measure_id}/readings",
        params={
            "since": since,
            "_limit": 1000,
        },
        timeout=30,
    )
    response.raise_for_status()

    for reading in response.json()["items"]:
        rows.append(
            {
                "station": station_name,
                "timestamp": reading.get("dateTime"),
                "level_mAOD": reading.get("value"),
            }
        )

if not rows:
    raise RuntimeError("The API returned no recent readings.")

df = pd.DataFrame(rows)

# Parse timestamps and remove missing or non-numeric levels.
df["timestamp"] = pd.to_datetime(
    df["timestamp"], utc=True, errors="coerce"
)
df["level_mAOD"] = pd.to_numeric(
    df["level_mAOD"], errors="coerce"
)
df = df.dropna(subset=["timestamp", "level_mAOD"])

df = df.drop_duplicates(
    subset=["station", "timestamp"],
    keep="last",
)

# One row per observation time; one column per station.
levels = df.pivot(
    index="timestamp",
    columns="station",
    values="level_mAOD",
)

levels = levels.reindex(columns=list(STATIONS.values()))
levels = levels.sort_index()

# Only compare timestamps with readings at all six stations.
shared_levels = levels.dropna(how="any")
last_four = shared_levels.tail(4)

if len(last_four) < 4:
    raise RuntimeError(
        "Fewer than four shared observation times were found "
        "across the six stations in the last two days."
    )

print("\nSelected readings:")
print(last_four.to_string())

gaps = last_four.index.to_series().diff().dropna()
if not gaps.eq(pd.Timedelta(minutes=15)).all():
    print(
        "\nNote: the selected shared readings are not all "
        "15 minutes apart. The legend shows their actual times."
    )

latest_time = last_four.index[-1]
age_minutes = (run_time - latest_time).total_seconds() / 60

# Colours run from oldest to newest.
colours = ["#0072B2", "#E69F00", "#009E73", "#CC79A7"]

fig = go.Figure()

for position, (timestamp, values) in enumerate(
    last_four.iterrows()
):
    newest = position == len(last_four) - 1

    fig.add_trace(
        go.Scatter(
            x=list(STATIONS.values()),
            y=values.to_list(),
            mode="lines+markers+text",
            name=timestamp.strftime("%d %b %H:%M UTC"),
            line={
                "color": colours[position],
                "width": 4 if newest else 2,
            },
            marker={"size": 10 if newest else 7},
            text=[f"{value:.2f}" for value in values],
            textposition=(
                "top center" if position % 2 else "bottom center"
            ),
            textfont={"color": colours[position], "size": 11},
            cliponaxis=False,
            hovertemplate=(
                "%{x}<br>"
                "Level: %{y:.3f} mAOD"
                "<extra>%{fullData.name}</extra>"
            ),
        )
    )

status = (
    f"Newest plotted reading: "
    f"{latest_time.strftime('%d %b %Y %H:%M UTC')} "
    f"({age_minutes:.0f} minutes old at build time)"
)

fig.update_layout(
    title={
        "text": (
            "Thames water levels"
            f"<br><sup>{status}</sup>"
        )
    },
    template="plotly_white",
    xaxis_title="Stations — upstream to downstream",
    yaxis_title="Water level (metres above Ordnance Datum)",
    legend_title_text="Observation time",
    hovermode="closest",
    height=650,
    margin={"t": 110, "b": 150, "l": 80, "r": 40},
    annotations=[
        {
            "text": (
                "Stations are equally spaced schematically; "
                "levels are elevations, not water depths."
                "<br>"
                "This uses Environment Agency flood and river "
                "level data from the real-time data API (Beta)."
                "<br>"
                f"Dashboard built: "
                f"{run_time.strftime('%d %b %Y %H:%M UTC')}"
            ),
            "xref": "paper",
            "yref": "paper",
            "x": 0,
            "y": -0.22,
            "showarrow": False,
            "align": "left",
            "font": {"size": 11},
        }
    ],
)

# Keep the downloaded observations for inspection.
df.sort_values(["timestamp", "station"]).to_csv(
    "recent_readings.csv", index=False
)

# Embed Plotly so the HTML can be opened without a CDN connection.
output_path = Path("index.html").resolve()

fig.write_html(
    str(output_path),
    include_plotlyjs=True,
    full_html=True,
    config={
        "responsive": True,
        "displaylogo": False,
    },
)

print(f"\nDashboard saved to: {output_path}")