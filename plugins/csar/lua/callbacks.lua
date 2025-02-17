local base 	        = _G
local utils         = base.require("DCSServerBotUtils")
local csar          = csar or {}

function csar.onMissionLoadEnd()
    log.write('DCSServerBot', log.DEBUG, 'CSAR: onMissionLoadEnd() callbacks.lua')
    utils.loadScript('DCSServerBot.lua')
    utils.loadScript('csar/mission.lua')
    -- net.dostring_in('mission', 'a_do_script("dofile(\\"' .. lfs.writedir():gsub('\\', '/') .. 'Scripts/net/DCSServerBot/DCSServerBot.lua' .. '\\")")')
    -- net.dostring_in('mission', 'a_do_script("dofile(\\"' .. lfs.writedir():gsub('\\', '/') .. 'Scripts/net/DCSServerBot/csar/mission.lua' .. '\\")")')
end

DCS.setUserCallbacks(csar)