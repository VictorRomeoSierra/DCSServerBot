import discord

from core import Plugin, Group, Server, Status, utils
from discord import app_commands
from services.bot import DCSServerBot

from .listener import VrsEventListener


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
                   description="Arm a campaign reset for the next server restart")
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

        # Destructive — require explicit confirmation.
        confirm_text = (
            f"Arm a campaign reset on **{server.name}**?\n"
            f"All previous progress, base ownership, salvage jobs, and CSAR state "
            f"will be cleared on the next server restart."
        )
        if not await utils.yn_question(interaction, confirm_text):
            await interaction.followup.send("Cancelled.", ephemeral=True)
            return

        reason_str = (reason or "").strip()
        script = f"VRS.persistence.armCampaignReset({_lua_quote(reason_str)})"
        await server.send_to_dcs({"command": "do_script", "script": script})

        msg = (
            f"Campaign reset armed on **{server.name}**. "
            f"It will fire on the next server restart."
        )
        if reason_str:
            msg += f"\nReason: {reason_str}"
        await interaction.followup.send(msg, ephemeral=utils.get_ephemeral(interaction))

        audit_msg = f"armed campaign reset on {server.name}"
        if reason_str:
            audit_msg += f" (reason: {reason_str})"
        await self.bot.audit(audit_msg, user=interaction.user, server=server)


async def setup(bot: DCSServerBot):
    await bot.add_cog(Vrs(bot, VrsEventListener))
