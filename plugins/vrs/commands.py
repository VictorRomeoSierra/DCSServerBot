import asyncio
import os
import re

import discord

from core import Plugin, Group, Server, Status, Coalition, utils
from discord import app_commands
from services.bot import DCSServerBot

from .listener import VrsEventListener

WARN_TIMES = (60, 30, 10)

# VRS .miz naming convention: VRS_<Theatre>_<Version>.miz
# Example: "VRS_Syria_0.48.6.miz" -> theatre "Syria"
# Used by /vrs reset_campaign to flag a theatre change in the confirm
# dialog. Returns None when the filename doesn't match the convention.
_THEATRE_RE = re.compile(r'^VRS_([^_]+)_', re.IGNORECASE)


def _theatre_from_miz_name(path_or_name) -> str | None:
    if not path_or_name:
        return None
    name = os.path.basename(str(path_or_name))
    m = _THEATRE_RE.match(name)
    return m.group(1) if m else None


def _lua_quote(s: str) -> str:
    """Wrap a Python string as a Lua string literal. Escapes backslash, double
    quote, and the standard control characters. UTF-8 bytes pass through as-is
    (Lua strings are byte sequences)."""
    return (
        '"'
        + s.replace('\\', '\\\\')
            .replace('"', '\\"')
            .replace('\n', '\\n')
            .replace('\r', '\\r')
        + '"'
    )


class Vrs(Plugin[VrsEventListener]):
    """VRS-specific admin commands (campaign reset, etc.) and mission RPC
    handlers (Discord webhook posting)."""

    def __init__(self, bot: DCSServerBot, listener: type[VrsEventListener]):
        super().__init__(bot, listener)

    group = Group(name="vrs", description="VRS server admin commands")

    @group.command(name="reset_campaign",
                   description="Reset the campaign and restart the server (optionally switching missions)")
    @app_commands.guild_only()
    @utils.app_has_role('DCS Admin')
    @app_commands.rename(mission_id="mission")
    @app_commands.autocomplete(mission_id=utils.mission_autocomplete)
    @app_commands.describe(reason="Optional reason text shown in the campaign-reset embed and audit log")
    @app_commands.describe(mission_id="Optional: pick a different mission to load on the fresh campaign")
    async def reset_campaign(
        self,
        interaction: discord.Interaction,
        server: app_commands.Transform[
            Server, utils.ServerTransformer(status=[Status.RUNNING, Status.PAUSED])
        ],
        reason: str | None = None,
        mission_id: int | None = None,
    ):
        if server.status not in (Status.RUNNING, Status.PAUSED):
            await interaction.response.send_message(
                f"Server {server.name} is not running.", ephemeral=True
            )
            return

        # Resolve the selected mission if one was specified. Validate index
        # against the current mission list before we go anywhere near the
        # destructive path. Theatre comparison is best-effort via the VRS
        # naming convention; if either filename doesn't match, the theatre-
        # change warning is silently skipped (no false positives).
        selected_mission_path = None
        selected_theatre = None
        current_theatre = None
        if mission_id is not None:
            mission_list = await server.getMissionList()
            if mission_id < 0 or mission_id >= len(mission_list):
                await interaction.response.send_message(
                    f"Mission index {mission_id} out of range (have {len(mission_list)} missions).",
                    ephemeral=True
                )
                return
            selected_mission_path = mission_list[mission_id]
            selected_theatre = _theatre_from_miz_name(selected_mission_path)

            current_filename = None
            try:
                if server.current_mission is not None:
                    current_filename = server.current_mission.filename
            except AttributeError:
                pass
            current_theatre = _theatre_from_miz_name(current_filename)

        warn_times = sorted(WARN_TIMES, reverse=True)
        lead_time = warn_times[0]

        # yn_question puts `question` into the embed title (Discord caps at
        # 256 chars) and `message` into the description (4096 cap). Keep the
        # title short; put the verbose detail + mission/theatre info in the
        # description.
        confirm_title = f"Reset the campaign on {server.name}?"
        confirm_details = (
            f"Players will get a **{lead_time}-second** warning, then the server "
            f"will restart. All previous progress, base ownership, salvage jobs, "
            f"and CSAR state will be cleared."
        )
        if selected_mission_path:
            confirm_details += (
                f"\n\nNew mission: **{os.path.basename(selected_mission_path)}**"
            )
        if current_theatre and selected_theatre \
                and current_theatre.lower() != selected_theatre.lower():
            confirm_details += (
                f"\n\n**WARNING: THEATRE CHANGE** -- "
                f"{current_theatre} -> {selected_theatre}"
            )

        if not await utils.yn_question(interaction, confirm_title, message=confirm_details):
            await interaction.followup.send("Cancelled.", ephemeral=True)
            return

        reason_str = (reason or "").strip()

        async def _warn(secs_left: int):
            await asyncio.sleep(lead_time - secs_left)
            popup = f"Campaign reset in {secs_left} second{'s' if secs_left != 1 else ''} - land or eject!"
            if reason_str:
                popup += f"\nReason: {reason_str}"
            await server.sendPopupMessage(Coalition.ALL, popup)

        ack = (
            f"Campaign reset armed on **{server.name}**. "
            f"Server will restart in {lead_time} seconds."
        )
        if reason_str:
            ack += f"\nReason: {reason_str}"
        if selected_mission_path:
            ack += f"\nNew mission: {os.path.basename(selected_mission_path)}"
        await interaction.followup.send(ack, ephemeral=utils.get_ephemeral(interaction))

        await utils.run_parallel_nofail(*(_warn(t) for t in warn_times))

        script = f"VRS.persistence.armCampaignReset({_lua_quote(reason_str)})"
        await server.send_to_dcs({"command": "do_script", "script": script})

        # If a different mission was selected, set the start index BEFORE
        # the process cycle so startup boots into the new .miz.
        # setStartIndex is 1-indexed per the DCSServerBot contract.
        if mission_id is not None:
            await server.setStartIndex(mission_id + 1)

        # Full DCS process cycle (not just `server.restart`, which only reloads
        # the mission). shutdown + startup re-runs the bot's plugin-Lua-glue
        # install (_install_plugin copies plugins/<name>/lua/* into Saved Games),
        # so any pushed mission-Lua hotfixes plus updated bot plugin glue take
        # effect on the post-reset boot. Adds ~30s of downtime vs mission reload.
        await server.shutdown()
        await server.startup(modify_mission=True)

        audit_msg = f"reset campaign on {server.name} (DCS cycled)"
        if selected_mission_path:
            audit_msg += f" -- new mission: {os.path.basename(selected_mission_path)}"
        if reason_str:
            audit_msg += f" (reason: {reason_str})"
        await self.bot.audit(audit_msg, user=interaction.user, server=server)


async def setup(bot: DCSServerBot):
    await bot.add_cog(Vrs(bot, VrsEventListener))
