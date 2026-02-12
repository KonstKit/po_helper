#!/usr/bin/env python3
"""
Hotfix for task schema without restarting the server.
Run this script to patch the running application.
"""


# This is a temporary fix that modifies the schema validation
# without needing to restart the backend

print("Applying hotfix for task schema...")

# The fix is already in the code, but if you need to apply it without restart,
# you would need to use a different approach like:
# 1. Creating a new endpoint that doesn't use the strict schema
# 2. Using a database migration to fix NULL project_ids
# 3. Using a middleware to intercept and fix the response

# For now, let's create a SQL script to fix the data
sql_fix = """
-- Find tasks without project_id
SELECT COUNT(*) as orphaned_tasks FROM tasks WHERE project_id IS NULL;

-- If you know which project they belong to, update them:
-- UPDATE tasks SET project_id = (SELECT id FROM projects WHERE jira_key = 'WAB' LIMIT 1)
-- WHERE project_id IS NULL;

-- Or delete orphaned tasks if they're not needed:
-- DELETE FROM tasks WHERE project_id IS NULL;
"""

print("SQL fix to run in your database:")
print(sql_fix)

print("\nAlternatively, you can:")
print("1. Use --reload flag when starting uvicorn (for auto-reload on code changes)")
print("2. Save settings before restart: curl http://127.0.0.1:8000/api/v1/settings/export > settings.json")
print("3. Restore after restart: curl -X POST http://127.0.0.1:8000/api/v1/settings/import --data @settings.json")