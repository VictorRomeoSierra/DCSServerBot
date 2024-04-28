from core import EventListener, Server, event, chat_command, Player
import ruamel.yaml


class SlotManagementEventListener(EventListener):
    """
    A class where your DCS events will be handled.

    Methods
    -------
    registerDCSServer(data)
        Called on registration of any DCS server.

    slotmanagement(data)
        Called whenever ".slotmanagement" is called in discord (see commands.py).
    """

    @event(name="registerDCSServer")
    async def registerDCSServer(self, server: Server, data: dict) -> None:
        self.log.debug(f"I've received a registration event from server {server.name}!")

    @event(name="save")
    async def save(self, server: Server, data: dict):
        self.log.debug("I've received the save event!")

        group = json.loads(data['group'])
        position = json.loads(data['position'])
        # construct the necessary replace logic for MizEdit
        yaml = ruamel.yaml.YAML()
        # yaml.preserve_quotes = True
        with open('slots.yaml') as fp:
            data = yaml.load(fp)
        for elem in data:
            if elem['for-each'] == 'sense2':
                elem['value'] = 1234
                break  # no need to iterate further
        yaml.dump(data, sys.stdout)

        return data

    @chat_command(name="slotmanagement", roles=['DCS Admin'], help="A slotmanagement command")
    async def slotmanagement(self, server: Server, player: Player, params: list[str]):
        player.sendChatMessage("This is a slotmanagement command!")
