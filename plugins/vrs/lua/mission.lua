-----------------------------------------------------
-- VRS plugin mission-state RPC methods.
-- Defines mission -> bot calls under dcsbot.*
-----------------------------------------------------
local base = _G
dcsbot     = base.dcsbot

-- Post a pre-encoded JSON payload to a Discord webhook URL.
-- Replaces the legacy JAPI.cont.postDiscord call path from the JSB era.
-- The bot performs the actual HTTPS POST in plugins/vrs/listener.py and
-- logs status codes via DCSServerBot's logger (filterable in Seq).
--
--   url      Full Discord webhook URL (e.g. https://discord.com/api/webhooks/...)
--   payload  Pre-encoded JSON string (the bot does NOT re-encode).
--
-- Mission code is responsible for JSON-encoding its own embed payload. The
-- bot is a dumb pipe -- whatever payload you send goes directly to Discord.
function dcsbot.sendDiscordWebhook(url, payload)
    if not url or url == "" or not payload or payload == "" then
        env.warning("DCSServerBot - VRS: sendDiscordWebhook missing url or payload")
        return
    end
    local msg = {
        command = 'sendDiscordWebhook',
        url     = url,
        payload = payload,
    }
    dcsbot.sendBotTable(msg)
end

env.info("DCSServerBot - VRS: mission.lua loaded.")
