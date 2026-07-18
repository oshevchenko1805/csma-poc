"""Unit tests for run_batch.py loss-passthrough CLI args."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import run_batch  # noqa: E402


def test_loss_args_default_none():
    a = run_batch.parse_args([])
    assert a.mesh_loss_prob is None
    assert a.mesh_loss_seed is None


def test_loss_args_parsed():
    a = run_batch.parse_args(["--mesh-loss-prob", "0.25", "--mesh-loss-seed", "7"])
    assert a.mesh_loss_prob == 0.25
    assert a.mesh_loss_seed == 7
