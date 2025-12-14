from app.schemas.project import ProjectWithStats
payload = {
    'id': 1,
    'jira_key': 'PRIM',
    'name': 'PrimaCare',
    'status': 'active',
    'meta': '{\"last_sync_at\": \"2025-10-04T10:08:50.728019\"}',
    'created_at': '2025-10-04T10:00:00',
    'updated_at': None,
}
model = ProjectWithStats(**payload)
print(model.meta)
