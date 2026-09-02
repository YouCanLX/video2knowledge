import asyncio
import sys

import pytest

from video2knowledge.mlx_service import MlxAudioServiceManager


async def _unreachable() -> bool:
    return False


def test_mlx_service_rejects_missing_executable(tmp_path, monkeypatch):
    manager = MlxAudioServiceManager(
        "definitely-missing-v2k-executable",
        "http://127.0.0.1:8000",
        tmp_path / "mlx.log",
    )
    monkeypatch.setattr(manager, "_is_reachable", _unreachable)

    with pytest.raises(FileNotFoundError, match="executable was not found"):
        asyncio.run(manager.start())


def test_mlx_service_starts_and_stops_managed_process(tmp_path, monkeypatch):
    command = f'{sys.executable} -c "import time; time.sleep(30)"'
    manager = MlxAudioServiceManager(
        command,
        "http://127.0.0.1:8000",
        tmp_path / "mlx.log",
    )
    monkeypatch.setattr(manager, "_is_reachable", _unreachable)

    async def scenario():
        try:
            started = await manager.start()
            assert started.state == "starting"
            assert started.managed is True
            assert started.pid is not None
        finally:
            stopped = await manager.stop()
        assert stopped.state == "stopped"
        assert stopped.managed is False

    asyncio.run(scenario())
