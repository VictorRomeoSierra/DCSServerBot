-----------------------------------------------------
-- All callback commands have to go here.
-- You have to make sure, that these commands are
-- named uniquely in the DCSServerBot context.
-----------------------------------------------------
local base 	    = _G
local dcsbot    = base.dcsbot
local utils 	= base.require("DCSServerBotUtils")

function dcsbot.vplSendPersistentObjects(json)
    log.write('DCSServerBot', log.DEBUG, 'VPL: vplSendPersistentObjects()')
    local script = 'dcsbot._vplSendPersistentObjects(' .. utils.basicSerialize(playerName) .. ',' ..  utils.basicSerialize(typeName) .. ',' .. utils.basicSerialize(block) .. ')'
    net.dostring_in('mission', 'a_do_script(' .. utils.basicSerialize(script) .. ')')
end
