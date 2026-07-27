"""run_batch exposes a post-launch settle knob (fix for high-loss spoof drop)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import run_batch  # noqa: E402


def test_post_launch_settle_default():
    a = run_batch.parse_args([])
    assert a.post_launch_settle == 20.0


def test_post_launch_settle_override():
    a = run_batch.parse_args(["--post-launch-settle", "30"])
    assert a.post_launch_settle == 30.0
