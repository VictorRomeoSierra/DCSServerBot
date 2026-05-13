import asyncio
import aiohttp

from core import EventListener, event, Server
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .commands import Vrs


class VrsEventListener(EventListener["Vrs"]):
    """Listener for VRS plugin events.

    Currently handles the Discord webhook RPC that replaces the legacy
    JAPI.cont.postDiscord call path. Mission code (VRScore.lua) ships a
    pre-encoded JSON payload + a Discord webhook URL; this handler does
    the HTTPS POST via aiohttp and logs the response status. Discord
    returns 204 No Content on success; 4xx/5xx are logged WARN with a
    body preview to make routing/cert/payload issues debuggable in Seq.
    """

    @event(name="sendDiscordWebhook")
    async def sendDiscordWebhook(self, server: Server, data: dict):
        url = data.get('url')
        payload = data.get('payload')
        if not url:
            self.log.warning(
                f"VRS sendDiscordWebhook: missing 'url' (server={server.name})"
            )
            return
        if not payload:
            self.log.warning(
                f"VRS sendDiscordWebhook: missing 'payload' (server={server.name})"
            )
            return

        url_preview = url[:60] + ("..." if len(url) > 60 else "")

        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    url,
                    data=payload,
                    headers={'Content-Type': 'application/json'},
                ) as resp:
                    if resp.status >= 400:
                        body = await resp.text()
                        body_preview = body[:200].replace('\n', ' ')
                        self.log.warning(
                            f"VRS sendDiscordWebhook status={resp.status} "
                            f"url={url_preview} body={body_preview}"
                        )
                    else:
                        self.log.info(
                            f"VRS sendDiscordWebhook status={resp.status} "
                            f"url={url_preview}"
                        )
        except aiohttp.ClientError as ex:
            self.log.error(
                f"VRS sendDiscordWebhook client error url={url_preview} err={ex}"
            )
        except asyncio.TimeoutError:
            self.log.error(f"VRS sendDiscordWebhook timeout url={url_preview}")
        except Exception:
            self.log.exception(
                f"VRS sendDiscordWebhook unexpected error url={url_preview}"
            )
