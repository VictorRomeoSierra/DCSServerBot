-----------------------------------------------------
-- VRS Patreon plugin mission-side cache.
-- Populated by the hook env via dcsbot._setPatronTier when
-- the bot resolves a player's Discord roles on connect.
-----------------------------------------------------
local base = _G
dcsbot     = base.dcsbot

local _tiers = {}

-- Don't call this function, it's for internal use only!
function dcsbot._setPatronTier(name, tier)
    _tiers[name] = tier
end

function dcsbot.getPatronTier(name)
    return _tiers[name]
end

function dcsbot.listPatronTiers()
    local list = {}
    for name, tier in pairs(_tiers) do
        list[#list+1] = {name = name, tier = tier}
    end
    return list
end

env.info("DCSServerBot - Patreon: mission.lua loaded.")
