-----------------------------------------------------
-- VRS Patreon plugin callbacks (GameGUI hook state).
-- Bootstraps the mission.lua side at mission load.
-----------------------------------------------------
local base    = _G
local utils   = base.require("DCSServerBotUtils")
local patreon = patreon or {}

function patreon.onMissionLoadEnd()
    log.write('DCSServerBot', log.DEBUG, 'Patreon: onMissionLoadEnd()')
    utils.loadScript('DCSServerBot.lua')
    utils.loadScript('patreon/mission.lua')
end

Sim.setUserCallbacks(patreon)
