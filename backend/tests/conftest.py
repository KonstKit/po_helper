import os

# Ensure cryptographic settings exist for the test environment before the app loads settings
TEST_SECRET = "test-secret-key-should-be-long-enough-1234567890"
os.environ.setdefault("SECRET_KEY", TEST_SECRET)
os.environ.setdefault("ENCRYPTION_SECRET", TEST_SECRET)
