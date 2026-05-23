import discord

from core import Plugin, Group, utils
from discord import app_commands
from discord.ext import commands
from services.bot import DCSServerBot

from .listener import PatreonEventListener, resolve_tier


# Discord embed colour for /patreon list. Patreon's brand orange would be
# nicer but feels gimmicky; using a neutral purple that reads fine in both
# light and dark themes.
EMBED_COLOR = 0x9B59B6

# /patreon list shows at most this many names per tier inline; remainder is
# rolled into a "+N more" suffix so we never bump the Discord field 1024-char
# cap.
LIST_NAMES_PER_TIER = 25


class Patreon(Plugin[PatreonEventListener]):
    """VRS Patreon plugin -- syncs Patreon tier status (via Discord roles
    granted by Patreon's native integration) into the mission, so mission-
    side perks can key off the patron tier. No DB; tier is resolved at
    connect time from the player's Discord roles."""

    def __init__(self, bot: DCSServerBot, listener: type[PatreonEventListener]):
        super().__init__(bot, listener)

    group = Group(name="patreon", description="VRS Patreon tier commands")

    def _tiers_config(self) -> list[dict] | None:
        """Resolve the tiers list from plugin DEFAULT config (guild-wide)."""
        config = self.get_config()
        if not config:
            return None
        return config.get('tiers') or None

    def _tier_label(self, tiers_config: list[dict], tier: int) -> str:
        for entry in tiers_config:
            if entry.get('tier') == tier:
                return entry.get('label') or f"Tier {tier}"
        return f"Tier {tier}"

    @group.command(name="list",
                   description="List patrons currently in the Discord guild, grouped by tier")
    @app_commands.guild_only()
    @utils.app_has_role('DCS Admin')
    async def list_patrons(self, interaction: discord.Interaction):
        tiers_config = self._tiers_config()
        if not tiers_config:
            await interaction.response.send_message(
                "Patreon plugin has no `tiers` configured. "
                "Edit `config/plugins/patreon.yaml`.",
                ephemeral=True,
            )
            return

        guild = interaction.guild
        if not guild:
            await interaction.response.send_message(
                "No guild context.", ephemeral=True
            )
            return

        by_tier: dict[int, list[discord.Member]] = {}
        for member in guild.members:
            if member.bot:
                continue
            tier = resolve_tier(member, tiers_config)
            if tier is not None:
                by_tier.setdefault(tier, []).append(member)

        if not by_tier:
            await interaction.response.send_message(
                "No patrons found in this guild.", ephemeral=True
            )
            return

        embed = discord.Embed(title="VRS Patrons", color=EMBED_COLOR)
        total = 0
        for tier in sorted(by_tier.keys(), reverse=True):
            members = sorted(by_tier[tier], key=lambda m: m.display_name.lower())
            total += len(members)
            shown = members[:LIST_NAMES_PER_TIER]
            extra = len(members) - len(shown)
            value = ", ".join(m.display_name for m in shown)
            if extra > 0:
                value += f"  (+{extra} more)"
            embed.add_field(
                name=f"{self._tier_label(tiers_config, tier)}  ({len(members)})",
                value=value or "_(none)_",
                inline=False,
            )
        embed.set_footer(text=f"{total} patron{'s' if total != 1 else ''} total")
        await interaction.response.send_message(
            embed=embed, ephemeral=utils.get_ephemeral(interaction)
        )

    @group.command(name="whois",
                   description="Report a user's resolved Patreon tier")
    @app_commands.guild_only()
    @utils.app_has_role('DCS Admin')
    async def whois(self, interaction: discord.Interaction,
                    member: discord.Member):
        tiers_config = self._tiers_config()
        if not tiers_config:
            await interaction.response.send_message(
                "Patreon plugin has no `tiers` configured.",
                ephemeral=True,
            )
            return
        tier = resolve_tier(member, tiers_config)
        if tier is None:
            await interaction.response.send_message(
                f"{member.display_name} has no Patreon tier role.",
                ephemeral=utils.get_ephemeral(interaction),
            )
            return
        label = self._tier_label(tiers_config, tier)
        await interaction.response.send_message(
            f"{member.display_name} -- **{label}** (tier {tier})",
            ephemeral=utils.get_ephemeral(interaction),
        )


    # ------------------------------------------------------------------
    # Membership change announcements (Discord-side, no DCS involvement).
    # Triggered by Patreon's native Discord role grant/revoke; we observe
    # the role diff via on_member_update and announce tier transitions.
    # ------------------------------------------------------------------

    async def _announce(self, message: str) -> None:
        config = self.get_config() or {}
        channel_id = config.get('announce_channel')
        if not channel_id:
            self.log.debug(f"Patreon: announce suppressed (no channel): {message}")
            return
        channel = self.bot.get_channel(int(channel_id))
        if channel is None:
            self.log.warning(
                f"Patreon: announce_channel {channel_id} not found / no access."
            )
            return
        try:
            await channel.send(message)
        except discord.DiscordException as ex:
            self.log.warning(f"Patreon: failed to send announcement: {ex}")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member,
                               after: discord.Member) -> None:
        tiers_config = self._tiers_config()
        if not tiers_config:
            return
        before_tier = resolve_tier(before, tiers_config)
        after_tier = resolve_tier(after, tiers_config)
        if before_tier == after_tier:
            return  # role change unrelated to patron tiers (or no change)

        if before_tier is None:
            # First-time patron (no prior tier role).
            label = self._tier_label(tiers_config, after_tier)
            await self._announce(
                f"{after.mention} just became a **{label}** patron. Thank you!"
            )
        elif after_tier is None:
            # Lost their last tier role -- ended Patreon support.
            label = self._tier_label(tiers_config, before_tier)
            await self._announce(
                f"{after.mention} is no longer a patron (was **{label}**)."
            )
        else:
            before_label = self._tier_label(tiers_config, before_tier)
            after_label = self._tier_label(tiers_config, after_tier)
            if after_tier > before_tier:
                await self._announce(
                    f"{after.mention} upgraded from **{before_label}** "
                    f"to **{after_label}**."
                )
            else:
                await self._announce(
                    f"{after.mention} moved from **{before_label}** "
                    f"to **{after_label}**."
                )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        tiers_config = self._tiers_config()
        if not tiers_config:
            return
        # member.roles is still populated at remove time -- resolve their
        # tier from the snapshot we have, so we can announce them leaving
        # as a patron rather than as a generic departure.
        tier = resolve_tier(member, tiers_config)
        if tier is None:
            return
        label = self._tier_label(tiers_config, tier)
        # User mention won't ping (they're gone); fall back to display name
        # plus their ID for paper-trail.
        await self._announce(
            f"**{member.display_name}** left the server "
            f"(was a **{label}** patron)."
        )


async def setup(bot: DCSServerBot):
    await bot.add_cog(Patreon(bot, PatreonEventListener))
