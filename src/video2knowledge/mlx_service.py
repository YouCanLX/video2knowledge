from __future__ import annotations

import asyncio
import shlex
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx


@dataclass(frozen=True, slots=True)
class MlxServiceStatus:
    state: str
    reachable: bool
    managed: bool
    pid: int | None
    command: str
    base_url: str
    message: str
    log_tail: str

    def to_dict(self) -> dict[str, str | bool | int | None]:
        return asdict(self)


class MlxAudioServiceManager:
    """Manage one MLX Audio process started by this application instance."""

    def __init__(self, command: str, base_url: str, log_path: Path):
        self.command = command.strip()
        self.base_url = base_url.rstrip("/")
        self.log_path = log_path
        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()

    @property
    def is_managed_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    def configure(self, command: str, base_url: str) -> None:
        self.command = command.strip()
        self.base_url = base_url.rstrip("/")

    async def start(self) -> MlxServiceStatus:
        async with self._lock:
            current = await self.status()
            if current.reachable or self.is_managed_running:
                return current
            arguments = shlex.split(self.command)
            if not arguments:
                raise ValueError("MLX Audio command cannot be empty")
            executable = shutil.which(arguments[0])
            if not executable:
                raise FileNotFoundError(f"MLX Audio executable was not found: {arguments[0]}")
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("ab") as log:
                self._process = await asyncio.create_subprocess_exec(
                    executable,
                    *arguments[1:],
                    stdout=log,
                    stderr=asyncio.subprocess.STDOUT,
                    cwd=self.log_path.parent,
                )
            await asyncio.sleep(0.5)
            return await self.status()

    async def stop(self) -> MlxServiceStatus:
        async with self._lock:
            if self.is_managed_running:
                assert self._process is not None
                self._process.terminate()
                try:
                    await asyncio.wait_for(self._process.wait(), timeout=10)
                except TimeoutError:
                    self._process.kill()
                    await self._process.wait()
            self._process = None
            return await self.status()

    async def shutdown(self) -> None:
        if self.is_managed_running:
            await self.stop()

    async def status(self) -> MlxServiceStatus:
        reachable = await self._is_reachable()
        process = self._process
        managed = process is not None
        pid = process.pid if process and process.returncode is None else None
        if reachable:
            state = "running"
            message = "MLX Audio is reachable"
        elif process and process.returncode is None:
            state = "starting"
            message = "MLX Audio is starting; model loading may take several minutes"
        elif process and process.returncode is not None:
            state = "failed"
            message = f"MLX Audio exited with status {process.returncode}"
        else:
            state = "stopped"
            message = "MLX Audio is not reachable"
        return MlxServiceStatus(
            state=state,
            reachable=reachable,
            managed=managed,
            pid=pid,
            command=self.command,
            base_url=self.base_url,
            message=message,
            log_tail=self._read_log_tail(),
        )

    async def _is_reachable(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=1) as client:
                await client.get(f"{self.base_url}/v1/models")
        except httpx.RequestError:
            return False
        return True

    def _read_log_tail(self, max_bytes: int = 8_000) -> str:
        if not self.log_path.exists():
            return ""
        with self.log_path.open("rb") as handle:
            handle.seek(0, 2)
            handle.seek(max(0, handle.tell() - max_bytes))
            return handle.read().decode(errors="replace").strip()
