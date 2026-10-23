-- =============================================================================
-- FactSync Chile: read-only access for the app's own Zetaris user.
-- Run as an ADMIN user after 01-04. One statement per request.
--
-- Before running it, in the Zetaris web UI:
--   1. Management > Users: create a user with the General role (view only).
--   2. Signed in as that user, create an API key for it.
--   3. In the app's .env: ZETARIS_API_KEY = that user's key, ZETARIS_ADMIN_API_KEY =
--      the admin key (only the setup scripts use it), ZETARIS_APP_USER = the
--      user's login e-mail.
--
-- The app only runs SELECT on the factsync views, so it gets exactly that.
-- YOUR_APP_USER is filled in from ZETARIS_APP_USER by scripts/zetaris_sql.py.
-- Check the result with: .venv\Scripts\python scripts\verify_readonly.py
-- =============================================================================

GRANT SELECT ON VIEW NAMESPACE factsync TO USER 'YOUR_APP_USER';
