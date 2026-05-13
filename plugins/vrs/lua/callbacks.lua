-----------------------------------------------------
-- VRS plugin callbacks (GameGUI hook state).
-- Bootstraps the mission.lua side at mission load.
-----------------------------------------------------
local base    = _G
local utils   = base.require("DCSServerBotUtils")
local vrs     = vrs or {}

function vrs.onMissionLoadEnd()
    log.write('DCSServerBot', log.DEBUG, 'VRS: onMissionLoadEnd()')
    utils.loadScript('DCSServerBot.lua')
    utils.loadScript('vrs/mission.lua')
end

Sim.setUserCallbacks(vrs)
