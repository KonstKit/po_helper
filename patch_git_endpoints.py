# -*- coding: utf-8 -*-
from pathlib import Path
p=Path('backend/app/api/api_v1/endpoints/git.py')
s=p.read_text()
# Imports
if 'from sqlalchemy.exc import IntegrityError' not in s:
    s=s.replace('from sqlalchemy import select', 'from sqlalchemy import select\nfrom sqlalchemy.exc import IntegrityError')
if 'from app.core.db_utils import supports_for_update' not in s:
    s=s.replace('from app.core.metrics import metrics', 'from app.core.metrics import metrics\nfrom app.core.db_utils import supports_for_update')

# _get_or_create_repo: wrap in transaction with FOR UPDATE
s=s.replace(
    'async def _get_or_create_repo(db: AsyncSession, provider: str, slug: str, default_branch: Optional[str] = None) -> Repository:\n    res = await db.execute(select(Repository).where(Repository.provider == provider, Repository.repo_slug == slug))\n    repo = res.scalar_one_or_none()\n    if not repo:\n        repo = Repository(provider=provider, repo_slug=slug, default_branch=default_branch)\n        db.add(repo)\n        await db.commit()\n        await db.refresh(repo)\n    return repo',
    'async def _get_or_create_repo(db: AsyncSession, provider: str, slug: str, default_branch: Optional[str] = None) -> Repository:\n    try:\n        async with db.begin():\n            sel = select(Repository).where(Repository.provider == provider, Repository.repo_slug == slug)\n            if supports_for_update(db):\n                sel = sel.with_for_update()\n            res = await db.execute(sel)\n            repo = res.scalar_one_or_none()\n            if not repo:\n                repo = Repository(provider=provider, repo_slug=slug, default_branch=default_branch)\n                db.add(repo)\n        await db.refresh(repo)\n        return repo\n    except IntegrityError:\n        await db.rollback()\n        # Re-select after race\n        res = await db.execute(select(Repository).where(Repository.provider == provider, Repository.repo_slug == slug))\n        repo = res.scalar_one_or_none()\n        if repo:\n            return repo\n        raise'
)

# create_commit_artifacts: enclose main loop work in transaction; check Commit with FOR UPDATE; catch IntegrityError
s=s.replace(
    '    repo = await _get_or_create_repo(db, provider, repo_slug)\n    created = 0\n    updated = 0\n    links_created = 0\n    suggestions: List[Dict[str, Any]] = []\n\n    for c in commits:',
    '    repo = await _get_or_create_repo(db, provider, repo_slug)\n    created = 0\n    updated = 0\n    links_created = 0\n    suggestions: List[Dict[str, Any]] = []\n\n    try:\n        async with db.begin():\n            for c in commits:'
)
s=s.replace(
    '    await db.commit()\n    return {"created": created, "updated": updated, "links_created": links_created, "suggestions": suggestions}',
    '    except IntegrityError:\n        await db.rollback()\n        # Duplicate commit/artifact under race — continue best-effort\n        pass\n    return {"created": created, "updated": updated, "links_created": links_created, "suggestions": suggestions}'
)
# In per-commit select for CommitModel, add FOR UPDATE when creating new
s=s.replace(
    '        res = await db.execute(select(CommitModel).where(CommitModel.repository_id == repo.id, CommitModel.sha == sha))\n        cm = res.scalar_one_or_none()\n        if not cm:\n            cm = CommitModel(repository_id=repo.id, sha=sha)\n            db.add(cm)\n            created += 1\n        else:\n            updated += 1',
    '        sel_cm = select(CommitModel).where(CommitModel.repository_id == repo.id, CommitModel.sha == sha)\n        if supports_for_update(db):\n            sel_cm = sel_cm.with_for_update()\n        cm = (await db.execute(sel_cm)).scalar_one_or_none()\n        if not cm:\n            cm = CommitModel(repository_id=repo.id, sha=sha)\n            db.add(cm)\n            created += 1\n        else:\n            updated += 1'
)

# upsert_pull_request_artifact: wrap artifact upsert and linking in transaction, IntegrityError handling
s=s.replace(
    '    artifact = res.scalar_one_or_none()\n    if not artifact:\n        artifact = Artifact(\n            type="pull_request",',
    '    artifact = res.scalar_one_or_none()\n    try:\n        async with db.begin():\n            if not artifact:\n                artifact = Artifact(\n            type="pull_request",'
)
s=s.replace(
    '        )\n        db.add(artifact)\n        await db.flush()\n    else:',
    '        )\n                db.add(artifact)\n                await db.flush()\n            else:'
)
s=s.replace(
    '    return {"links_created": links_created, "suggestions": suggestions}',
    '    except IntegrityError:\n        await db.rollback()\n        # Link or artifact duplicate under race\n        pass\n    return {"links_created": links_created, "suggestions": suggestions}'
)

Path('backend/app/api/api_v1/endpoints/git.py').write_text(s)
print('git endpoints patched')
