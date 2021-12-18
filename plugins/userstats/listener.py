# listener.py
import psycopg2
from contextlib import closing
from core import const, DCSServerBot, EventListener
from typing import Union


class UserStatisticsEventListener(EventListener):

    SQL_EVENT_UPDATES = {
        'takeoff': 'UPDATE statistics SET takeoffs = takeoffs + 1 WHERE mission_id = %s AND player_ucid = %s AND hop_off IS NULL',
        'landing': 'UPDATE statistics SET landings = landings + 1 WHERE mission_id = %s AND player_ucid = %s AND hop_off IS NULL',
        'eject': 'UPDATE statistics SET ejections = ejections + 1 WHERE mission_id = %s AND player_ucid = %s AND hop_off IS NULL',
        'crash': 'UPDATE statistics SET crashes = crashes + 1 WHERE mission_id = %s AND player_ucid = %s AND hop_off IS NULL',
        'pilot_death': 'UPDATE statistics SET deaths = deaths + 1 WHERE mission_id = %s AND player_ucid = %s AND hop_off IS NULL',
        'pvp': 'UPDATE statistics SET kills = kills + 1, pvp = pvp + 1 WHERE mission_id = %s AND player_ucid = %s AND hop_off IS NULL',
        'teamkill': 'UPDATE statistics SET teamkills = teamkills + 1 WHERE mission_id = %s AND player_ucid = %s AND hop_off IS NULL',
        'kill_planes': 'UPDATE statistics SET kills = kills + 1, kills_planes = kills_planes + 1 WHERE mission_id = %s AND player_ucid = %s AND hop_off IS NULL',
        'kill_helicopters': 'UPDATE statistics SET kills = kills + 1, kills_helicopters = kills_helicopters + 1 WHERE mission_id = %s AND player_ucid = %s AND hop_off IS NULL',
        'kill_ships': 'UPDATE statistics SET kills = kills + 1, kills_ships = kills_ships + 1 WHERE mission_id = %s AND player_ucid = %s AND hop_off IS NULL',
        'kill_sams': 'UPDATE statistics SET kills = kills + 1, kills_sams = kills_sams + 1 WHERE mission_id = %s AND player_ucid = %s AND hop_off IS NULL',
        'kill_ground': 'UPDATE statistics SET kills = kills + 1, kills_ground = kills_ground + 1 WHERE mission_id = %s AND player_ucid = %s AND hop_off IS NULL',
        'teamdeath': 'UPDATE statistics SET deaths = deaths - 1 WHERE mission_id = %s AND player_ucid = %s AND hop_off IS NULL',
        'deaths_pvp': 'UPDATE statistics SET deaths_pvp = deaths_pvp + 1 WHERE mission_id = %s AND player_ucid = %s AND hop_off IS NULL',
        'deaths_planes': 'UPDATE statistics SET deaths_planes = deaths_planes + 1 WHERE mission_id = %s AND player_ucid = %s AND hop_off IS NULL',
        'deaths_helicopters': 'UPDATE statistics SET deaths_helicopters = deaths_helicopters + 1 WHERE mission_id = %s AND player_ucid = %s AND hop_off IS NULL',
        'deaths_ships': 'UPDATE statistics SET deaths_ships = deaths_ships + 1 WHERE mission_id = %s AND player_ucid = %s AND hop_off IS NULL',
        'deaths_sams': 'UPDATE statistics SET deaths_sams = deaths_sams + 1 WHERE mission_id = %s AND player_ucid = %s AND hop_off IS NULL',
        'deaths_ground': 'UPDATE statistics SET deaths_ground = deaths_ground + 1 WHERE mission_id = %s AND player_ucid = %s AND hop_off IS NULL'
    }

    def __init__(self, bot: DCSServerBot):
        super().__init__(bot)
        self.statistics = {}

    async def processEvent(self, data: dict[str, Union[str, int]]) -> None:
        if (data['command'] == 'registerDCSServer') or \
                (data['server_name'] in self.statistics and data['command'] in self.registeredEvents()):
            return await getattr(self, data['command'])(data)
        else:
            return None

    # Return a player from the internal list
    # TODO: change player data handling!
    def get_player(self, server_name, id):
        df = self.bot.player_data[server_name]
        row = df[df['id'] == id]
        if not row.empty:
            return df[df['id'] == id].to_dict('records')[0]
        else:
            return None

    def getCurrentMissionID(self, server_name):
        id = -1
        conn = self.pool.getconn()
        try:
            with closing(conn.cursor()) as cursor:
                cursor.execute(
                    'SELECT id FROM missions WHERE server_name = %s AND mission_end IS NULL', (server_name,))
                if cursor.rowcount > 0:
                    id = cursor.fetchone()[0]
        except (Exception, psycopg2.DatabaseError) as error:
            self.log.exception(error)
        finally:
            self.pool.putconn(conn)
        return id

    async def registerDCSServer(self, data):
        self.statistics[data['server_name']] = data['statistics']

    async def onMissionLoadEnd(self, data):
        SQL_CLOSE_STATISTICS = 'UPDATE statistics SET hop_off = NOW() WHERE mission_id IN (SELECT id FROM missions ' \
                               'WHERE server_name = %s AND mission_end IS NULL) AND hop_off IS NULL '
        SQL_CLOSE_MISSIONS = 'UPDATE missions SET mission_end = NOW() WHERE server_name = %s AND mission_end IS NULL'
        SQL_START_MISSION = 'INSERT INTO missions (server_name, mission_name, mission_theatre) VALUES (%s, %s, %s)'
        conn = self.pool.getconn()
        try:
            with closing(conn.cursor()) as cursor:
                cursor.execute(SQL_CLOSE_STATISTICS, (data['server_name'],))
                cursor.execute(SQL_CLOSE_MISSIONS, (data['server_name'],))
                cursor.execute(SQL_START_MISSION, (data['server_name'],
                                                   data['current_mission'], data['current_map']))
                conn.commit()
        except (Exception, psycopg2.DatabaseError) as error:
            self.log.exception(error)
            conn.rollback()
        finally:
            self.pool.putconn(conn)

    async def onSimulationStop(self, data):
        conn = self.pool.getconn()
        try:
            mission_id = self.getCurrentMissionID(data['server_name'])
            with closing(conn.cursor()) as cursor:
                cursor.execute('UPDATE statistics SET hop_off = NOW() WHERE mission_id = %s AND hop_off IS NULL',
                               (mission_id,))
                cursor.execute('UPDATE missions SET mission_end = NOW() WHERE id = %s',
                               (mission_id,))
                conn.commit()
        except (Exception, psycopg2.DatabaseError) as error:
            self.log.exception(error)
            conn.rollback()
        finally:
            self.pool.putconn(conn)

    async def onPlayerChangeSlot(self, data):
        SQL_CLOSE_STATISTICS = 'UPDATE statistics SET hop_off = NOW() WHERE mission_id = %s AND player_ucid = %s AND ' \
                               'hop_off IS NULL '
        SQL_INSERT_STATISTICS = 'INSERT INTO statistics (mission_id, player_ucid, slot) VALUES (%s, %s, ' \
                                '%s) ON CONFLICT DO NOTHING '
        conn = self.pool.getconn()
        try:
            mission_id = self.getCurrentMissionID(data['server_name'])
            with closing(conn.cursor()) as cursor:
                cursor.execute(SQL_CLOSE_STATISTICS, (mission_id, data['ucid']))
                if data['side'] != const.SIDE_SPECTATOR:
                    cursor.execute(SQL_INSERT_STATISTICS, (mission_id, data['ucid'], data['unit_type']))
                conn.commit()
        except (Exception, psycopg2.DatabaseError) as error:
            self.log.exception(error)
            conn.rollback()
        finally:
            self.pool.putconn(conn)

    async def getCurrentPlayers(self, data):
        # Close statistics for players that are no longer active
        players = self.bot.player_data[data['server_name']]
        ucids = ', '.join(['"' + x + '"' for x in players[players['active'] == True]['ucid']])
        if len(players) > 0:
            conn = self.pool.getconn()
            try:
                with closing(conn.cursor()) as cursor:
                    cursor.execute(
                        'UPDATE statistics SET hop_off = NOW() WHERE player_ucid NOT IN (%s) AND mission_id = %s',
                        (ucids, self.getCurrentMissionID(data['server_name'])))
                    conn.commit()
            except (Exception, psycopg2.DatabaseError) as error:
                self.log.exception(error)
                conn.rollback()
            finally:
                self.pool.putconn(conn)

    async def disableUserStats(self, data):
        SQL_DELETE_STATISTICS = 'DELETE FROM statistics WHERE mission_id = %s'
        SQL_DELETE_MISSION = 'DELETE FROM missions WHERE id = %s'
        if data['server_name'] in self.statistics:
            del self.statistics[data['server_name']]
        conn = self.pool.getconn()
        try:
            mission_id = self.getCurrentMissionID(data['server_name'])
            with closing(conn.cursor()) as cursor:
                cursor.execute(SQL_DELETE_MISSION, (mission_id,))
                cursor.execute(SQL_DELETE_STATISTICS, (mission_id,))
                conn.commit()
        except (Exception, psycopg2.DatabaseError) as error:
            self.log.exception(error)
            conn.rollback()
        finally:
            self.pool.putconn(conn)

    async def onGameEvent(self, data):
        if data['eventName'] == 'disconnect':
            if data['arg1'] != 1:
                player = self.get_player(data['server_name'], data['arg1'])
                conn = self.pool.getconn()
                try:
                    with closing(conn.cursor()) as cursor:
                        cursor.execute('UPDATE statistics SET hop_off = NOW() WHERE mission_id = %s AND player_ucid = '
                                       '%s AND hop_off IS NULL', (self.getCurrentMissionID(data['server_name']),
                                                                  player['ucid']))
                        conn.commit()
                except (Exception, psycopg2.DatabaseError) as error:
                    self.log.exception(error)
                    conn.rollback()
                finally:
                    self.pool.putconn(conn)
        elif data['eventName'] == 'kill':
            conn = self.pool.getconn()
            try:
                with closing(conn.cursor()) as cursor:
                    # Player is not an AI
                    if data['arg1'] != -1:
                        if data['arg4'] != -1:
                            if data['arg1'] == data['arg4']:  # self kill
                                kill_type = 'self_kill'
                            elif data['arg3'] == data['arg6']:  # teamkills
                                kill_type = 'teamkill'
                            elif data['victimCategory'] in ['Planes', 'Helicopters']:  # pvp
                                kill_type = 'pvp'
                        elif data['victimCategory'] == 'Planes':
                            kill_type = 'kill_planes'
                        elif data['victimCategory'] == 'Helicopters':
                            kill_type = 'kill_helicopters'
                        elif data['victimCategory'] == 'Ships':
                            kill_type = 'kill_ships'
                        elif data['victimCategory'] == 'Air Defence':
                            kill_type = 'kill_sams'
                        elif data['victimCategory'] in ['Unarmed', 'Armor', 'Infantry' 'Fortification', 'Artillery',
                                                        'MissilesSS']:
                            kill_type = 'kill_ground'
                        else:
                            kill_type = 'kill_other'  # Static objects
                        # TODO Update database
                        player1 = self.get_player(data['server_name'], data['arg1'])
                        if kill_type in self.SQL_EVENT_UPDATES.keys():
                            cursor.execute(self.SQL_EVENT_UPDATES[kill_type],
                                           (self.getCurrentMissionID(data['server_name']), player1['ucid']))

                    # Victim is not an AI
                    if data['arg4'] != -1:
                        if data['arg1'] != -1:
                            if data['arg1'] == data['arg4']:  # self kill
                                death_type = 'self_kill'
                            elif data['arg3'] == data['arg6']:  # killed by team member - no death counted
                                death_type = 'teamdeath'
                            elif data['killerCategory'] in ['Planes', 'Helicopters']:  # pvp
                                death_type = 'deaths_pvp'
                        elif data['killerCategory'] == 'Planes':
                            death_type = 'deaths_planes'
                        elif data['killerCategory'] == 'Helicopters':
                            death_type = 'deaths_helicopters'
                        elif data['killerCategory'] == 'Ships':
                            death_type = 'deaths_ships'
                        elif data['killerCategory'] == 'Air Defence':
                            death_type = 'deaths_sams'
                        elif data['killerCategory'] in ['Armor', 'Infantry' 'Fortification', 'Artillery',
                                                        'MissilesSS']:
                            death_type = 'deaths_ground'
                        else:
                            death_type = 'other'
                        player2 = self.get_player(data['server_name'], data['arg4'])
                        if death_type in self.SQL_EVENT_UPDATES.keys():
                            cursor.execute(self.SQL_EVENT_UPDATES[death_type],
                                           (self.getCurrentMissionID(data['server_name']), player2['ucid']))
                    conn.commit()
            except (Exception, psycopg2.DatabaseError) as error:
                self.log.exception(error)
                conn.rollback()
            finally:
                self.pool.putconn(conn)
        elif data['eventName'] in ['takeoff', 'landing', 'crash', 'eject', 'pilot_death']:
            if data['arg1'] != -1:
                player = self.get_player(data['server_name'], data['arg1'])
                if data['eventName'] in self.SQL_EVENT_UPDATES.keys():
                    conn = self.pool.getconn()
                    try:
                        with closing(conn.cursor()) as cursor:
                            cursor.execute(self.SQL_EVENT_UPDATES[data['eventName']],
                                           (self.getCurrentMissionID(data['server_name']), player['ucid']))
                            conn.commit()
                    except (Exception, psycopg2.DatabaseError) as error:
                        self.log.exception(error)
                        conn.rollback()
                    finally:
                        self.pool.putconn(conn)
        else:
            self.log.debug('Unhandled event: ' + data['eventName'])
        return None