CREATE TABLE IF NOT EXISTS csar_events (
    datestamp TIMESTAMP NOT NULL DEFAULT now(),
    ts double precision NOT NULL,
    playername text,
    ucid text,
    savedpilots int,
    helicopterused text,
    CONSTRAINT csar_events_pkey PRIMARY KEY (datestamp, ts)
);
CREATE TABLE IF NOT EXISTS csar_wounded
(
    datestamp TIMESTAMP DEFAULT now(),
    id text,
    coalition int,
    country int,
    pos jsonb,
    coordinates text,
    unitname text,
    typename text,
    playername text,
    ucid text,
    freq text,
    voice text,
    server_name text NOT NULL,
    CONSTRAINT csar_wounded_pkey PRIMARY KEY (id, server_name)
);
