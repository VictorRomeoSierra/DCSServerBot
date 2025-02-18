-----------------------------------------------------
-- All callback commands have to go here.
-- You have to make sure, that these commands are
-- named uniquely in the DCSServerBot context.
-----------------------------------------------------
local base 	    = _G
local dcsbot    = base.dcsbot
local utils 	= base.require("DCSServerBotUtils")

function dcsbot.csarUpdatePersistentData(json)
    log.write('DCSServerBot', log.DEBUG, 'CSAR: csarUpdatePersistentData() (commands.lua)')
    local script = 'dcsbot._csarUpdatePersistentData(' .. utils.basicSerialize(json.data) .. ')'
    net.dostring_in('mission', 'a_do_script(' .. utils.basicSerialize(script) .. ')')
end

function dcsbot.csarSetLives(json)
    log.write('DCSServerBot', log.DEBUG, 'CSAR: csarSetLives() (commands.lua)')
    local script = 'dcsbot._csarSetLives(' .. utils.basicSerialize(json.data) .. ')'
    net.dostring_in('mission', 'a_do_script(' .. utils.basicSerialize(script) .. ')')
end

function dcsbot.csarBlockSlot(json)
    log.write('DCSServerBot', log.DEBUG, 'CSAR: csarBlockSlot() (commands.lua)')
    local script = 'dcsbot._blockSlot(' .. utils.basicSerialize(json.playerName) .. ',' ..  utils.basicSerialize(json.typeName) .. ',' .. utils.basicSerialize(json.block) .. ')'
    net.dostring_in('mission', 'a_do_script(' .. utils.basicSerialize(script) .. ')')
end

function dcsbot.csarSetUserDiscord(json)
    log.write('DCSServerBot', log.DEBUG, 'CSAR: csarSetUserDiscord() (commands.lua)')
    local script = 'dcsbot._setUserDiscord(' .. utils.basicSerialize(json.name) .. ',' ..  utils.basicSerialize(json.discord) .. ')'
    net.dostring_in('mission', 'a_do_script(' .. utils.basicSerialize(script) .. ')')
end

log.write('DCSServerBot', log.DEBUG, "DCSServerBot - CSAR: commands.lua loaded.")