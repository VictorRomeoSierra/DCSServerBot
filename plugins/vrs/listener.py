import asyncio
import aiohttp
import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from core import EventListener, event, Server, Player
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .commands import Vrs


# Map specific webhook keys to a fallback category. If the config doesn't
# define the exact key, the bot falls back to the category URL. Lets Shifty
# configure just three channels (messages / admin / bugReport) and have
# every logical key route correctly without per-key URL duplication.
KEY_TO_CATEGORY = {
    "sitrep":   "messages",
    "general":  "messages",
    "events":   "messages",
    "status":   "messages",
    "admin":    "admin",
    "boot":     "admin",
    "bugReport": "bugReport",
}

# Bug-report flow constants.
BUG_REPORT_WINDOW_SECONDS = 120
BUG_REPORT_RATE_LIMIT_SECONDS = 300   # 5 min per UCID between submissions
BUG_REPORT_FLOOD_WINDOW_SECONDS = 60  # sliding window for flood detection
BUG_REPORT_FLOOD_THRESHOLD = 5        # >= this many reports in window = FLOOD prefix
BUG_REPORT_EMBED_COLOR = 0xCC0000     # red
BUG_REPORT_DESCRIPTION_MAX = 3500     # leave headroom under Discord's 4096 cap
BUG_REPORT_RECENT_ERRORS_LIMIT = 4    # how many ring buffer entries to render
                                     # (mission side already prioritises and
                                     # caps to ~4; this is the upper safety net)


@dataclass
class BugCaptureState:
    """Per-(server, ucid) state for an in-flight bug-report capture window."""
    server_name: str
    ucid: str
    player_id: int
    player_name: str
    bug_id: str
    auto_state: dict
    submitted_at: float  # time.monotonic()
    chat_lines: list = field(default_factory=list)
    timer_task: asyncio.Task | None = None


class VrsEventListener(EventListener["Vrs"]):
    """Listener for VRS plugin events.

    Two responsibilities:
      1. sendDiscordWebhook RPC -- mission Lua posts via a webhook key
         (e.g. "admin", "bugReport"); we resolve the URL from
         config/plugins/vrs.yaml. Legacy {url, payload} compat shim still
         accepted; logs WARN so stragglers are easy to find.
      2. Bug-report flow -- F10 -> Personal -> Report a bug fires
         startBugReport with auto-state. We open a 120s rolling chat-capture
         window, accumulate chat from the player (timer resets on each chat),
         then post a Discord embed when the timer expires.
    """

    def __init__(self, plugin):
        super().__init__(plugin)
        # Keyed by (server.name, ucid). Each entry has an asyncio.Task in
        # timer_task; cancel-and-reschedule on every chat to roll the timer.
        self._bug_windows: dict[tuple[str, str], BugCaptureState] = {}
        # Per-UCID last-submitted timestamp for rate-limit gate.
        self._bug_last_submit: dict[str, float] = {}
        # Sliding list of recent submission timestamps for flood detection.
        self._bug_recent_submits: list[float] = []

    # ------------------------------------------------------------------
    # sendDiscordWebhook (existing path, with key-or-url contract)
    # ------------------------------------------------------------------

    @event(name="sendDiscordWebhook")
    async def sendDiscordWebhook(self, server: Server, data: dict):
        payload = data.get('payload')
        if not payload:
            self.log.warning(
                f"VRS sendDiscordWebhook: missing 'payload' (server={server.name})"
            )
            return

        key = data.get('key')
        url = data.get('url')

        if key:
            # New path: resolve URL from plugin config. Try exact-key first,
            # then category fallback (so e.g. key="boot" resolves to
            # webhooks.admin if webhooks.boot isn't configured).
            url = self._resolve_webhook(server, key)
            if not url:
                self.log.warning(
                    f"VRS sendDiscordWebhook: no URL configured for key={key} "
                    f"(server={server.name}) -- check config/plugins/vrs.yaml"
                )
                return
        elif url:
            # Legacy path: mission Lua passed a raw URL. Migration compat shim.
            self.log.warning(
                f"VRS sendDiscordWebhook: legacy {{url, payload}} contract used "
                f"(server={server.name}) -- caller should migrate to {{key, payload}}"
            )
        else:
            self.log.warning(
                f"VRS sendDiscordWebhook: missing both 'key' and 'url' "
                f"(server={server.name})"
            )
            return

        await self._post_to_webhook(url, payload)

    def _resolve_webhook(self, server: Server, key: str) -> str | None:
        config = self.plugin.get_config(server) or {}
        webhooks = config.get('webhooks', {}) or {}
        url = webhooks.get(key)
        if url:
            return url
        category = KEY_TO_CATEGORY.get(key)
        if category:
            return webhooks.get(category)
        return None

    async def _post_to_webhook(self, url: str, payload) -> bool:
        """POST payload to Discord webhook URL. payload may be a JSON string
        (pre-encoded by mission Lua) or a dict (encoded here)."""
        url_preview = url[:60] + ("..." if len(url) > 60 else "")
        if isinstance(payload, dict):
            data_body = json.dumps(payload)
            headers = {'Content-Type': 'application/json'}
        else:
            data_body = payload
            headers = {'Content-Type': 'application/json'}

        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, data=data_body, headers=headers) as resp:
                    if resp.status >= 400:
                        body = await resp.text()
                        body_preview = body[:200].replace('\n', ' ')
                        self.log.warning(
                            f"VRS webhook status={resp.status} "
                            f"url={url_preview} body={body_preview}"
                        )
                        return False
                    self.log.debug(
                        f"VRS webhook status={resp.status} url={url_preview}"
                    )
                    return True
        except aiohttp.ClientError as ex:
            self.log.error(f"VRS webhook client error url={url_preview} err={ex}")
        except asyncio.TimeoutError:
            self.log.error(f"VRS webhook timeout url={url_preview}")
        except Exception:
            self.log.exception(f"VRS webhook unexpected error url={url_preview}")
        return False

    # ------------------------------------------------------------------
    # Bug-report flow
    # ------------------------------------------------------------------

    @event(name="startBugReport")
    async def startBugReport(self, server: Server, data: dict):
        payload_raw = data.get('payload')
        if not payload_raw:
            self.log.warning(f"VRS startBugReport: missing payload (server={server.name})")
            return

        try:
            auto_state = json.loads(payload_raw)
        except (json.JSONDecodeError, TypeError) as ex:
            self.log.warning(
                f"VRS startBugReport: failed to decode payload (server={server.name}): {ex}"
            )
            return

        player_name = auto_state.get('playerName')
        if not player_name:
            self.log.warning(
                f"VRS startBugReport: payload missing playerName (server={server.name})"
            )
            return

        player: Player | None = server.get_player(name=player_name, active=True)
        if not player:
            self.log.warning(
                f"VRS startBugReport: no active player named {player_name!r} on {server.name}"
            )
            return

        key = (server.name, player.ucid)

        # Rate-limit gate. If the player already has an open window OR submitted
        # within the rate-limit window, send a friendly message and bail.
        existing = self._bug_windows.get(key)
        if existing:
            await player.sendChatMessage(
                f"Bug #{existing.bug_id} is still capturing. Keep typing details, "
                f"or stay quiet for {BUG_REPORT_WINDOW_SECONDS}s to submit."
            )
            return

        now = time.monotonic()
        last_submit = self._bug_last_submit.get(player.ucid)
        if last_submit is not None:
            elapsed = now - last_submit
            if elapsed < BUG_REPORT_RATE_LIMIT_SECONDS:
                remaining = int(BUG_REPORT_RATE_LIMIT_SECONDS - elapsed)
                await player.sendChatMessage(
                    f"You've recently submitted a bug report. Try again in {remaining}s."
                )
                return

        # Generate a short bug ID. UCID + current ns suffices; we just want
        # something stable for the lifetime of the window.
        seed = f"{player.ucid}:{time.time_ns()}"
        bug_id = hashlib.md5(seed.encode()).hexdigest()[:6]

        state = BugCaptureState(
            server_name=server.name,
            ucid=player.ucid,
            player_id=player.id,
            player_name=player.name,
            bug_id=bug_id,
            auto_state=auto_state,
            submitted_at=now,
        )
        self._bug_windows[key] = state
        state.timer_task = asyncio.create_task(self._bug_window_timer(key))

        self.log.info(
            f"VRS startBugReport: opened window bug={bug_id} player={player.name} "
            f"ucid={player.ucid} server={server.name}"
        )

        await player.sendChatMessage(
            f"Bug #{bug_id} captured. Type details in chat; report submits "
            f"{BUG_REPORT_WINDOW_SECONDS}s after your last message. "
            f"Stay quiet to submit as-is."
        )

    async def _bug_window_timer(self, key: tuple[str, str]):
        """Sleep BUG_REPORT_WINDOW_SECONDS, then fire the report. Cancelled
        and replaced on each chat from the player (rolling reset)."""
        try:
            await asyncio.sleep(BUG_REPORT_WINDOW_SECONDS)
        except asyncio.CancelledError:
            return  # rescheduled or torn down; nothing to do
        state = self._bug_windows.pop(key, None)
        if not state:
            return
        await self._fire_bug_report(state)

    @event(name="onChatMessage")
    async def onChatMessage(self, server: Server, data: dict):
        from_id = data.get('from')
        message = (data.get('message') or '').strip()
        if not from_id or not message:
            return
        player = server.get_player(id=from_id, active=True)
        if not player:
            return
        key = (server.name, player.ucid)
        state = self._bug_windows.get(key)
        if not state:
            return  # no open capture window for this player

        state.chat_lines.append(message)

        # Roll the timer: cancel + reschedule.
        if state.timer_task and not state.timer_task.done():
            state.timer_task.cancel()
        state.timer_task = asyncio.create_task(self._bug_window_timer(key))

    @event(name="onPlayerStop")
    async def onPlayerStop(self, server: Server, data: dict):
        """Drop any open capture window for the disconnecting player. Their
        report would have nothing to broadcast to anyway."""
        ucid = data.get('ucid')
        if not ucid:
            return
        key = (server.name, ucid)
        state = self._bug_windows.pop(key, None)
        if not state:
            return
        if state.timer_task and not state.timer_task.done():
            state.timer_task.cancel()
        self.log.info(
            f"VRS bugReport: dropped open window bug={state.bug_id} on player stop "
            f"(player={state.player_name} server={server.name})"
        )

    async def _fire_bug_report(self, state: BugCaptureState):
        """Build the Discord embed, post via the bugReport webhook, then
        notify the player in-game with a summary."""
        now = time.monotonic()
        # Update rate-limit + flood-guard bookkeeping.
        self._bug_last_submit[state.ucid] = now
        cutoff = now - BUG_REPORT_FLOOD_WINDOW_SECONDS
        self._bug_recent_submits = [t for t in self._bug_recent_submits if t >= cutoff]
        self._bug_recent_submits.append(now)
        is_flood = len(self._bug_recent_submits) >= BUG_REPORT_FLOOD_THRESHOLD

        # Resolve the server object (we only stored the name in state).
        server = self.bot.servers.get(state.server_name)

        embed = self._build_embed(state, is_flood)

        url = self._resolve_webhook(server, "bugReport") if server else None
        if not url:
            self.log.warning(
                f"VRS bugReport: no URL for key=bugReport (server={state.server_name}) "
                f"-- check config/plugins/vrs.yaml. Bug #{state.bug_id} dropped."
            )
            await self._notify_player(server, state, success=False,
                                      reason="no Discord webhook configured")
            return

        ok = await self._post_to_webhook(url, {"username": "VRS Bug Reports",
                                                "embeds": [embed]})
        await self._notify_player(server, state, success=ok)

        self.log.info(
            f"VRS bugReport: posted bug={state.bug_id} player={state.player_name} "
            f"ucid={state.ucid} server={state.server_name} "
            f"details_lines={len(state.chat_lines)} "
            f"recent_errors={len(state.auto_state.get('recentErrors', []))} "
            f"flood={is_flood} ok={ok}"
        )

    def _build_embed(self, state: BugCaptureState, is_flood: bool) -> dict:
        title = f"Bug #{state.bug_id}"
        if is_flood:
            title = f"**FLOOD** {title}"

        # Description: player-provided chat lines, plus recent-errors code block.
        # Build the code block separately and apply truncation INSIDE the fence
        # so the closing ``` is always preserved (otherwise Discord drops the
        # markdown formatting and the report renders as raw text).
        if state.chat_lines:
            header = "\n".join(state.chat_lines)
        else:
            header = "_(no details added)_"

        recent = state.auto_state.get('recentErrors') or []
        errors_section = ""
        if recent:
            lines = []
            for entry in recent[-BUG_REPORT_RECENT_ERRORS_LIMIT:]:
                level = entry.get('level', '?')
                msg = entry.get('message', '')
                lines.append(f"[{level:5}] {msg}")
            errors_block = "\n".join(lines)

            fence_open = "\n\n**Recent errors**\n```\n"
            fence_close = "\n```"
            truncate_marker = "\n...(truncated)"

            # If the assembled description would exceed the limit, trim the
            # errors_block (which is the only variable-length part) so the
            # closing fence still fits.
            overhead = len(header) + len(fence_open) + len(fence_close)
            available = BUG_REPORT_DESCRIPTION_MAX - overhead
            if available < 0:
                # Header alone is over budget; drop the errors section entirely.
                errors_section = ""
                if len(header) > BUG_REPORT_DESCRIPTION_MAX:
                    header = header[:BUG_REPORT_DESCRIPTION_MAX] + truncate_marker
            elif len(errors_block) > available:
                kept = errors_block[: max(0, available - len(truncate_marker))]
                errors_section = fence_open + kept + truncate_marker + fence_close
            else:
                errors_section = fence_open + errors_block + fence_close

        description = header + errors_section

        auto = state.auto_state
        utc_now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        mission_time_s = int(auto.get('missionTime') or 0)
        mission_time = (
            f"{mission_time_s // 3600:02d}:"
            f"{(mission_time_s % 3600) // 60:02d}:"
            f"{mission_time_s % 60:02d}"
        )

        modules_map = auto.get('modules') or {}
        modules_str = ", ".join(f"{k} {v}" for k, v in sorted(modules_map.items())) or "(none)"
        if len(modules_str) > 1000:
            modules_str = modules_str[:1000] + "..."

        fields = [
            {"name": "Player", "value": f"{auto.get('playerName', '?')} ({auto.get('coalition', '?')})",
             "inline": True},
            {"name": "Aircraft", "value": auto.get('aircraftType', '?'), "inline": True},
            {"name": "Position", "value": auto.get('position', '?'), "inline": False},
            {"name": "Server", "value": state.server_name, "inline": True},
            {"name": "Mission time", "value": f"{mission_time}  ·  {utc_now}", "inline": True},
            {"name": "HEAD", "value": str(auto.get('gitHashShort', '?')), "inline": True},
            {"name": "Modules", "value": modules_str, "inline": False},
        ]

        return {
            "title": title,
            "description": description,
            "color": BUG_REPORT_EMBED_COLOR,
            "fields": fields,
        }

    async def _notify_player(self, server: Server | None,
                              state: BugCaptureState, *,
                              success: bool, reason: str | None = None):
        if not server:
            return
        player = server.get_player(ucid=state.ucid, active=True)
        if not player:
            return
        if success:
            summary = "\n".join(state.chat_lines)[:120]
            if not summary:
                summary = "(no details added)"
            await player.sendChatMessage(
                f"Bug #{state.bug_id} posted. Summary: \"{summary}\". Thanks!"
            )
        else:
            tail = f" ({reason})" if reason else ""
            await player.sendChatMessage(
                f"Bug #{state.bug_id} could not be posted{tail}. "
                f"Tell an admin in Discord."
            )
