local base		= _G
dcsbot 			= base.dcsbot

function dcsbot.blockSlot(playerName, typeName, block)
  if playerName and typeName then
      local msg = {}
      msg.command = 'blockSlot'
      msg.playerName = playerName
      msg.typeName = typeName
      msg.block = block
      utils.sendBotTable(msg)
  end
end