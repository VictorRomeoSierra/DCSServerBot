# listener.py
import asyncio
from typing import List, Union, TypeVar


class EventListener:

    def __init__(self, plugin):
        self.plugin = type(self).__module__.split('.')[-2]
        self.bot = plugin.bot
        self.log = plugin.log
        self.pool = plugin.pool
        self.config = plugin.config
        self.globals = plugin.globals
        self.locals = plugin.locals
        self.registered = False
        self.loop = asyncio.get_event_loop()

    def registeredEvents(self) -> List[str]:
        return [m for m in dir(self) if m not in dir(EventListener) and not m.startswith('_')]

    async def processEvent(self, data: dict[str, Union[str, int]]) -> None:
        # ignore any other events until the server is registered
        if data['command'] == 'registerDCSServer':
            self.registered = True
        if self.registered and data['command'] in self.registeredEvents():
            return await getattr(self, data['command'])(data)
        else:
            return None


TEventListener = TypeVar("TEventListener", bound=EventListener)
