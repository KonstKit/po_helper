from fastapi.testclient import TestClient
from app.main import app
from app.api import deps
from app.models import User

class DummyUser(User):
    def has_permission(self, perm: str) -> bool:
        return True

async def override_get_current_user():
    user = DummyUser(id=0, email='test@example.com', username='test', full_name='Test User', hashed_password='', is_active=True, is_superuser=True)
    return user

app.dependency_overrides[deps.get_current_user] = override_get_current_user
app.dependency_overrides[deps.require_permission('dummy')] = lambda: override_get_current_user

client = TestClient(app)
resp = client.get('/api/v1/projects/3')
print(resp.status_code)
print(resp.json())
