import asyncio

import discord

from core import Plugin, Group, Server, Status, Coalition, utils
from discord import app_commands
from services.bot import DCSServerBot

from .listener import VrsEventListener

WARN_TIMES = (60, 30, 10)


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
                   description="Reset the campaign and restart the server")
    @app_commands.guild_only()
    @utils.app_has_role('DCS Admin')
    async def reset_campaign(
        self,
        interaction: discord.Interaction,
        server: app_commands.Transform[
            Server, utils.ServerTransformer(status=[Status.RUNNING, Status.PAUSED])
        ],
        reason: str | None = None,
    ):
        if server.status not in (Status.RUNNING, Status.PAUSED):
            await interaction.response.send_message(
                f"Server {server.name} is not running.", ephemeral=True
            )
            return

        warn_times = sorted(WARN_TIMES, reverse=True)
        lead_time = warn_times[0]

        confirm_text = (
            f"Reset the campaign on **{server.name}**?\n"
            f"Players will get a **{lead_time}-second** warning, then the server "
            f"will restart. All previous progress, base ownership, salvage jobs, "
            f"and CSAR state will be cleared."
        )
        if not await utils.yn_question(interaction, confirm_text):
            await interaction.followup.send("Cancelled.", ephemeral=True)
            return

        reason_str = (reason or "").strip()

        async def _warn(secs_left: int):
            await asyncio.sleep(lead_time - secs_left)
            popup = f"Campaign reset in {secs_left} second{'s' if secs_left != 1 else ''} — land or eject!"
            if reason_str:
                popup += f"\nReason: {reason_str}"
            await server.sendPopupMessage(Coalition.ALL, popup)

        ack = (
            f"Campaign reset armed on **{server.name}**. "
            f"Server will restart in {lead_time} seconds."
        )
        if reason_str:
            ack += f"\nReason: {reason_str}"
        await interaction.followup.send(ack, ephemeral=utils.get_ephemeral(interaction))

        await utils.run_parallel_nofail(*(_warn(t) for t in warn_times))

        script = f"VRS.persistence.armCampaignReset({_lua_quote(reason_str)})"
        await server.send_to_dcs({"command": "do_script", "script": script})
        await server.restart(modify_mission=True)

        audit_msg = f"reset campaign on {server.name} (server restarted)"
        if reason_str:
            audit_msg += f" (reason: {reason_str})"
        await self.bot.audit(audit_msg, user=interaction.user, server=server)


async def setup(bot: DCSServerBot):
    await bot.add_cog(Vrs(bot, VrsEventListener))
