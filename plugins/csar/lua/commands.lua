-----------------------------------------------------
-- All callback commands have to go here.
-- You have to make sure, that these commands are
-- named uniquely in the DCSServerBot context.
-----------------------------------------------------
local base 	    = _G
local dcsbot    = base.dcsbot
-- local utils 	= base.require("DCSServerBotUtils")

local function basicSerialize(s)
	if s == nil then
		return "\"\""
	else
		if ((type(s) == 'number') or (type(s) == 'boolean') or (type(s) == 'function') or (type(s) == 'table') or (type(s) == 'userdata') ) then
			return tostring(s)
		elseif type(s) == 'string' then
			return string.format('%q', s)
		end
  end
end

function dcsbot.csarUpdatePersistentData(json)
    log.write('DCSServerBot', log.DEBUG, 'CSAR: csarUpdatePersistentData() (commands.lua)')
    local script = 'dcsbot._csarUpdatePersistentData(' .. basicSerialize(json.data) .. ')'
    net.dostring_in('mission', 'a_do_script(' .. basicSerialize(script) .. ')')
end

function dcsbot.csarSetLives(json)
    log.write('DCSServerBot', log.DEBUG, 'CSAR: csarSetLives() (commands.lua)')
    local script = 'dcsbot._csarSetLives(' .. basicSerialize(json.data) .. ')'
    net.dostring_in('mission', 'a_do_script(' .. basicSerialize(script) .. ')')
end

function dcsbot.csarBlockSlot(json)
    log.write('DCSServerBot', log.DEBUG, 'CSAR: csarBlockSlot() (commands.lua)')
    local script = 'dcsbot._blockSlot(' .. basicSerialize(json.playerName) .. ',' ..  basicSerialize(json.typeName) .. ',' .. basicSerialize(json.block) .. ')'
    net.dostring_in('mission', 'a_do_script(' .. basicSerialize(script) .. ')')
end

function dcsbot.csarSetUserDiscord(json)
    log.write('DCSServerBot', log.DEBUG, 'CSAR: csarSetUserDiscord() (commands.lua)')
    local script = 'dcsbot._setUserDiscord(' .. basicSerialize(json.name) .. ',' ..  basicSerialize(json.discord) .. ')'
    net.dostring_in('mission', 'a_do_script(' .. basicSerialize(script) .. ')')
end

log.write('DCSServerBot', log.DEBUG, "DCSServerBot - CSAR: commands.lua loaded.")