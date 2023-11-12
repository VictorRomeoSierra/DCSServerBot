-----------------------------------------------------
-- All callback commands have to go here.
-- You have to make sure, that these commands are
-- named uniquely in the DCSServerBot context.
-----------------------------------------------------
local base 	    = _G
local dcsbot    = base.dcsbot
local utils 	= base.require("DCSServerBotUtils")

-- function dcsbot.sample(json)
--     log.write('DCSServerBot', log.DEBUG, 'Sample: sample()')
--     local msg = {}
--     msg.command = 'sample'
--     msg.message = json.message
--     utils.sendBotTable(msg, json.channel)
-- end

function dcsbot._blockSlot(playerName, typeName, block)
    log.write('DCSServerBot', log.DEBUG, 'Slotblock: _blockSlot() (commands.lua)')
    -- log.write('DCSServerBot', log.DEBUG, 'CSAR: data:' .. utils.basicSerialize(json.data))
    local script = 'slotblock.blockSlot(' .. utils.basicSerialize(playerName) .. ',' ..  utils.basicSerialize(typeName) .. ',' .. utils.basicSerialize(block) .. ')'  --, ' .. json.points .. '
    net.dostring_in('mission', 'a_do_script(' .. utils.basicSerialize(script) .. ')')
end