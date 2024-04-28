-----------------------------------------------------
-- All callback commands have to go here.
-- You have to make sure, that these commands are
-- named uniquely in the DCSServerBot context.
-----------------------------------------------------
local base 	    = _G
local dcsbot    = base.dcsbot
local utils 	= base.require("DCSServerBotUtils")

function dcsbot.slotmanagement(json)
    log.write('DCSServerBot', log.DEBUG, 'slotmanagement: slotmanagement()')
    local msg = {}
    msg.command = 'slotmanagement'
    msg.message = json.message
    utils.sendBotTable(msg, json.channel)
end
