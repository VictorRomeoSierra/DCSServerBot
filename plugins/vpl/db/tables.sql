-- Insert your database DDL or DML in here!
-- If you need to update the database to a newer version, increase the version in here to the next higher one
-- (v1.2 in this case as we are simulating an update already with the update SQL below), and make sure, that you
-- UPDATE the plugins table in your update script (see example).
CREATE TABLE vpl (datestamp TIMESTAMP NOT NULL DEFAULT NOW(), name TEXT, freq TEXT, coords jsonb, objecttype TEXT, CONSTRAINT vpl_pkey PRIMARY KEY (datestamp));