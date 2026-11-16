import asyncio
import os
import re

import discord

from core import Plugin, Group, Server, Status, Coalition, utils
from discord import app_commands
from services.bot import DCSServerBot

from .listener import VrsEventListener

WARN_TIMES = (60, 30, 10)

# reset_campaign handshake. VRS.persistence.armCampaignReset sets this DCS user
# flag only after the reset is saved to VRSPflags.lua; the command polls it
# (gamemaster getFlag) before touching the DCS process. do_script is
# fire-and-forget, and a shutdown straight after it lost the arm on 2026-11-15.
ARMED_FLAG = "VRS_CAMPAIGN_RESET_ARMED"
ARM_CONFIRM_TIMEOUT_S = 20
# Graceful-shutdown budget. The node's own graceful path can run ~240s
# (180s exit wait + 30s + 30s terminate), longer than the master's 180s
# send_to_node_sync timeout in ServerProxy.shutdown -- the collision that
# stranded Test on 2026-07-23. Cap it well below 180s, then force-kill.
GRACEFUL_SHUTDOWN_TIMEOUT_S = 120


async def _confirm_reset_armed(server: Server) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + ARM_CONFIRM_TIMEOUT_S
    while loop.time() < deadline:
        try:
            data = await server.send_to_dcs_sync({"command": "getFlag", "flag": ARMED_FLAG}, timeout=5)
        except (TimeoutError, asyncio.TimeoutError):
            data = None
        try:
            if data and float(data.get('value') or 0) >= 1:
                return True
        except (TypeError, ValueError):
            pass
        await asyncio.sleep(1)
    return False

# VRS .miz naming convention: VRS_<Theatre>_<Version>.miz
# Example: "VRS_Syria_0.48.6.miz" -> theatre "Syria"
# Used by /vrs reset_campaign to flag a theatre change in the confirm
# dialog. Returns None when the filename doesn't match the convention.
_THEATRE_RE = re.compile(r'^VRS_([^_]+)_', re.IGNORECASE)


def _theatre_from_miz_name(path_or_name) -> str | None:
    if not path_or_name:
        return None
    name = os.path.basename(str(path_or_name))
    m = _THEATRE_RE.match(name)
    return m.group(1) if m else None


def _lua_quote(s: str) -> str:
    """Wrap a Python string as a Lua string literal. Escapes backslash, double
    quote, and the standard control characters. UTF-8 bytes pass through as-is
    (Lua strings are byte sequences)."""
    return (
        '"'
        + s.replace('\\', '\\\\')
            .replace('"', '\\"')
            .replace('\n', '\\n')
            .replace('\r', '\\r')
        + '"'
    )


async def _rollback_version_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    """Suggest semver release tags from the selected server's GitHub
    extension. Resolves the same `server` namespace value the user
    just picked, mirroring how mission_autocomplete works.

    Module-level (not nested) because the `@app_commands.autocomplete`
    decorator on Vrs.rollback resolves this name at class-body
    evaluation time -- the function must already exist when the class
    is parsed.
    """
    log = interaction.client.log
    namespace_server = getattr(interaction.namespace, 'server', None)
    log.info(f"rollback_autocomplete: entry current='{current}' ns_server='{namespace_server}'")
    if not await interaction.command._check_can_run(interaction):
        log.info("rollback_autocomplete: _check_can_run returned False")
        return []
    try:
        server: Server = await utils.ServerTransformer().transform(
            interaction, namespace_server)
        if not server:
            log.info("rollback_autocomplete: server did not resolve")
            return []
        ext_summary = [
            f"{type(e).__name__}(name={getattr(e, 'name', '?')})"
            for e in server.extensions.values()
        ]
        log.info(f"rollback_autocomplete: server={server.name} extensions={ext_summary}")
        for ext in server.extensions.values():
            if ext.name == 'GitHub' and hasattr(ext, 'list_release_tags'):
                tags = await ext.list_release_tags()
                log.info(f"rollback_autocomplete: ext.list_release_tags() returned {tags}")
                return [
                    app_commands.Choice(name=t, value=t)
                    for t in tags
                    if not current or current in t
                ][:25]
        log.info("rollback_autocomplete: no extension matched GitHub+list_release_tags")
        return []
    except Exception as ex:
        log.exception(ex)
        return []


class Vrs(Plugin[VrsEventListener]):
    """VRS-specific admin commands (campaign reset, etc.) and mission RPC
    handlers (Discord webhook posting)."""

    def __init__(self, bot: DCSServerBot, listener: type[VrsEventListener]):
        super().__init__(bot, listener)

    group = Group(name="vrs", description="VRS server admin commands")

    @group.command(name="reset_campaign",
                   description="Reset the campaign and restart the server (optionally switching missions)")
    @app_commands.guild_only()
    @utils.app_has_role('DCS Admin')
    @app_commands.rename(mission_id="mission")
    @app_commands.autocomplete(mission_id=utils.mission_autocomplete)
    @app_commands.describe(reason="Optional reason text shown in the campaign-reset embed and audit log")
    @app_commands.describe(mission_id="Optional: pick a different mission to load on the fresh campaign")
    async def reset_campaign(
        self,
        interaction: discord.Interaction,
        server: app_commands.Transform[
            Server, utils.ServerTransformer(status=[Status.RUNNING, Status.PAUSED])
        ],
        reason: str | None = None,
        mission_id: int | None = None,
    ):
        if server.status not in (Status.RUNNING, Status.PAUSED):
            await interaction.response.send_message(
                f"Server {server.name} is not running.", ephemeral=True
            )
            return

        # Resolve the selected mission if one was specified. Validate index
        # against the current mission list before we go anywhere near the
        # destructive path. Theatre comparison is best-effort via the VRS
        # naming convention; if either filename doesn't match, the theatre-
        # change warning is silently skipped (no false positives).
        selected_mission_path = None
        selected_theatre = None
        current_theatre = None
        if mission_id is not None:
            mission_list = await server.getMissionList()
            if mission_id < 0 or mission_id >= len(mission_list):
                await interaction.response.send_message(
                    f"Mission index {mission_id} out of range (have {len(mission_list)} missions).",
                    ephemeral=True
                )
                return
            selected_mission_path = mission_list[mission_id]
            selected_theatre = _theatre_from_miz_name(selected_mission_path)

            current_filename = None
            try:
                if server.current_mission is not None:
                    current_filename = server.current_mission.filename
            except AttributeError:
                pass
            current_theatre = _theatre_from_miz_name(current_filename)

        warn_times = sorted(WARN_TIMES, reverse=True)
        lead_time = warn_times[0]

        # yn_question puts `question` into the embed title (Discord caps at
        # 256 chars) and `message` into the description (4096 cap). Keep the
        # title short; put the verbose detail + mission/theatre info in the
        # description.
        confirm_title = f"Reset the campaign on {server.name}?"
        confirm_details = (
            f"Players will get a **{lead_time}-second** warning, then the server "
            f"will restart. All previous progress, base ownership, salvage jobs, "
            f"and CSAR state will be cleared."
        )
        if selected_mission_path:
            confirm_details += (
                f"\n\nNew mission: **{os.path.basename(selected_mission_path)}**"
            )
        if current_theatre and selected_theatre \
                and current_theatre.lower() != selected_theatre.lower():
            confirm_details += (
                f"\n\n**WARNING: THEATRE CHANGE** -- "
                f"{current_theatre} -> {selected_theatre}"
            )

        if not await utils.yn_question(interaction, confirm_title, message=confirm_details):
            await interaction.followup.send("Cancelled.", ephemeral=True)
            return

        reason_str = (reason or "").strip()

        async def _warn(secs_left: int):
            await asyncio.sleep(lead_time - secs_left)
            popup = f"Campaign reset in {secs_left} second{'s' if secs_left != 1 else ''} - land or eject!"
            if reason_str:
                popup += f"\nReason: {reason_str}"
            await server.sendPopupMessage(Coalition.ALL, popup)

        ack = (
            f"Campaign reset scheduled on **{server.name}**. Players get a "
            f"{lead_time}-second warning; the server restarts once the mission "
            f"confirms the reset is saved."
        )
        if reason_str:
            ack += f"\nReason: {reason_str}"
        if selected_mission_path:
            ack += f"\nNew mission: {os.path.basename(selected_mission_path)}"
        await interaction.followup.send(ack, ephemeral=utils.get_ephemeral(interaction))

        await utils.run_parallel_nofail(*(_warn(t) for t in warn_times))

        script = f"VRS.persistence.armCampaignReset({_lua_quote(reason_str)})"
        await server.send_to_dcs({"command": "do_script", "script": script})

        # Nothing below runs until the mission confirms the reset is saved.
        # Unconfirmed = abort with the server untouched, never a restart that
        # silently keeps the old campaign.
        if not await _confirm_reset_armed(server):
            await server.sendPopupMessage(Coalition.ALL, "Campaign reset cancelled - the server stays up.")
            await interaction.followup.send(
                f"Campaign reset ABORTED on **{server.name}**: the mission did not confirm the reset "
                f"within {ARM_CONFIRM_TIMEOUT_S}s (flag `{ARMED_FLAG}`). The server was left running "
                f"and nothing was reset.",
                ephemeral=utils.get_ephemeral(interaction)
            )
            await self.bot.audit(f"reset campaign ABORTED on {server.name} (arm not confirmed)",
                                 user=interaction.user, server=server)
            return

        # If a different mission was selected, set the start index BEFORE
        # the process cycle so startup boots into the new .miz.
        # setStartIndex is 1-indexed per the DCSServerBot contract.
        if mission_id is not None:
            await server.setStartIndex(mission_id + 1)

        # Full DCS process cycle (not just `server.restart`, which only reloads
        # the mission). shutdown + startup re-runs the bot's plugin-Lua-glue
        # install (_install_plugin copies plugins/<name>/lua/* into Saved Games),
        # so any pushed mission-Lua hotfixes plus updated bot plugin glue take
        # effect on the post-reset boot. Adds ~30s of downtime vs mission reload.
        #
        # Graceful first, bounded by GRACEFUL_SHUTDOWN_TIMEOUT_S so the master's
        # 180s RPC timeout can't fire mid-cycle (the 2026-07-23 strand), then
        # force-kill. The arm is already confirmed on disk, so the fallback can
        # no longer lose it. The finally guarantees startup still runs.
        try:
            try:
                await asyncio.wait_for(server.shutdown(), timeout=GRACEFUL_SHUTDOWN_TIMEOUT_S)
            except (TimeoutError, asyncio.TimeoutError):
                self.log.warning(f"reset_campaign: graceful shutdown of {server.name} exceeded "
                                 f"{GRACEFUL_SHUTDOWN_TIMEOUT_S}s; forcing")
                await server.shutdown(force=True)
        finally:
            await server.startup(modify_mission=True)

        audit_msg = f"reset campaign on {server.name} (DCS cycled)"
        if selected_mission_path:
            audit_msg += f" -- new mission: {os.path.basename(selected_mission_path)}"
        if reason_str:
            audit_msg += f" (reason: {reason_str})"
        await self.bot.audit(audit_msg, user=interaction.user, server=server)

    @group.command(name="rollback",
                   description="Roll back the XSAF code on this server to a previous release tag")
    @app_commands.guild_only()
    @utils.app_has_role('DCS Admin')
    @app_commands.autocomplete(version=_rollback_version_autocomplete)
    @app_commands.describe(version="Release tag to roll back to (e.g. 1.2.1)")
    @app_commands.describe(reason="Optional reason text shown in player warnings + audit log")
    async def rollback(
        self,
        interaction: discord.Interaction,
        server: app_commands.Transform[
            Server, utils.ServerTransformer(status=[Status.RUNNING, Status.PAUSED, Status.STOPPED])
        ],
        version: str,
        reason: str | None = None,
    ):
        """Roll the server's XSAF clone back to a tagged release and
        restart the server on the rolled-back code. Mirrors reset_campaign's
        warning + audit pattern; the destructive action is `git reset
        --hard refs/tags/<version>` inside the GitHub extension's target
        clone (typically E:\\XSAF on Prod).

        Tag list is filtered to bare semver X.Y.Z per the XSAF
        release-tagging spec; backup/save-point tags are excluded as
        rollback targets.
        """
        # Find the GitHub extension on this server. There may be more
        # than one extension configured but only one is named "GitHub"
        # per extensions/github/extension.py.
        github_ext = None
        for ext in server.extensions.values():
            if ext.name == 'GitHub':
                github_ext = ext
                break
        if github_ext is None:
            await interaction.response.send_message(
                f"Server {server.name} has no GitHub extension configured -- "
                f"nothing to roll back.",
                ephemeral=True
            )
            return

        # Validate the requested tag is real before warning anyone.
        try:
            available_tags = await github_ext.list_release_tags()
        except Exception as ex:
            await interaction.response.send_message(
                f"Couldn't fetch release tags from `{github_ext.target}`: `{ex}`",
                ephemeral=True
            )
            return

        if version not in available_tags:
            recent = ", ".join(available_tags[:5]) if available_tags else "(none found)"
            await interaction.response.send_message(
                f"Tag `{version}` not found in `{github_ext.repo}`.\n"
                f"Recent semver tags: {recent}",
                ephemeral=True
            )
            return

        warn_times = sorted(WARN_TIMES, reverse=True)
        lead_time = warn_times[0]

        confirm_title = f"Roll back {server.name} to {version}?"
        confirm_details = (
            f"This will:\n"
            f"1. Warn players, then shut down `{server.name}`.\n"
            f"2. `git reset --hard refs/tags/{version}` in `{github_ext.target}`.\n"
            f"3. Restart the server with the rolled-back code.\n\n"
            f"Players get a **{lead_time}-second** warning."
        )
        reason_str = (reason or "").strip()
        if reason_str:
            confirm_details += f"\n\nReason: **{reason_str}**"

        if not await utils.yn_question(interaction, confirm_title, message=confirm_details):
            await interaction.followup.send("Cancelled.", ephemeral=True)
            return

        async def _warn(secs_left: int):
            await asyncio.sleep(lead_time - secs_left)
            popup = (
                f"Rollback to {version} in {secs_left} "
                f"second{'s' if secs_left != 1 else ''} - land or eject!"
            )
            if reason_str:
                popup += f"\nReason: {reason_str}"
            await server.sendPopupMessage(Coalition.ALL, popup)

        ack = (
            f"Rollback to **{version}** armed on **{server.name}**. "
            f"Server will restart in {lead_time} seconds."
        )
        if reason_str:
            ack += f"\nReason: {reason_str}"
        await interaction.followup.send(ack, ephemeral=utils.get_ephemeral(interaction))

        await utils.run_parallel_nofail(*(_warn(t) for t in warn_times))

        # Full process cycle so post-reset hook + plugin Lua reinstall
        # picks up the rolled-back state. Same justification as
        # reset_campaign. force=True avoids the same 180s graceful-exit / RPC
        # timeout collision that would otherwise strand a busy server down
        # mid-rollback.
        try:
            await server.shutdown(force=True)
        except Exception as ex:
            # Shutdown failed -- do NOT git reset the clone with DCS possibly
            # still holding files open. Bring the server back on the current
            # code and bail without rolling back.
            await server.startup(modify_mission=True)
            await interaction.followup.send(
                f"Rollback ABORTED: shutdown failed (`{ex}`). "
                f"Server restarted on the current code; no rollback performed.",
                ephemeral=False
            )
            return

        try:
            old_sha, new_sha = await github_ext.reset_to_ref(f"refs/tags/{version}")
        except Exception as ex:
            # Restore the server on whatever code is currently there.
            # The extension's update() will run again on next mission load.
            await server.startup(modify_mission=True)
            await interaction.followup.send(
                f"Rollback FAILED at `git reset`: `{ex}`. "
                f"Server has been restarted on the previous code.",
                ephemeral=False
            )
            return

        await server.startup(modify_mission=True)

        audit_msg = (
            f"rolled back {server.name} to {version} "
            f"({old_sha[:8]} -> {new_sha[:8]})"
        )
        if reason_str:
            audit_msg += f" (reason: {reason_str})"
        await self.bot.audit(audit_msg, user=interaction.user, server=server)


async def setup(bot: DCSServerBot):
    await bot.add_cog(Vrs(bot, VrsEventListener))
