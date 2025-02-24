import json
import time
import asyncio

from psycopg.rows import dict_row
from contextlib import closing

from core import EventListener, event, chat_command, Player, DEFAULT_TAG, Server, Player

# from typing import TYPE_CHECKING

# if TYPE_CHECKING:
#     from core import Server

class CsarEventListener(EventListener):
    """
    A class where your DCS events will be handled.

    Methods
    -------
    registerDCSServer(data)
        Called on registration of any DCS server.

    sample(data)
        Called whenever ".sample" is called in discord (see commands.py).
    """
    @event(name="registerDCSServer")
    async def registerDCSServer(self, server: Server, data: dict) -> None:
        self.expire_after = self.locals.get(DEFAULT_TAG, {}).get('expire_after')
        self.log.debug(f"CSAR: reading number of lives from csar.yaml")
        self.lives = self.locals.get(DEFAULT_TAG, {}).get('lives')


    def get_csar_wounded(self, server: Server) -> list[dict]:
        with self.pool.connection() as conn:
            with closing(conn.cursor(row_factory=dict_row)) as cursor:
                return list(cursor.execute("""
                    SELECT DATE_PART('EPOCH', datestamp) AS time, id, coalition, country, pos, coordinates, typename, unitname, playername, freq FROM csar_wounded
                    WHERE server_name = %s
                """, (server.name, )).fetchall())

    @event(name="csarStatData")
    async def csarStatData(self, server: Server, data: dict):
        stats = json.loads(data['data'])
        if stats:
            playernames = stats.keys()
            with self.pool.connection() as conn:
                with conn.transaction():
                    for playername in playernames:
                        ucid, name = await self.bot.get_ucid_by_name(playername)
                        if ucid is None:
                            ucid = -1
                            name = playername
                        timestamps = stats[playername].keys()
                        for ts in timestamps:
                            conn.execute("""
                                INSERT INTO csar_events (ts, playername, ucid, savedpilots, helicopterused) 
                                VALUES (%s, %s, %s, %s, %s)
                            """, (ts, name, ucid, stats[playername][ts]['savedPilots'], stats[playername][ts]['helicopterUsed']))
        return data

    @event(name="csarSavePersistentData")
    async def savePersistentData(self, server: Server, data: dict):
        wounded = json.loads(data['data'])
        currentids = ""
        # {"coalition":"blue","coordinates":"120.1, 241.0","unitname":"csar 1-1","country":"usa","playername":"Agaarin","freq":"4201","typename":"MI-8MTV2","pos":"120.1, 241.0"}
        with self.pool.connection() as conn:
            with conn.transaction():
                for w in wounded:
                    currentids += "'" + w['id'] + "', "
                    playername = ""
                    if 'playername' in w:
                        playername = w['playername']
                    else:
                        playername = w['unitname']
                    row = conn.execute("""
                        SELECT id FROM csar_wounded WHERE id = %s AND server_name = %s
                        """,(w['id'], server.name, )).fetchone()
                    if row:
                        conn.execute("""
                            UPDATE csar_wounded SET (coalition, country, pos, coordinates, typename, unitname, playername, freq, server_name) = (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                            WHERE id = %s AND server_name = %s
                            """, (w['coalition'], w['country'], json.dumps(w['pos']), w['coordinates'], w['typename'], w['unitname'], playername, w['freq'], server.name, w['id'], server.name))
                    else:
                        conn.execute("""
                            INSERT INTO csar_wounded (id, coalition, country, pos, coordinates, typename, unitname, playername, freq, server_name) 
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """, (w['id'], w['coalition'], w['country'], json.dumps(w['pos']), w['coordinates'], w['typename'], w['unitname'], playername, w['freq'], server.name))
                if currentids:
                    delete = "DELETE FROM csar_wounded WHERE id NOT IN (" + currentids.strip(', ') + ") AND server_name = '" + server.name + "'"
                else:
                     delete = "DELETE FROM csar_wounded WHERE server_name = '" + server.name + "'"
                conn.execute(delete)
        return data

    @event(name="csarGetPersistentData")
    async def getPersistentData(self, server: Server, data: dict):
        self.log.debug(server.name + " csarGetPersistentData start")
        command = "DELETE FROM csar_wounded WHERE datestamp < NOW() - INTERVAL '" + self.expire_after + "' AND server_name = '" + server.name + "'"
        with self.pool.connection() as conn:
            with conn.transaction():
                conn.execute(command)
        data = self.get_csar_wounded(server=server)
        if not data:
            self.log.debug(f"CSAR: No wounded pilots in database")
            return
        i = 0
        concat = ""
        for row in data:
            if concat == "":
                concat = "[" + json.dumps(row)
            else:
                concat += ", " + json.dumps(row)
            i += 1
            if i >= 5:
                concat += "]"
                asyncio.create_task(server.send_to_dcs({
                    'command': 'csarUpdatePersistentData',
                    'data': concat
                }))
                self.log.debug(server.name + " csarGetPersistentData sent data " + concat)
                concat = ""
                i = 0
                time.sleep(1)
        if concat != "":
            concat += "]"
            asyncio.create_task(server.send_to_dcs({
                'command': 'csarUpdatePersistentData',
                'data': concat
            }))
            self.log.debug(server.name + " csarGetPersistentData sent data " + concat)
        return

    @event(name="csarGetLives")
    async def csarGetLives(self, server: Server, data: dict):
        self.log.debug('csarGetLives called, self.lives: {}'.format(str(self.lives)))
        asyncio.create_task(server.send_to_dcs({
                'command': 'csarSetLives',
                'data': json.dumps(self.lives)  #'[{}]'.format()
            }))

    @chat_command(name="csar", roles=['DCS Admin'], help="A sample command")
    async def csar(self, server: Server, player: Player, params: list[str]):
        asyncio.create_task(player.sendChatMessage("This is a csar command!"))

    @event(name="rescuedPilot")
    async def rescuedPilot(self, server: Server, data: dict):
        self.log.debug(f"CSAR: A pilot was rescued!")
        playername = data['playername']
        typename = data['typename']
        pilotname = data['pilotname']
        # ucid, name = self.bot.get_ucid_by_name(playername)
        player: Player = server.get_player(name=playername, active=True)
        # self.log.debug('player found? {}'.format(player))
        if player:
            self.log.debug('Message sent to {}'.format(playername))
            asyncio.create_task(player.sendChatMessage('Your {} pilot has been rescued by {}'.format(typename, pilotname)))
    
    @event(name="blockSlot")
    async def blockSlot(self, server: Server, data: dict) -> None:
        block = data['block']
        self.log.debug('CSAR: blockSlot called: playerName {}, typeName {}, block {}'.format(data['playerName'], data['typeName'], block))
        asyncio.create_task(server.send_to_dcs({
            'command': 'csarBlockSlot',
            'playerName': data['playerName'],
            'typeName': data['typeName'],
            'block': block
        }))
        if block:
            self.log.debug('CSAR: attempting to move to spectators')
            player: Player = server.get_player(name=data['playerName'], active=True)
            reason = 'Unfortunatley, you have no more lives for {} airframes.'.format(data['typeName'])
            asyncio.create_task(server.move_to_spectators(player, reason))

    @event(name="onPlayerStart")
    async def onPlayerStart(self, server: Server, data: dict) -> None:
        self.log.debug('CSAR: onPlayerStart - start')
        if data['id'] == 1 or 'ucid' not in data:
            return
        player: Player = server.get_player(ucid=data['ucid'])
        if not player or not player.member:
            self.log.debug('CSAR: onPlayerStart - player or member not found')
            return
        else:
            # noinspection PyAsyncCall
            self.log.debug('CSAR: onPlayerStart - player ' + player.display_name + ' added with discord ID ' + str(player.member.id))
            asyncio.create_task(server.send_to_dcs({
                'command': 'csarSetUserDiscord',
                'name': player.display_name,
                'discord': player.member.id
            }))