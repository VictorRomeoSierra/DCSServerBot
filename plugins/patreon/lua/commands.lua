-----------------------------------------------------
-- VRS Patreon plugin hook-env bridge.
-- Bot listener fires updatePatronTier with {ucid, tier};
-- we resolve UCID -> player name (mission Lua identifies
-- players by name) and forward to the mission-side cache.
-----------------------------------------------------
local base   = _G
local utils  = base.require("DCSServerBotUtils")
local dcsbot = base.dcsbot

-- internal, do not use inside of missions unless you know what you are doing!
function dcsbot.updatePatronTier(json)
    log.write('DCSServerBot', log.DEBUG, 'Patreon: updatePatronTier()')

    local name
    local plist = net.get_player_list()
    for i = 2, #plist do
        if (net.get_player_info(plist[i], 'ucid') == json.ucid) then
            name = net.get_player_info(plist[i], 'name')
            break
        end
    end
    if name then
        -- tier may be nil (patron status cleared); serialize as Lua nil literal.
        local tier_arg = (json.tier == nil) and 'nil' or tostring(json.tier)
        local script = 'dcsbot._setPatronTier(' ..
            utils.basicSerialize(name) .. ', ' .. tier_arg .. ')'
        net.dostring_in('mission', 'a_do_script(' .. utils.basicSerialize(script) .. ')')
    end
end

log.write('DCSServerBot', log.DEBUG, "DCSServerBot - Patreon: commands.lua loaded.")
