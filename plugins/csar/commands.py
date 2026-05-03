import discord
import psycopg

from core import Plugin, utils, DEFAULT_TAG, Report, Group, Server
from discord import app_commands
from services.bot import DCSServerBot

from .listener import CsarEventListener


class Csar(Plugin[CsarEventListener]):
    """Discord-facing commands for the CSAR plugin."""

    def __init__(self, bot: DCSServerBot, listener: type[CsarEventListener]):
        super().__init__(bot, listener)
        cfg = self.locals.get(DEFAULT_TAG, {}) if self.locals else {}
        self.expire_after = cfg.get('expire_after')
        self.lives = cfg.get('lives') or {}
        self.default_server = cfg.get('default_server')

    async def rename(self, conn: psycopg.AsyncConnection, old_name: str, new_name: str) -> None:
        await conn.execute(
            'UPDATE csar_wounded SET server_name = %s WHERE server_name = %s',
            (new_name, old_name)
        )

    async def _resolve_user(
        self, user: discord.Member | str | None, fallback: discord.Member
    ) -> tuple[str | None, str]:
        # Returns (ucid, display_name); ucid is None if no DCS link exists.
        if user is None:
            user = fallback
        if isinstance(user, str):
            ucid = user
            resolved = await self.bot.get_member_or_name_by_ucid(ucid)
            if isinstance(resolved, discord.Member):
                return ucid, resolved.display_name
            return ucid, resolved or ucid
        ucid = await self.bot.get_ucid_by_member(user)
        return ucid, user.display_name

    @staticmethod
    def _rescue_rank(total: int) -> str:
        if total >= 250: return "Hero"
        if total >= 100: return "Legend"
        if total >= 50:  return "Ace"
        if total >= 10:  return "Veteran"
        if total >= 1:   return "Pilot"
        return "Rookie"

    group = Group(name="csar", description="Commands to check your CSAR data")

    @group.command(name="stats", description='Shows CSAR rescue stats')
    @app_commands.guild_only()
    @utils.app_has_role('DCS')
    async def stats(self, interaction: discord.Interaction,
                    user: app_commands.Transform[
                        discord.Member | str, utils.UserTransformer
                    ] | None = None):
        ucid, name = await self._resolve_user(user, interaction.user)
        if not ucid:
            # noinspection PyUnresolvedReferences
            await interaction.response.send_message(
                f"{name} is not linked to a DCS account.", ephemeral=True)
            return

        # noinspection PyUnresolvedReferences
        await interaction.response.defer()
        async with self.apool.connection() as conn:
            cursor = await conn.execute("""
                SELECT COALESCE(SUM(savedpilots), 0) AS total,
                       COUNT(*) AS events,
                       MIN(datestamp) AS first_rescue,
                       MAX(datestamp) AS last_rescue
                FROM csar_events
                WHERE ucid = %s
            """, (ucid,))
            total, events, first_rescue, last_rescue = await cursor.fetchone()

        if total == 0:
            embed = discord.Embed(
                title=f"CSAR Rescues for {name}",
                description="No rescues recorded yet. Go save someone!",
                color=discord.Color.blue()
            )
            await interaction.followup.send(embed=embed)
            return

        report = Report(self.bot, self.plugin_name, 'rescues.json')
        env = await report.render(
            name=name, ucid=ucid,
            rank=self._rescue_rank(int(total)),
            total=int(total), events=int(events),
            first_rescue=first_rescue, last_rescue=last_rescue,
        )
        await interaction.followup.send(embed=env.embed)

    @group.command(name="lives", description='Shows your slot lives for airframes with active CSARs')
    @app_commands.guild_only()
    @utils.app_has_role('DCS')
    async def lives(self, interaction: discord.Interaction,
                    user: app_commands.Transform[
                        discord.Member | str, utils.UserTransformer
                    ] | None = None,
                    server: app_commands.Transform[
                        Server, utils.ServerTransformer
                    ] | None = None):
        ucid, name = await self._resolve_user(user, interaction.user)
        if not ucid:
            # noinspection PyUnresolvedReferences
            await interaction.response.send_message(
                f"{name} is not linked to a DCS account.", ephemeral=True)
            return

        # Looking up someone else's lives is admin-only.
        caller_ucid = await self.bot.get_ucid_by_member(interaction.user)
        if ucid != caller_ucid and not utils.check_roles(
                self.bot.roles['DCS Admin'], interaction.user):
            # noinspection PyUnresolvedReferences
            await interaction.response.send_message(
                "You need the DCS Admin role to view another user's lives.",
                ephemeral=True)
            return

        server_name = server.name if server else self.default_server
        if not server_name:
            # noinspection PyUnresolvedReferences
            await interaction.response.send_message(
                "No `default_server` configured for csar; pass a `server:` to query.",
                ephemeral=True)
            return

        default_allowance = int(self.lives.get('DEFAULT', 0))
        rows: list[dict] = []
        async with self.apool.connection() as conn:
            cursor = await conn.execute("""
                SELECT typename, COUNT(*) AS used
                FROM csar_wounded
                WHERE ucid = %s AND server_name = %s
                GROUP BY typename
                ORDER BY typename
            """, (ucid, server_name))
            for typename, used in await cursor.fetchall():
                allowance = int(self.lives.get(typename, default_allowance))
                remaining = max(0, allowance - int(used))
                rows.append({
                    "airframe": typename,
                    "remaining": str(remaining),
                    "max": str(allowance),
                })

        # noinspection PyUnresolvedReferences
        await interaction.response.defer()
        if not rows:
            embed = discord.Embed(
                title=f"Pilot lives for {name}",
                description=f"All lives intact on **{server_name}**.",
                color=discord.Color.blue()
            )
            await interaction.followup.send(embed=embed)
            return

        report = Report(self.bot, self.plugin_name, 'lives.json')
        env = await report.render(name=name, server_name=server_name, lives=rows)
        await interaction.followup.send(embed=env.embed)


async def setup(bot: DCSServerBot):
    await bot.add_cog(Csar(bot, CsarEventListener))
