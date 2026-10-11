-- One-time setup of the separate clips database, on the existing haman-db container.
-- Optional hardening. By default the API creates the clips database itself using the
-- main haman role (see app/jobs/prepare_clips.py). This script instead gives it a
-- separate role, so the clips can be backed up and accessed separately.
--
--   docker exec -i haman-db psql -U haman -d hamanhealth \
--     -v clips_pass="'$(openssl rand -hex 24)'" < deploy/sql/create_clips_db.sql
--
-- Then point CLIPS_DATABASE_URL in deploy/docker-compose.haman.yml at
--   postgresql://haman_clips:<password>@haman-db:5432/hamanclips
-- and redeploy haman-api; the entrypoint creates the table.
--
-- Keep the clip key (HAMAN_CLIPS_KEY or the haman-keys volume) safe and separate from database backups: without it the clip
-- files cannot be decrypted (by anyone, including us).

CREATE ROLE haman_clips LOGIN PASSWORD :clips_pass;
CREATE DATABASE hamanclips OWNER haman_clips;
-- The main app role does not need access to the clips database.
REVOKE ALL ON DATABASE hamanclips FROM PUBLIC;
