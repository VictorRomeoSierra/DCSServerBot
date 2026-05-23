import discord

from core import EventListener, Server, event
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .commands import Patreon


def _role_matches(role_value, member_role_ids: set[int],
                  member_role_names: set[str]) -> bool:
    """A configured `role` entry matches a member when it equals a role ID
    they hold (int or numeric string) OR a role name they hold (string)."""
    if isinstance(role_value, int):
        return role_value in member_role_ids
    if isinstance(role_value, str):
        if role_value.isnumeric():
            return int(role_value) in member_role_ids
        return role_value in member_role_names
    return False


def resolve_tier(member: discord.Member,
                 tiers_config: list[dict]) -> Optional[int]:
    """Return the highest-numbered configured tier the member matches via
    any of their Discord roles, or None if no configured role matches.

    `tiers_config` is the validated list from plugins/patreon/schemas/
    patreon_schema.yaml -- entries are {tier: int, role: str|int, label?: str}.
    """
    if not member or not tiers_config:
        return None
    member_role_ids = {r.id for r in member.roles}
    member_role_names = {r.name for r in member.roles}
    best: Optional[int] = None
    for entry in tiers_config:
        tier_n = entry.get('tier')
        role_value = entry.get('role')
        if tier_n is None or role_value is None:
            continue
        if _role_matches(role_value, member_role_ids, member_role_names):
            if best is None or tier_n > best:
                best = tier_n
    return best


class PatreonEventListener(EventListener["Patreon"]):
    """Listener for VRS Patreon plugin.

    On player connect, resolves the player's highest-matching configured
    Patreon tier (via Discord roles granted by Patreon's native integration)
    and pushes it down to the mission so mission-side perks can key off the
    tier. Players whose Discord isn't linked get no tier -- expected.
    """

    @event(name="onPlayerStart")
    async def onPlayerStart(self, server: Server, data: dict) -> None:
        if data.get('id') == 1 or 'ucid' not in data:
            return
        player = server.get_player(ucid=data['ucid'])
        if not player or not player.member:
            return
        config = self.plugin.get_config(server) or {}
        tiers_config = config.get('tiers')
        if not tiers_config:
            return
        tier = resolve_tier(player.member, tiers_config)
        if tier is None:
            return
        await server.send_to_dcs({
            'command': 'updatePatronTier',
            'ucid': player.ucid,
            'tier': tier,
        })
        self.log.debug(
            f"Patreon: pushed tier={tier} for {player.name} "
            f"(ucid={player.ucid}, server={server.name})"
        )
