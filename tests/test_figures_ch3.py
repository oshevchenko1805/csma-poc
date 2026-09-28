"""metrics.figures_ch3 — structure of Fig. 3.1 (data-dependency graph)."""
import os

from metrics import figures_ch3 as F


def test_every_edge_connects_known_nodes():
    ids = F.all_ids()
    for src, dst, style in F.EDGES:
        assert src in ids and dst in ids, (src, dst)
        assert style in ("solid", "weak")


def test_taint_states_match_table_3_8():
    # the spoof falsifies the GNSS position and everything computed from it
    for n in ("gnss_pos", "ekf_pos", "ann", "innov"):
        assert F.state_of(n) == F.TAINTED, n
    # clean only under the adversary model (position-only spoof)
    assert F.state_of("ekf_vel") == F.CONDITIONAL
    # independent of the victim
    for n in ("gnss_vel", "imu", "peer_pos", "range"):
        assert F.state_of(n) == F.CLEAN, n
    # actions inherit the state of the data they rely on
    assert F.state_of("loiter") == F.state_of("ekf_pos")
    assert F.state_of("zerovel") == F.state_of("ekf_vel")


def test_only_ranging_check_has_a_clean_side():
    assert F.detector_sides_clean("gps") == []
    assert F.detector_sides_clean("cc") == []
    assert set(F.detector_sides_clean("rng")) == {"peer_pos", "range"}


def test_figure_renders(tmp_path):
    F.fig_data_dependency(str(tmp_path))
    for ext in ("png", "pdf"):
        assert os.path.getsize(tmp_path / ("fig3_1_data_dependency." + ext)) > 0


def test_architecture_properties_match_table_3_5():
    assert F.properties_of("A") == (False, False, False)
    assert F.properties_of("B") == (True, False, False)
    assert F.properties_of("C") == (True, True, True)


def test_architectures_figure_renders(tmp_path):
    F.fig_architectures(str(tmp_path))
    for ext in ("png", "pdf"):
        assert os.path.getsize(tmp_path / ("fig3_2_architectures." + ext)) > 0


def test_deployment_ports_match_table_3_16():
    labels = {(s, d): lab for s, d, lab, _tw, _da in F.DEPLOY_EDGES}
    assert "14540+i" in labels[("px4", "router")]
    assert labels[("router", "mon")] == "14570+i"
    assert labels[("router", "mavsdk")] == "14560+i"
    assert labels[("atk", "guard")] == "14590+i"
    assert labels[("guard", "px4")] == "14580+i"
    assert "5550+i" in labels[("mon", "peers")]
    # the attacker and the ground-truth recorder are outside the system under test
    assert F.DEPLOY["atk"][5] == "atk" and F.DEPLOY["rec"][5] == "obs"


def test_deployment_figure_renders(tmp_path):
    F.fig_deployment(str(tmp_path))
    for ext in ("png", "pdf"):
        assert os.path.getsize(tmp_path / ("fig3_3_deployment." + ext)) > 0
