"""run_batch cleanup must reap leaked mavsdk_server gRPC subprocesses."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
import run_batch  # noqa: E402


def test_cleanup_cmd_kills_mavsdk_server():
    assert "mavsdk_server" in run_batch.CLEANUP_CMD


def test_cleanup_cmd_still_kills_px4_and_gz():
    assert "px4" in run_batch.CLEANUP_CMD
    assert "gz" in run_batch.CLEANUP_CMD
