import asyncio
import json

from core import EventListener, event, chat_command, Player, Server
from psycopg.rows import dict_row
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .commands import Csar


class CsarEventListener(EventListener["Csar"]):

    async def _resolve_ucid(self, conn, server: Server, playername: str | None) -> str | None:
        # Reuse caller's connection so we don't nest pool acquisitions inside an open transaction.
        if not playername:
            return None
        player = server.get_player(name=playername)
        if player and player.ucid:
            return player.ucid
        cursor = await conn.execute("""
            SELECT ucid FROM players
            WHERE name = %s AND LENGTH(ucid) = 32
            ORDER BY last_seen DESC NULLS LAST
            LIMIT 1
        """, (playername,))
        row = await cursor.fetchone()
        return row[0] if row else None

    @event(name="csarStatData")
    async def csarStatData(self, server: Server, data: dict):
        stats = json.loads(data['data'])
        if not stats:
            return data
        async with self.apool.connection() as conn:
            async with conn.transaction():
                for playername, by_ts in stats.items():
                    ucid = await self._resolve_ucid(conn, server, playername)
                    for ts, entry in by_ts.items():
                        await conn.execute("""
                            INSERT INTO csar_events
                                (ts, playername, ucid, savedpilots, helicopterused)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (ts, playername, ucid,
                              entry['savedPilots'], entry['helicopterUsed']))
        return data

    @event(name="csarSavePersistentData")
    async def savePersistentData(self, server: Server, data: dict):
        wounded = json.loads(data['data'])
        current_ids = [w['id'] for w in wounded]
        async with self.apool.connection() as conn:
            async with conn.transaction():
                for w in wounded:
                    playername = w.get('playername') or w.get('unitname')
                    ucid = await self._resolve_ucid(conn, server, playername)
                    await conn.execute("""
                        INSERT INTO csar_wounded
                            (id, coalition, country, pos, coordinates, typename,
                             unitname, playername, ucid, freq, voice, server_name)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (id, server_name) DO UPDATE SET
                            coalition   = EXCLUDED.coalition,
                            country     = EXCLUDED.country,
                            pos         = EXCLUDED.pos,
                            coordinates = EXCLUDED.coordinates,
                            typename    = EXCLUDED.typename,
                            unitname    = EXCLUDED.unitname,
                            playername  = EXCLUDED.playername,
                            ucid        = EXCLUDED.ucid,
                            freq        = EXCLUDED.freq,
                            voice       = EXCLUDED.voice
                    """, (w['id'], w['coalition'], w['country'], json.dumps(w['pos']),
                          w['coordinates'], w['typename'], w['unitname'], playername,
                          ucid, w['freq'], w.get('voice'), server.name))
                if current_ids:
                    await conn.execute("""
                        DELETE FROM csar_wounded
                        WHERE server_name = %s AND id <> ALL(%s)
                    """, (server.name, current_ids))
                else:
                    await conn.execute(
                        'DELETE FROM csar_wounded WHERE server_name = %s',
                        (server.name,))
        return data

    @event(name="csarGetPersistentData")
    async def getPersistentData(self, server: Server, _data: dict):
        expire_after = self.plugin.expire_after
        async with self.apool.connection() as conn:
            async with conn.transaction():
                if expire_after:
                    await conn.execute("""
                        DELETE FROM csar_wounded
                        WHERE server_name = %s
                          AND datestamp < NOW() - %s::interval
                    """, (server.name, expire_after))
            async with conn.cursor(row_factory=dict_row) as cursor:
                await cursor.execute("""
                    SELECT DATE_PART('EPOCH', datestamp) AS time, id, coalition,
                           country, pos, coordinates, typename, unitname,
                           playername, freq, voice
                    FROM csar_wounded
                    WHERE server_name = %s
                """, (server.name,))
                rows = await cursor.fetchall()

        if not rows:
            self.log.debug("CSAR: no wounded pilots in DB for %s", server.name)
            return

        # DCS-side handler can't ingest the whole list at once; chunk it.
        BATCH = 5
        for i in range(0, len(rows), BATCH):
            chunk = rows[i:i + BATCH]
            await server.send_to_dcs({
                'command': 'csarUpdatePersistentData',
                'data': json.dumps(chunk)
            })
            if i + BATCH < len(rows):
                await asyncio.sleep(1)

    @event(name="csarGetLives")
    async def csarGetLives(self, server: Server, _data: dict):
        await server.send_to_dcs({
            'command': 'csarSetLives',
            'data': json.dumps(self.plugin.lives)
        })

    @event(name="rescuedPilot")
    async def rescuedPilot(self, server: Server, data: dict):
        player: Player | None = server.get_player(name=data['playername'], active=True)
        if player:
            await player.sendChatMessage(
                f"Your {data['typename']} pilot has been rescued by {data['pilotname']}"
            )

    @event(name="blockSlot")
    async def blockSlot(self, server: Server, data: dict) -> None:
        block = data['block']
        await server.send_to_dcs({
            'command': 'csarBlockSlot',
            'playerName': data['playerName'],
            'typeName': data['typeName'],
            'block': block
        })
        if block:
            player: Player | None = server.get_player(name=data['playerName'], active=True)
            if player:
                await server.move_to_spectators(
                    player,
                    f"You have no more lives for {data['typeName']} airframes."
                )

    @event(name="onPlayerStart")
    async def onPlayerStart(self, server: Server, data: dict) -> None:
        if data['id'] == 1 or 'ucid' not in data:
            return
        player: Player | None = server.get_player(ucid=data['ucid'])
        if not player or not player.member:
            return
        await server.send_to_dcs({
            'command': 'csarSetUserDiscord',
            'name': player.display_name,
            'discord': player.member.id
        })

    @chat_command(name="csar", roles=['DCS Admin'], help="CSAR admin probe")
    async def csar(self, _server: Server, player: Player, _params: list[str]):
        await player.sendChatMessage("This is a csar command!")
