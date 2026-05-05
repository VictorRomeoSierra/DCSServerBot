import aiofiles
import aiohttp
import asyncio
import os
import re

from core import Extension, Server, Status, ServiceRegistry, get_translation
from services.bot import BotService
from services.servicebus import ServiceBus
from typing_extensions import override

_ = get_translation(__name__.split('.')[1])

ACMI_PATTERN_MATCH = r'Successfully saved \[(?P<filename>.*?\.acmi)\]'

__all__ = ["TacviewLink"]


class TacviewLink(Extension):
    CONFIG_DICT = {
        "target": {
            "type": str,
            "label": _("Discord Channel"),
            "placeholder": "<id:1234567890>",
            "required": True,
        },
        "base_url": {
            "type": str,
            "label": _("Lardoon URL"),
            "placeholder": "https://tacview.example.com",
        },
        "poll_timeout": {
            "type": int,
            "label": _("Index poll timeout (s)"),
            "default": 600,
        },
        "poll_interval": {
            "type": int,
            "label": _("Index poll interval (s)"),
            "default": 30,
        },
    }

    def __init__(self, server: Server, config: dict):
        super().__init__(server, config)
        self.bus = ServiceRegistry.get(ServiceBus)
        self.exp = re.compile(ACMI_PATTERN_MATCH)
        self.log_pos = -1
        self.stop_event = asyncio.Event()
        self.stopped = asyncio.Event()

    @override
    async def startup(self, *, quiet: bool = False) -> bool:
        if not self._get_base_url():
            self.log.error(
                f"{self.name}: no base_url configured and no sibling Lardoon `url` to fall back to; "
                f"cannot post links."
            )
            return False
        if not self.config.get('target'):
            self.log.error(f"{self.name}: no `target` channel configured.")
            return False
        if 'Tacview' not in self.server.extensions:
            self.log.warning(
                f"{self.name}: Tacview extension is not enabled — no ACMI files will be produced "
                f"and no links will ever be posted."
            )
        self.stop_event.clear()
        self.stopped.clear()
        asyncio.create_task(self.check_log())
        return await super().startup(quiet=quiet)

    async def _shutdown(self):
        await self.stopped.wait()
        super().shutdown()

    @override
    def shutdown(self, *, quiet: bool = False) -> bool:
        self.loop.create_task(self._shutdown())
        self.stop_event.set()
        return True

    @override
    def is_available(self) -> bool:
        return True

    @override
    async def render(self, param: dict | None = None) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "value": self._get_base_url() or 'enabled',
        }

    def _get_base_url(self) -> str | None:
        url = self.config.get('base_url')
        if not url:
            lardoon = self.server.extensions.get('Lardoon')
            if lardoon:
                url = lardoon.config.get('url')
        return url.rstrip('/') if url else None

    async def check_log(self):
        try:
            logfile = os.path.expandvars(
                self.config.get('log', os.path.join(self.server.instance.home, 'Logs', 'dcs.log'))
            )
            while not (self.stop_event.is_set() and self.server.status not in [Status.SHUTDOWN, Status.STOPPED]):
                try:
                    while not os.path.exists(logfile):
                        self.log_pos = 0
                        await asyncio.sleep(1)
                    async with aiofiles.open(logfile, mode='r', encoding='utf-8', errors='ignore') as file:
                        max_pos = os.fstat(file.fileno()).st_size
                        if self.log_pos == -1 or max_pos == self.log_pos:
                            self.log_pos = max_pos
                            await asyncio.sleep(1)
                            continue
                        elif max_pos < self.log_pos:
                            self.log_pos = 0

                        self.log_pos = await file.seek(self.log_pos, 0)
                        lines = await file.readlines()
                        for line in lines:
                            if 'End of flight data recorder.' in line or '=== Log closed.' in line:
                                self.log_pos = -1
                                return
                            match = self.exp.search(line)
                            if match:
                                self.log.debug(f"{self.name}: ACMI pattern found.")
                                mission_name = (
                                    self.server.current_mission.name
                                    if self.server.current_mission else None
                                )
                                asyncio.create_task(
                                    self.post_link(match.group('filename'), mission_name)
                                )
                                if self.stop_event.is_set():
                                    return
                        self.log_pos = await file.tell()
                except Exception as ex:
                    self.log.exception(ex)
        finally:
            self.stopped.set()

    async def post_link(self, filename: str, mission_name: str | None):
        for _i in range(60):
            if os.path.exists(filename):
                break
            await asyncio.sleep(1)
        else:
            self.log.warning(f"{self.name}: ACMI file {filename} did not appear within 60s.")
            return

        base_url = self._get_base_url()
        if not base_url:
            self.log.warning(f"{self.name}: lost base URL between startup and post; skipping.")
            return

        basename = os.path.basename(filename)
        timeout = int(self.config.get('poll_timeout', 600))
        interval = int(self.config.get('poll_interval', 30))
        replay_id = await self._poll_for_replay(base_url, basename, timeout, interval)

        if replay_id is None:
            self.log.warning(
                f"{self.name}: ACMI {basename} not indexed by lardoon within {timeout}s; no link posted."
            )
            return

        target = self.config['target']
        if not target.startswith('<id:') or not target.endswith('>'):
            self.log.warning(f"{self.name}: target {target!r} is not a Discord channel reference.")
            return

        viewer_url = f"{base_url}/replay/{replay_id}"
        embed = {
            "title": _("Tacview Replay"),
            "url": viewer_url,
            "color": 0x3498DB,
            "description": _("Replay available for **{mission}** on **{server}**").format(
                mission=mission_name or basename,
                server=self.server.name,
            ),
            "footer": {"text": basename},
        }
        try:
            await self.bus.send_to_node_sync({
                "command": "rpc",
                "service": BotService.__name__,
                "method": "send_message",
                "params": {
                    "channel": int(target[4:-1]),
                    "embed": embed,
                    "server": self.server.name,
                },
            })
            self.log.debug(f"{self.name}: posted lardoon link {viewer_url} for {basename}.")
        except AttributeError:
            self.log.warning(
                f"{self.name}: cannot post link, channel {target[4:-1]} not found."
            )
        except Exception as ex:
            self.log.warning(f"{self.name}: failed to post lardoon link for {basename}: {ex}")

    async def _poll_for_replay(self, base_url: str, basename: str, timeout: int, interval: int) -> int | None:
        deadline = self.loop.time() + timeout
        async with aiohttp.ClientSession() as session:
            while self.loop.time() < deadline:
                try:
                    async with session.get(f"{base_url}/api/replay") as resp:
                        if resp.status != 200:
                            self.log.debug(
                                f"{self.name}: lardoon /api/replay returned {resp.status}"
                            )
                        else:
                            data = await resp.json()
                            replay_id = self._find_replay_id(data, basename)
                            if replay_id is not None:
                                return replay_id
                except Exception as ex:
                    self.log.debug(f"{self.name}: poll error: {ex}")
                await asyncio.sleep(interval)
        return None

    @staticmethod
    def _find_replay_id(replays, basename: str) -> int | None:
        if not isinstance(replays, list):
            return None
        for replay in replays:
            if not isinstance(replay, dict):
                continue
            path = replay.get('path') or ''
            title = replay.get('title') or ''
            if basename in path or basename in title:
                return replay.get('id')
        return None
