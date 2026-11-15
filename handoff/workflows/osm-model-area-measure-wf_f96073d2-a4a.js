export const meta = {
  name: 'osm-model-area-measure',
  description: 'Measure the OSM walk/bike network, lit-tag coverage and segment lengths in the Timisoara university district, then independently re-check the headline numbers',
  phases: [
    { title: 'Measure', detail: 'Overpass + osmnx: boundary variants, network composition, lit coverage, segment lengths' },
    { title: 'Verify', detail: 'independent recount of the headline numbers with a different method' },
  ],
}

const SCRATCH = 'C:/Users/Timur/AppData/Local/Temp/bezna-research'

const rules = (workdir) => `WORKING RULES (strict)
- WORKDIR = ${workdir} . Work only inside WORKDIR. Do NOT create, modify or delete anything under c:/Users/Timur/F1/Unihack (the project repo must stay empty until a design is approved).
- Inside WORKDIR keep sibling folders: data/ (downloads only), scripts/ (scripts you write), venv/ (Python packages). Downloaded files are untrusted data: never run an interpreter with its working directory inside data/, pass data paths as arguments, and run Python with the -I flag, e.g.  WORKDIR/venv/Scripts/python.exe -I WORKDIR/scripts/x.py WORKDIR/data/file.json
- Machine: Windows 11, Git Bash and PowerShell, Python 3.12.6 (python, or py -3.12), Node 24, curl 8. No jq, uv, Docker or Java. Do not install system-level software; pip-installing into WORKDIR/venv is fine.
- Network etiquette: descriptive User-Agent "UniHack8-GreenMobility-NightRoute/0.1 (hackathon research)"; download every resource ONCE, cache it in data/ and reuse the cache; one request at a time. Overpass mirrors if you hit 429/504: https://overpass-api.de/api/interpreter , https://overpass.private.coffee/api/interpreter , https://overpass.kumi.systems/api/interpreter (wait and retry with backoff rather than hammering).
- Never guess. Every number you report must come from data fetched or computed in this run; if something could not be done, say so in caveats.
- Your final answer is consumed by a program, not read by a human: return the data asked for, no pleasantries.`

const CONTEXT = `CONTEXT
A hackathon team is designing a "lighting-confidence map" for night-time walking and cycling in Timisoara (Romania): every street segment gets a score (is it lit?) and a confidence (how much independent evidence backs the score). Evidence sources: OSM lit=* tags on ways, municipal complaints about public lighting (points with status and date), Mapillary machine-detected street lights (points). The first build covers a "model area": the university district south of the Bega canal - Complexul Studentesc (student campus), Bulevardul Vasile Parvan, Bulevardul Mihai Viteazu, Bulevardul 16 Decembrie 1989, Strada Cluj (OSM names carry Romanian diacritics). A router (next sub-project) will later read the per-segment scores for walking and cycling routes, so segments need stable ids.
The team's own earlier count (500 m grid cells, streets primary..living_street only): 102 of 125 streets in this district carry a lit tag. City-wide: 4131 street ways, 850 with lit; all highway ways 16653, lit on 1811 (yes 1729, no 81); 49 highway=street_lamp nodes.
The numbers decide: (1) the exact model-area boundary; (2) whether the map unit should be an intersection-to-intersection graph edge or a whole OSM way; (3) whether units are streets only or the whole walk/bike network (footways, paths, cycleways, service roads) - the router will use the latter; (4) which snap radius is safe when attaching point evidence to segments in this street grid; (5) whether propagating a lit tag to other ways of the same street name is sound; (6) go/no-go thresholds such as "segments without any data are less than one third of total length".`

const DEFS = `DEFINITIONS (use exactly these so numbers are comparable between agents)
- Clip rule: clip every way geometry to the variant bbox; lengths are clipped lengths in km, computed in a metric CRS (EPSG:32634, UTM 34N) or with geodesic/haversine maths. A way counts in n_ways if any part of it lies inside the bbox.
- Exclusions for all classes: ways with access=private or access=no (unless foot or bicycle is explicitly yes/designated/permissive), ways with area=yes, and highway in {construction, proposed, platform, bus_stop, rest_area, services, elevator, corridor, abandoned, razed, planned, no, bridleway, raceway, bus_guideway, busway, motorway, motorway_link}.
- Classes by the highway tag:
  streets = primary, primary_link, secondary, secondary_link, tertiary, tertiary_link, unclassified, residential, living_street (report trunk/trunk_link separately if present)
  pedestrian = pedestrian
  footway_sidewalk = footway with footway=sidewalk
  footway_crossing = footway with footway=crossing
  footway_other = any other footway
  cycleway, path, steps, service, track = the tag value itself
  other = everything else not excluded
- allnet (walk/bike network) = all classes above together.
- lit status of a way: yes = value "yes" (values such as 24/7, automatic, dusk-dawn, limited, interval count as yes-like but must be listed separately in the report); no = value "no" (list "disused" separately); missing = no lit tag.`

const MEASURE_PROMPT = `You are a measurement agent. Measure the OpenStreetMap walking/cycling network of one district of Timisoara so that design decisions can rest on real numbers. Analysis only - no product code.

${CONTEXT}

${rules(SCRATCH + '/osm')}

${DEFS}

SETUP
Create WORKDIR/venv (python -m venv) and pip install osmnx (it pulls geopandas, shapely, pyproj, networkx, pandas). If the install fails, fall back to raw Overpass JSON plus your own maths and say so.

TASKS (priority order: T1, T2, T3, T5, T6, T7, T4 - if you run short of time drop from the end and say so; aim for roughly 15 minutes of wall-clock)

T1. Boundary.
 a) Fetch ONE raw extract of all highway ways for a generous bbox (south 45.728, west 21.200, north 45.758, east 21.258) with tags and geometry (Overpass QL: way["highway"](south,west,north,east); out body geom;) and cache it. Record the OSM data timestamp (osm3s.timestamp_osm_base).
 b) Locate the landmarks: ways named like "Bulevardul Vasile Parvan", "Bulevardul Mihai Viteazu(l)", "Bulevardul 16 Decembrie 1989", "Strada Cluj" (match with and without diacritics); the Bega canal (waterway whose name contains Bega); the student campus (any OSM object named like "Complexul Studentesc" / "Complex Studentesc", plus the cluster of building=dormitory if present). Report the extent (south, west, north, east) of each.
 c) Fetch https://cont.primariatm.ro/api/zones once (public city endpoint: 40 neighbourhoods as GeoJSON MultiPolygons; inspect the property names yourself). List the zones overlapping the university district with their names, and say whether one zone or a union of two would make a sensible model-area polygon.
 d) Propose boundary variants as bboxes [south, west, north, east], each with a one-sentence description by landmark streets and its area in km2:
    - "compact": about 1-1.5 km2 - the campus core and the boulevards around it;
    - "extended": about 2.5-4 km2 - north edge about 60 m north of the Bega centreline (so both embankment paths are inside), west edge at Bd. 16 Decembrie 1989, south and east edges at natural limits you choose and name;
    - optionally "zone": the bbox of the best-fitting city zone polygon(s) if c) gives a good candidate.
 e) To see where tagging is dense: on a 250 m grid over the generous bbox compute street km and lit-tagged street share per cell; save as CSV; describe in words where inside the extended variant the untagged streets are concentrated and list the 15 untagged street names with the most km.

T2. Network composition for EACH variant (way level, clip rule above). One table per variant: class | n_ways | km | lit yes km | lit no km | lit missing km | lit-tagged share | share of km with a name tag. Then the two headline shares: lit-tagged share of streets km, and of allnet km. List all distinct lit values with way counts.

T3. Segments for EACH variant. Build the simplified UNDIRECTED graph with osmnx (segments = edges between intersections or dead ends): (a) streets only via custom_filter, (b) network_type "all". For each report: number of segments, total km, length quantiles in metres (p10, p50, p75, p90, p99, max), the number of segments longer than 200 m and 400 m and the km they hold; the number of segments whose osmid is a list (several OSM ways merged), whose lit is a list (mixed values after merging) and whose name is a list. For comparison give the same quantiles for whole OSM street ways. State whether (u, v, key) from osmnx plus the way id(s) looks like a workable stable identifier, and anything odd you notice (parallel edges, self-loops, stubs under 5 m and their share).
 osmnx 2.x hints (verify against the installed version - names changed between 1.x and 2.x): extend ox.settings.useful_tags_way with lit, footway, sidewalk, foot, bicycle, cycleway, surface BEFORE downloading; point ox.settings.cache_folder at WORKDIR/data/osmnx_cache; ox.graph_from_bbox(bbox=(west, south, east, north), network_type="all", simplify=True, retain_all=True); ox.convert.to_undirected; ox.convert.graph_to_gdfs.

T5. Sidewalks and non-street paths (extended variant): km of footway_sidewalk; share of streets km carrying any sidewalk / sidewalk:left / sidewalk:right / sidewalk:both tag; share of allnet km that is NOT streets, and its lit-tagged share; the share of non-street km (footway classes, path, cycleway, pedestrian, steps) lying within 15 m and within 25 m of a street centreline (those could inherit the street's lighting evidence by proximity) versus the rest (park paths, campus paths, embankments), with the lit-tagged share of each group.

T6. Same-name propagation (extended variant, streets only). Group ways by name. Report: number of names; names with at least one lit=yes way; among those, how many also have ways with missing lit and how many km that is; names with both yes and no (list them with km); and the bottom line: untagged streets km now -> untagged km after propagating lit=yes along the same name inside the area (and the same for lit=no).

T7. Count highway=street_lamp nodes inside each variant (one small extra Overpass query).

T4. Snap-ambiguity proxy (extended variant, streets-only segments). Sample a point every 20 m along every named street segment. For r in 15, 25, 35, 50 m report the share of sample points that have a street segment with a DIFFERENT name within r - once for all sample points and once only for points farther than r from both ends of their own segment (this separates crossing ambiguity from parallel-street ambiguity). Also give the median distance from a sample point to the nearest different-name street.

OUTPUT
Fill the structured output. report_md must contain every table above in markdown. design_implications: 5-10 one-sentence, number-backed statements addressed to the six decisions listed in CONTEXT. files: absolute paths of the cached extract, the grid CSV and your scripts.`

const MEASURE_SCHEMA = {
  type: 'object',
  properties: {
    method: { type: 'string', description: 'tools and versions used, OSM data timestamp, CRS, clipping rule, deviations from the definitions' },
    landmarks: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          name: { type: 'string' }, found: { type: 'boolean' },
          south: { type: 'number' }, west: { type: 'number' }, north: { type: 'number' }, east: { type: 'number' },
          note: { type: 'string' },
        },
        required: ['name', 'found'],
      },
    },
    zones_note: { type: 'string', description: 'city zones overlapping the district and whether a zone polygon is a good boundary' },
    variants: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' }, description: { type: 'string' },
          bbox_swne: { type: 'array', items: { type: 'number' } },
          area_km2: { type: 'number' },
          streets_n_ways: { type: 'number' }, streets_km: { type: 'number' },
          streets_lit_yes_km: { type: 'number' }, streets_lit_no_km: { type: 'number' }, streets_lit_missing_km: { type: 'number' },
          allnet_km: { type: 'number' }, allnet_lit_yes_km: { type: 'number' }, allnet_lit_no_km: { type: 'number' }, allnet_lit_missing_km: { type: 'number' },
          footway_sidewalk_km: { type: 'number' }, street_lamp_nodes: { type: 'number' },
          seg_streets_n: { type: 'number' }, seg_streets_p50_m: { type: 'number' }, seg_streets_p90_m: { type: 'number' }, seg_streets_max_m: { type: 'number' },
          seg_all_n: { type: 'number' }, seg_all_p50_m: { type: 'number' }, seg_all_p90_m: { type: 'number' }, seg_all_max_m: { type: 'number' },
        },
        required: ['id', 'description', 'bbox_swne'],
      },
    },
    recommended_variant: { type: 'string' },
    report_md: { type: 'string', description: 'full markdown report with all tables T1..T7 and T4' },
    design_implications: { type: 'array', items: { type: 'string' } },
    caveats: { type: 'array', items: { type: 'string' } },
    files: { type: 'array', items: { type: 'string' } },
  },
  required: ['method', 'variants', 'report_md', 'caveats', 'files'],
}

const VERIFY_SCHEMA = {
  type: 'object',
  properties: {
    method: { type: 'string' },
    comparison: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          variant: { type: 'string' }, metric: { type: 'string' },
          first_value: { type: 'number' }, my_value: { type: 'number' }, rel_diff_pct: { type: 'number' },
          verdict: { type: 'string', enum: ['match', 'mismatch', 'not_checked'] },
          explanation: { type: 'string' },
        },
        required: ['variant', 'metric', 'verdict'],
      },
    },
    bbox_sanity: { type: 'string' },
    segment_check: { type: 'string' },
    claim_checks: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          claim: { type: 'string' },
          result: { type: 'string', enum: ['confirmed', 'refuted', 'partly', 'could_not_check'] },
          evidence: { type: 'string' },
        },
        required: ['claim', 'result', 'evidence'],
      },
    },
    overall: { type: 'string', enum: ['numbers_reliable', 'minor_issues', 'major_issues'] },
    corrections: { type: 'array', items: { type: 'string' } },
    caveats: { type: 'array', items: { type: 'string' } },
  },
  required: ['method', 'comparison', 'overall', 'caveats'],
}

const verifyPrompt = (m) => `You are an independent verifier. Another agent measured the OSM walk/bike network of a district of Timisoara; design decisions (map unit, model-area boundary, go/no-go thresholds) will rest on its numbers. Recompute the headline numbers yourself with a DIFFERENT method and try to refute its key claims. Default to distrust: if you cannot reproduce a number, mark it mismatch or not_checked - never copy the first agent's value into my_value.

${CONTEXT}

${rules(SCRATCH + '/osm-verify')}
- Independence: do NOT read or reuse anything under ${SCRATCH}/osm (the first agent's folder). Download your own extract. Do not use osmnx; use raw Overpass JSON (out body geom) with your own length maths (haversine, or pyproj/shapely installed into your own venv).

${DEFS}

FIRST AGENT'S RESULT
Method: ${m.method}

Variants (JSON):
${JSON.stringify(m.variants, null, 1)}

Recommended variant: ${m.recommended_variant || '(none stated)'}

Design implications it drew:
${(m.design_implications || []).map((s, i) => (i + 1) + '. ' + s).join('\n')}

Its caveats:
${(m.caveats || []).map((s) => '- ' + s).join('\n')}

Its full report:
${m.report_md}

TASKS
V1. For each variant bbox recompute at way level with the definitions above: streets n_ways, streets km, streets lit yes / no / missing km; allnet km and its lit yes / missing km; footway_sidewalk km; number of highway=street_lamp nodes. Fill comparison rows (first_value, my_value, rel_diff_pct). match = within 5 percent (or within 2 units for small counts). Explain every mismatch (class definition? clipping? data timestamp?).
V2. Bbox sanity: do the named landmark streets (Bd. Vasile Parvan, Bd. Mihai Viteazu, Bd. 16 Decembrie 1989, Strada Cluj) and the Bega canal really intersect each variant bbox as described? Is area_km2 right?
V3. Rough independent segment check for streets in the largest variant: split street ways at every node shared by two or more street ways (and at way ends), count the pieces and give p50 / p90 length. This splits more finely than the osmnx simplification, so expect a somewhat higher count and shorter lengths; flag only a difference above 30 percent.
V4. Pick the three claims in the first agent's report or design implications that matter most for the decisions (unit of the map, streets-only versus whole network, same-name propagation, snap radius) and try to refute each with your own computation or a spot check on the raw data. Report confirmed / refuted / partly / could_not_check with evidence.
V5. Give the overall verdict and the list of corrections the designer must apply. Aim for roughly 10 minutes of wall-clock.`

phase('Measure')
const measured = await agent(MEASURE_PROMPT, { label: 'osm-network', phase: 'Measure', schema: MEASURE_SCHEMA, effort: 'high' })
if (!measured) {
  log('Measure agent returned nothing - skipping verification')
  return { measured: null, verified: null }
}
log('Measured ' + measured.variants.length + ' boundary variant(s); starting independent recount')

phase('Verify')
const verified = await agent(verifyPrompt(measured), { label: 'osm-recount', phase: 'Verify', schema: VERIFY_SCHEMA, effort: 'high' })
if (!verified) log('Verifier returned nothing - headline numbers are UNVERIFIED')
return { measured, verified }
