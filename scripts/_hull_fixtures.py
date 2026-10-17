"""Plain location fixtures shared by hull smoke scripts; no storage imports."""


def stepped_house():
    """A two-storey rectangle with a setback and four contour openings."""
    return {
        "id": "hull-demo",
        "map3d": {
            "outline": [[0, 0], [10, 0], [10, 8], [0, 8]],
            "level_outlines": {"1": [[0, 0], [6, 0], [6, 8], [0, 8]]},
            "storey_height_m": 3.0,
            "boundary": [[0, 0], [10, 0], [10, 8], [0, 8]],
        },
        "rooms": [
            {"id": "a", "layout": {"x": 0, "y": 0, "w": 10, "d": 8,
                "level": 0, "openings": [
                    {"edge": 0, "at": 0.5, "width_m": 1.2,
                     "height_m": 1.2, "sill_m": 0.9, "type": "window"},
                    {"edge": 2, "at": 0.3, "width_m": 1.0,
                     "height_m": 2.1, "type": "door", "to": "outside"}]}},
            {"id": "b", "layout": {"x": 0, "y": 0, "w": 6, "d": 8,
                "level": 1, "openings": [
                    {"edge": 1, "at": 0.5, "width_m": 1.2,
                     "height_m": 1.2, "sill_m": 0.9, "type": "window"},
                    {"edge": 3, "at": 0.5, "width_m": 1.0,
                     "height_m": 2.4, "type": "passage", "to": "outside"}]}},
        ],
    }


def without_outline():
    """Rooms alone must never synthesize a building contour."""
    loc = stepped_house()
    loc["map3d"].pop("outline")
    loc["map3d"].pop("level_outlines")
    return loc
