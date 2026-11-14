"""Cycling routes on small hand-made networks. Run: .venv/bin/python -m pytest backend/tests -q"""
import pytest

from backend.routing import Network, bike_access, bike_both_ways
from backend.tests.test_routing import ll, seg


def net_of(*features):
    return Network(list(features), {"as_of": "2026-11-14"})


def at(net, x, y, mode="bike"):
    lon, lat = ll(x, y)
    return net.snap(lat, lon, mode=mode)


@pytest.mark.parametrize(
    "tags, expected",
    [
        ({"hw": "residential"}, "ride"),
        ({"hw": "cycleway"}, "ride"),
        ({"hw": "footway"}, None),                                   # a pavement: bikes need an explicit sign
        ({"hw": "footway", "bicycle": "designated"}, "ride"),        # bike lane painted on the pavement
        ({"hw": "pedestrian", "bicycle": "yes"}, "ride"),
        ({"hw": "path"}, "ride"),
        ({"hw": "path", "bicycle": "no"}, None),
        ({"hw": "steps"}, None),
        ({"hw": "secondary", "bicycle": "use_sidepath"}, None),      # the cycle track next to it must be used
        ({"hw": "footway", "bicycle": "dismount"}, "push"),
        ({"hw": "residential", "access": "no"}, None),
    ],
)
def test_bike_access(tags, expected):
    assert bike_access(tags) == expected


def test_one_way_rules():
    assert bike_both_ways({"oneway": "False"})
    assert not bike_both_ways({"oneway": "True"})
    assert bike_both_ways({"oneway": "True", "oneway:bicycle": "no"})
    assert bike_both_ways({"oneway": "True", "cycleway:left": "opposite_lane"})


def test_bike_respects_one_way_streets_and_walking_does_not():
    # 1 -> 2 is one way (200 m); the way back goes round through 3 (2 x 158 m)
    net = net_of(seg("oneway", 1, 2, [(0, 0), (200, 0)], "lit_confirmed", "Strada Unică", oneway="True"),
                 seg("back1", 2, 3, [(200, 0), (100, 120)], "lit_confirmed", "Ocol"),
                 seg("back2", 3, 1, [(100, 120), (0, 0)], "lit_confirmed", "Ocol"))
    there = net.plan(at(net, 0, 0), at(net, 200, 0), mode="bike")["routes"]["fastest"]
    back = net.plan(at(net, 200, 0), at(net, 0, 0), mode="bike")["routes"]["fastest"]
    walk = net.plan(at(net, 200, 0, "walk"), at(net, 0, 0, "walk"), mode="walk")["routes"]["fastest"]
    assert there["length_m"] == pytest.approx(200, abs=0.5)
    assert back["length_m"] == pytest.approx(312.4, abs=1) and back["streets"] == ["Ocol"]
    assert walk["length_m"] == pytest.approx(200, abs=0.5)


def test_bike_avoids_a_pavement_without_a_bike_sign_and_rides_faster():
    net = net_of(seg("pavement", 1, 2, [(0, 0), (100, 0)], "lit_confirmed", "Trotuar", hw="footway"),
                 seg("s1", 1, 3, [(0, 0), (0, 80)], "lit_confirmed", "Strada Nord"),
                 seg("s2", 3, 4, [(0, 80), (100, 80)], "lit_confirmed", "Strada Nord"),
                 seg("s3", 4, 2, [(100, 80), (100, 0)], "lit_confirmed", "Strada Nord"))
    bike = net.plan(at(net, 0, 0), at(net, 100, 0), mode="bike")["routes"]["fastest"]
    walk = net.plan(at(net, 0, 0, "walk"), at(net, 100, 0, "walk"), mode="walk")["routes"]["fastest"]
    assert bike["length_m"] == pytest.approx(260, abs=0.5) and walk["length_m"] == pytest.approx(100, abs=0.5)
    assert bike["minutes"] == pytest.approx(260 / 4.2 / 60, abs=0.1)


def test_pushing_the_bike_counts_at_walking_speed():
    net = net_of(seg("push", 1, 2, [(0, 0), (100, 0)], "lit_confirmed", "Pasaj", hw="footway", bicycle="dismount"))
    route = net.plan(at(net, 0, 0), at(net, 100, 0), mode="bike")["routes"]["fastest"]
    assert route["minutes"] == pytest.approx(100 / 1.35 / 60, abs=0.1)


def test_steps_are_not_for_bikes():
    net = net_of(seg("steps", 1, 2, [(0, 0), (60, 0)], "lit_confirmed", "Scări", hw="steps"),
                 seg("road", 3, 4, [(0, 500), (60, 500)], "lit_confirmed", "Strada"))
    lon, lat = ll(30, 0)
    snap = net.snap(lat, lon, max_m=1000, mode="bike")              # the steps are not offered to a cyclist
    assert net.props[snap.seg]["id"] == "road" and snap.d > 400
