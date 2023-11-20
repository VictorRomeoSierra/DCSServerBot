from psycopg.rows import dict_row
from contextlib import closing

from core import EventListener, Server, event, chat_command, Player


class VRSPersistencyLibraryEventListener(EventListener):
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
        self.log.debug(f"I've received a registration event from server {server.name}!")

    def get_persistent_objects(self) -> list[dict]:
        with self.pool.connection() as conn:
            with closing(conn.cursor(row_factory=dict_row)) as cursor:
                return list(cursor.execute("""
                    SELECT name, freq, coords, objecttype FROM vpl
                """).fetchall())

    @event(name="vplSavePersistentObject")
    async def vplSavePersistentObjects(self, server: Server, name:str, coords: dict, freq: str, objType: str):
        self.log.debug("I've received the vplSavePersistentObject event!")
        # save these details to the database
        with self.pool.connection() as conn:
            with conn.transaction():
                conn.execute("""
                    INSERT INTO vpl (name, coords, freq, objecttype) 
                    VALUES (%s, %s, %s, %s)
                """, (name, coords, freq, objType))
        return
    
    @event(name="vplGetPersistentObjects")
    async def vplGetPersistentObjects(self, server: Server, data: dict):
        data = self.get_persistent_objects()
        if not data:
            self.log.debug(f"VPL: No persistent objects in database")
            return
        for row in data:
            farp = {}
            farp.name = row[1]
            farp.freq = row[2]
            farp.coords = row[3]
            server.send_to_dcs({
                'command': 'csarUpdatePersistentData',
                'data': farp
            })
        return

    @chat_command(name="sample", roles=['DCS Admin'], help="A sample command")
    async def sample(self, server: Server, player: Player, params: list[str]):
        player.sendChatMessage("This is a sample command!")
