"""Boundary variants as [south, west, north, east] (EPSG:4326). Edges derived in t1_geom.py / t1_edges.py."""
VARIANTS = {
    # W: ~40 m west of Bd. Mihai Viteazu (westmost 21.22529); S: just south of Strada Cluj's south end (45.74365)
    # and Bd. Dr. Victor Babes (45.74440); E: ~60 m east of Aleea F.C. Ripensia / dormitory cluster (21.2432 / 21.2430);
    # N: Bega centreline max latitude west of lon 21.2355 (45.75060) + ~65 m.
    "compact": (45.7432, 21.2248, 45.7512, 21.2440),
    # W: Bd. 16 Decembrie 1989 at the south edge latitude (lon 21.2109) minus ~45 m; S: Piata Nicolae Balcescu /
    # Strada 1 Decembrie 1918 / Calea Martirilor north end (45.7407..45.7415) minus a few metres; N and E as compact.
    "extended": (45.7405, 21.2103, 45.7512, 21.2440),
    # bbox of the city zone polygon "Complex Studentesc" (cont.primariatm.ro/api/zones)
    "zone": (45.74441, 21.22535, 45.75447, 21.24678),
}
