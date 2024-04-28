local utils 	= base.require("DCSServerBotUtils")
local config	= base.require("DCSServerBotConfig")

local slotmanagement = {}

-- Overwrite any Hook unction in here that you want to handle.
-- Make sure that sending a message back to the bot has to be unique!
function slotmanagement.save(group, position)
  log.write('DCSServerBot', log.DEBUG, 'slotmanagement: save()')
	local msg = {}
	msg.command = 'save'
	msg.group = group
	msg.position = net.lua2json(position)
	utils.sendBotTable(msg)
end

DCS.setUserCallbacks(slotmanagement)