"""Shared, in-process record of recent server restarts.

Lets VRS alerting tell a restart-driven mass player-drop apart from an
organic one. A server restart (scheduled, admin, or vote) fires onPlayerStop
for every player at once, which otherwise false-trips the disconnect-storm
alert (Signal 2) and the on-call merge nudge.

Written by the vrs plugin (onSimulationStop / onVotePassed); read by the vrs
merge-nudge gate and the restapi /alert/enrich relay. All three run in the
master bot process, so a module-level dict is genuinely shared state -- no IPC.
"""
import time

# instance.name -> monotonic timestamp of the most recent restart/stop.
_restarts: dict[str, float] = {}

# How long after a restart a player-drop is still treated as restart-driven.
# Must comfortably exceed Signal 2's 2-minute grouping window plus Seq's
# evaluation lag before the enricher sees the fire.
DEFAULT_WINDOW_SECONDS = 300.0


def mark_restart(instance_name: str) -> None:
    if instance_name:
        _restarts[instance_name] = time.monotonic()


def recent_restart(instance_name: str | None = None,
                   within_secs: float = DEFAULT_WINDOW_SECONDS) -> bool:
    """True if a restart happened within the window -- for the given instance,
    or for any instance when instance_name is None."""
    now = time.monotonic()
    if instance_name is not None:
        ts = _restarts.get(instance_name)
        return ts is not None and (now - ts) <= within_secs
    return any((now - ts) <= within_secs for ts in _restarts.values())
