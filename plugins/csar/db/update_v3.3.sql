-- Store ucid directly on csar_wounded so lookups don't have to join on the
-- mutable players.name field.
ALTER TABLE csar_wounded ADD COLUMN IF NOT EXISTS ucid TEXT;

-- Backfill csar_wounded.ucid from players.name. On name collisions across
-- multiple players, prefer the most recently seen account.
UPDATE csar_wounded w
SET ucid = p.ucid
FROM (
    SELECT DISTINCT ON (name) name, ucid
    FROM players
    WHERE name IS NOT NULL AND LENGTH(ucid) = 32
    ORDER BY name, last_seen DESC NULLS LAST
) p
WHERE w.ucid IS NULL
  AND w.playername IS NOT NULL
  AND w.playername <> ''
  AND p.name = w.playername;

-- The previous listener stored '-1' on csar_events when name->ucid resolution
-- failed (and a later refactor broke the resolver entirely). Backfill those
-- rows the same way so historical stats line up with the current player.
UPDATE csar_events e
SET ucid = p.ucid
FROM (
    SELECT DISTINCT ON (name) name, ucid
    FROM players
    WHERE name IS NOT NULL AND LENGTH(ucid) = 32
    ORDER BY name, last_seen DESC NULLS LAST
) p
WHERE e.ucid = '-1'
  AND e.playername IS NOT NULL
  AND e.playername <> ''
  AND p.name = e.playername;

-- Make (id, server_name) the primary key so two servers can't collide on the
-- same wounded id. Drops orphaned rows from before update_v3.1 added the
-- server_name column (we have no way to attribute them to a server).
DELETE FROM csar_wounded WHERE server_name IS NULL OR server_name = '';
ALTER TABLE csar_wounded ALTER COLUMN server_name SET NOT NULL;
ALTER TABLE csar_wounded DROP CONSTRAINT IF EXISTS csar_wounded_pkey;
ALTER TABLE csar_wounded ADD PRIMARY KEY (id, server_name);
