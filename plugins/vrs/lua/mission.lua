-----------------------------------------------------
-- VRS plugin mission-state RPC methods.
-- Defines mission -> bot calls under dcsbot.*
-----------------------------------------------------
local base = _G
dcsbot     = base.dcsbot

-- Post a pre-encoded JSON payload to a Discord webhook.
--
-- As of 2026-05-15 the contract is `(webhookKey, payload)` -- pass a
-- logical key like "admin" or "bugReport" and the bot resolves the URL
-- from config/plugins/vrs.yaml. Mission code should never see the raw URL.
--
-- A backwards-compat shim still accepts a raw https:// URL as the first
-- arg so a mismatched DCS/bot restart window doesn't drop posts. Legacy
-- callers get a WARN on the bot side so they're easy to find in Seq.
--
--   webhookKey  Logical key ("admin", "messages", "bugReport", ...) or
--               a raw https:// URL (legacy path).
--   payload     Pre-encoded JSON string (the bot does NOT re-encode).
--
-- The bot is a dumb pipe -- whatever payload you send goes directly to
-- Discord. Mission code is responsible for JSON-encoding its own embed.
function dcsbot.sendDiscordWebhook(webhookKey, payload)
    if not webhookKey or webhookKey == "" or not payload or payload == "" then
        env.warning("DCSServerBot - VRS: sendDiscordWebhook missing key/url or payload")
        return
    end
    local msg = {
        command = 'sendDiscordWebhook',
        payload = payload,
    }
    if string.sub(webhookKey, 1, 8) == "https://" then
        msg.url = webhookKey
    else
        msg.key = webhookKey
    end
    dcsbot.sendBotTable(msg)
end

-- Open an in-game bug report capture window for the player who triggered
-- the F10 menu. Mission Lua side passes a pre-encoded JSON payload (built
-- by VRS.players.bugReport) containing auto-state + the recent-errors ring
-- buffer; the bot opens a 120s rolling chat-capture window keyed on the
-- player UCID, then posts the Discord embed when the timer expires.
--
--   payloadJson  Pre-encoded JSON string. Bot decodes; mission Lua owns
--                the shape (see plugins/vrs/listener.py startBugReport).
function dcsbot.startBugReport(payloadJson)
    if not payloadJson or payloadJson == "" then
        env.warning("DCSServerBot - VRS: startBugReport missing payload")
        return
    end
    local msg = {
        command = 'startBugReport',
        payload = payloadJson,
    }
    dcsbot.sendBotTable(msg)
end

env.info("DCSServerBot - VRS: mission.lua loaded.")
