import discord
import psycopg
import requests
import json

from contextlib import closing
from core import Plugin, utils, Server, TEventListener, Status, command, DEFAULT_TAG, Report, ReportEnv, Group
from discord import app_commands
from services import DCSServerBot
from typing import Type
from discord.ext import tasks
from typing import Optional, Union
from psycopg.rows import dict_row

from .listener import CsarEventListener


class Csar(Plugin):
    """
    A class where all your discord commands should go.

    If you need a specific initialization, make sure that you call super().__init__() after it, to
    assure a proper initialization of the plugin.

    Attributes
    ----------
    :param bot: DCSServerBot
        The discord bot instance.
    :param listener: EventListener
        A listener class to receive events from DCS.

    Methods
    -------
    sample(ctx, text)
        Send the text to DCS, which will return the same text again (echo).
    """

    def __init__(self, bot: DCSServerBot, listener: Type[TEventListener]):
        super().__init__(bot, listener)
        self.expire_after = self.locals.get(DEFAULT_TAG, {}).get('expire_after')
        # self.prune.add_exception_type(psycopg.DatabaseError)
        # self.prune.start()

        # api_url = "https://customdcs.com/playerranks.json"
        # response = requests.get(api_url)
        # self.rank_table = response.json()

        self.lives = self.locals.get(DEFAULT_TAG, {}).get('lives')

    def rename(self, conn: psycopg.Connection, old_name: str, new_name: str):
        # If a server rename takes place, you might want to update data in your created tables
        # if they contain a server_name value. You usually don't need to implement this function.
        pass
    
    group = Group(name="csar", description="Commands to check your CSAR data")

    @group.command(name="stats", description='Shows your CSAR stats')
    @app_commands.guild_only()
    @utils.app_has_role('DCS')
    async def stats(self, interaction: discord.Interaction,
                     user: Optional[app_commands.Transform[Union[str, discord.Member], utils.UserTransformer]]):

        if not user:
            user = interaction.user
        if isinstance(user, str):
            ucid = user
            user = self.bot.get_member_or_name_by_ucid(ucid)
            if isinstance(user, discord.Member):
                name = user.display_name
            else:
                name = user
        else:
            ucid = self.bot.get_ucid_by_member(user)
            name = user.display_name
        
        with self.pool.connection() as conn:
            with conn.transaction():
                row = conn.execute("""
                    SELECT SUM(savedpilots) as total_rescues FROM csar_events WHERE ucid = %s
                    """,(ucid, )).fetchone()
                total_rescues = row[0]
        if not total_rescues: total_rescues = 0

        rank = "Non CSAR Pilot"
        # for key in self.rank_table:
        #     if int(key) <= total_rescues :
        #         rank = self.rank_table[key]
        #     else:
        #         if int(key) > total_rescues :
        #             break

        report = Report(self.bot, self.plugin_name, 'rescues.json')
        env = await report.render(name=name, ucid=ucid, rank=rank)  # params={"rescues": rescues}
        await interaction.response.send_message(embed=env.embed)

    @group.command(name="lives", description='Shows your slot lives for airframes with active CSARs')
    @app_commands.guild_only()
    @utils.app_has_role('DCS')
    async def lives(self, interaction: discord.Interaction,
                     user: Optional[app_commands.Transform[Union[str, discord.Member], utils.UserTransformer]]):
        if not user:
            user = interaction.user
        if isinstance(user, str):
            ucid = user
            user = self.bot.get_member_or_name_by_ucid(ucid)
            if isinstance(user, discord.Member):
                name = user.display_name
            else:
                name = user
        else:
            ucid = self.bot.get_ucid_by_member(user)
            name = user.display_name
        
        lives = {}
        with self.pool.connection() as conn:
            with conn.transaction():
                rows = conn.execute("""
                    SELECT typename, count(*) FROM csar_wounded w
                    JOIN players p ON w.playername = p.name
                    WHERE p.ucid = %s
                    GROUP BY typename
                    """,(ucid, )).fetchall()
                for row in rows:
                    if self.lives[row[0]]:
                        lives[row[0]] = int(self.lives[row[0]]) - int(row[1])
                    else:
                        lives[row[0]] = int(self.lives['DEFAULT']) - int(row[1])
        
        report = Report(self.bot, self.plugin_name, 'lives.json')
        env = await report.render(name=name, lives=lives)
        await interaction.response.send_message(embed=env.embed)

    # @tasks.loop(hours=1.0)
    # async def prune(self):
    #     if self.expire_after:
    #         self.log.debug('CSAR: Pruning aged CSARS from DB')
    #         # self.log.debug('self.expire_after: {}'.format(self.expire_after))
    #         command = "DELETE FROM csar_wounded WHERE datestamp < NOW() - INTERVAL '{}'".format(self.expire_after)
    #         # self.log.debug(command)
    #         with self.pool.connection() as conn:
    #             with conn.transaction():
    #                 conn.execute(command)

async def setup(bot: DCSServerBot):
    await bot.add_cog(Csar(bot, CsarEventListener))
