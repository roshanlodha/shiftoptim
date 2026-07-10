"""Rainbow palette for PGY-4 residents — 15 evenly spaced hues with white text
for contrast on the calendar cells and legend chips."""

N_RESIDENTS = 15


def _rainbow_style(index):
    hue = int((index / N_RESIDENTS) * 360)
    return {"bg": f"hsl({hue}, 72%, 42%)", "color": "#ffffff"}


def color_map_for_residents(conn, pgy_level=4):
    """Returns last_name -> {bg, color} style dict."""
    rows = conn.execute(
        "SELECT id, last_name FROM residents WHERE pgy_level = ? ORDER BY id",
        (pgy_level,),
    ).fetchall()
    return {row["last_name"]: _rainbow_style(i) for i, row in enumerate(rows)}
