# Plugin "Gamemaster"
The gamemaster plugin adds commands that help you to interact with a running mission by either different kinds of messaging or setting and clearing flags.  

## Discord Commands

| Command | Parameter           | Channel                     | Role      | Description                                       |
|--------|----------------------|-----------------------------|-----------|---------------------------------------------------|
| .chat  | message              | chat-/admin-channel         | DCS       | Send a message to the DCS in-game-chat.           |
| .popup | red/blue/all message | admin-channel               | DCS Admin | Send a popup to the dedicated coalition in game.  |
| .flag  | <name> [value]       | admin-channel               | DCS Admin | Sets or clears a flag inside the running mission. |