"""
API endpoints for Jira field discovery and mapping
"""

from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.core.database import get_db
from app.services.jira_service import jira_service
from app.services.jira_field_mapper import JiraFieldMapper, FieldType
from app.models.jira_field_mapping import JiraFieldMapping
from app.utils import transactional_session, handle_api_error, get_or_404
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# Initialize field mapper
field_mapper = JiraFieldMapper(jira_service)


@router.get("/fields")
async def discover_fields(
    force_refresh: bool = Query(False, description="Force refresh of field discovery"),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """
    Discover all available fields from Jira
    Returns field mappings and metadata
    """
    with handle_api_error(operation="discover_fields", status_code=500):
        # Discover fields
        fields = await field_mapper.discover_fields(force_refresh=force_refresh)

        # Get current mappings
        mappings = {}
        for field_type in FieldType:
            field_id = field_mapper.get_field_id(field_type)
            if field_id:
                mappings[field_type.value] = {
                    'field_id': field_id,
                    'field_name': fields.get(field_id, {}).get('name', 'Unknown')
                }

        return {
            'total_fields': len(fields),
            'custom_fields': len([f for f in fields.values() if f.get('custom')]),
            'standard_fields': len([f for f in fields.values() if not f.get('custom')]),
            'mappings': mappings,
            'all_fields': fields
        }


@router.post("/calibrate")
async def calibrate_fields(
    project_key: str,
    sample_size: int = Query(10, ge=1, le=50, description="Number of issues to analyze"),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    """
    Calibrate field mappings by analyzing sample issues from a project
    Automatically detects and maps common field types
    """
    with handle_api_error(operation="calibrate_fields", status_code=500, context={"project_key": project_key}):
        # Run calibration
        calibration_results = await field_mapper.calibrate(project_key, sample_size)

        # Save calibration results to database
        jira_url = jira_service.base_url

        async with transactional_session(db):
            for field_id, result in calibration_results.items():
                # Check if mapping exists
                existing = await db.execute(
                    select(JiraFieldMapping).where(
                        and_(
                            JiraFieldMapping.jira_instance_url == jira_url,
                            JiraFieldMapping.field_type == result['type'],
                            JiraFieldMapping.project_key == project_key
                        )
                    )
                )
                mapping = existing.scalar_one_or_none()

                if not mapping:
                    mapping = JiraFieldMapping(
                        jira_instance_url=jira_url,
                        project_key=project_key,
                        field_type=result['type'],
                        field_id=field_id,
                        discovery_method='auto',
                        confidence_score=result['confidence'],
                        is_active=result['confidence'] > 0.5  # Auto-activate if confident
                    )
                    db.add(mapping)
                else:
                    # Update existing mapping
                    mapping.field_id = field_id
                    mapping.confidence_score = result['confidence']
                    mapping.discovery_method = 'auto'

        payload = {
            'project_key': project_key,
            'sample_size': sample_size,
            'calibration_results': calibration_results,
            'auto_mapped': len([r for r in calibration_results.values() if r['confidence'] > 0.5])
        }
        if not calibration_results:
            # Provide a gentle hint to the client when nothing detected
            payload['warning'] = 'No fields detected. Check Jira credentials and API access; server may be returning HTML (SSO/login).'
        return payload


@router.get("/mappings")
async def get_field_mappings(
    project_key: Optional[str] = None,
    active_only: bool = True,
    db: AsyncSession = Depends(get_db)
) -> List[Dict[str, Any]]:
    """
    Get current field mappings from database
    """
    with handle_api_error(operation="get_field_mappings", status_code=500):
        query = select(JiraFieldMapping)

        if project_key:
            query = query.where(JiraFieldMapping.project_key == project_key)

        if active_only:
            query = query.where(JiraFieldMapping.is_active == True)

        result = await db.execute(query)
        mappings = result.scalars().all()

        return [
            {
                'id': m.id,
                'field_type': m.field_type,
                'field_id': m.field_id,
                'field_name': m.field_name,
                'project_key': m.project_key,
                'discovery_method': m.discovery_method,
                'confidence_score': m.confidence_score,
                'is_active': m.is_active
            }
            for m in mappings
        ]


@router.post("/mappings")
async def save_field_mapping(
    field_type: str,
    field_id: str,
    project_key: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
) -> Dict[str, str]:
    """
    Manually save a field mapping
    """
    # Validate field type
    try:
        field_type_enum = FieldType(field_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid field type: {field_type}")

    with handle_api_error(operation="save_field_mapping", status_code=500):
        jira_url = jira_service.base_url

        # Check if mapping exists
        query = select(JiraFieldMapping).where(
            and_(
                JiraFieldMapping.jira_instance_url == jira_url,
                JiraFieldMapping.field_type == field_type
            )
        )

        if project_key:
            query = query.where(JiraFieldMapping.project_key == project_key)

        result = await db.execute(query)
        mapping = result.scalar_one_or_none()

        async with transactional_session(db):
            if not mapping:
                # Create new mapping
                mapping = JiraFieldMapping(
                    jira_instance_url=jira_url,
                    project_key=project_key,
                    field_type=field_type,
                    field_id=field_id,
                    discovery_method='manual',
                    is_active=True
                )
                db.add(mapping)
            else:
                # Update existing
                mapping.field_id = field_id
                mapping.discovery_method = 'manual'
                mapping.is_active = True

        # Also update in-memory mapper
        field_mapper.set_field_mapping(field_type_enum, field_id)

        return {
            'field_type': field_type,
            'field_id': field_id,
            'status': 'saved'
        }


@router.delete("/mappings/{mapping_id}")
async def delete_field_mapping(
    mapping_id: int,
    db: AsyncSession = Depends(get_db)
) -> Dict[str, str]:
    """
    Delete or deactivate a field mapping
    """
    with handle_api_error(operation="delete_field_mapping", status_code=500, context={"mapping_id": mapping_id}):
        mapping = await get_or_404(
            db,
            select(JiraFieldMapping).where(JiraFieldMapping.id == mapping_id),
            "Mapping"
        )

        async with transactional_session(db):
            # Soft delete - just deactivate
            mapping.is_active = False

        return {'status': 'deactivated', 'mapping_id': mapping_id}


@router.post("/test-mapping")
async def test_field_mapping(
    issue_key: str,
    field_type: Optional[str] = None
) -> Dict[str, Any]:
    """
    Test field mapping with a specific issue
    Returns the mapped fields for verification
    """
    with handle_api_error(operation="test_field_mapping", status_code=500, context={"issue_key": issue_key}):
        # Get issue with mapped fields
        mapped_issue = await field_mapper.get_issue_with_mapped_fields(issue_key)

        if not mapped_issue:
            raise HTTPException(status_code=404, detail=f"Issue {issue_key} not found")

        # If specific field type requested, focus on that
        if field_type:
            try:
                field_type_enum = FieldType(field_type)
                field_id = field_mapper.get_field_id(field_type_enum)

                return {
                    'issue_key': issue_key,
                    'field_type': field_type,
                    'field_id': field_id,
                    'value': mapped_issue.get(field_type),
                    'all_mapped_fields': mapped_issue
                }
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid field type: {field_type}")

        return {
            'issue_key': issue_key,
            'mapped_fields': mapped_issue,
            'sprints': mapped_issue.get('sprints', []),
            'has_sprint_data': len(mapped_issue.get('sprints', [])) > 0
        }


@router.get("/export-config")
async def export_configuration() -> Dict[str, Any]:
    """
    Export current field mapping configuration
    Can be imported on another instance
    """
    with handle_api_error(operation="export_configuration", status_code=500):
        config = field_mapper.export_configuration()
        return config


@router.post("/import-config")
async def import_configuration(
    config: Dict[str, Any],
    db: AsyncSession = Depends(get_db)
) -> Dict[str, str]:
    """
    Import field mapping configuration
    """
    with handle_api_error(operation="import_configuration", status_code=500):
        # Import to mapper
        field_mapper.import_configuration(config)

        # Save to database
        jira_url = jira_service.base_url
        mappings = config.get('mappings', {})

        async with transactional_session(db):
            for field_type, field_id in mappings.items():
                # Check if exists
                result = await db.execute(
                    select(JiraFieldMapping).where(
                        and_(
                            JiraFieldMapping.jira_instance_url == jira_url,
                            JiraFieldMapping.field_type == field_type
                        )
                    )
                )
                mapping = result.scalar_one_or_none()

                if not mapping:
                    mapping = JiraFieldMapping(
                        jira_instance_url=jira_url,
                        field_type=field_type,
                        field_id=field_id,
                        discovery_method='import',
                        is_active=True
                    )
                    db.add(mapping)
                else:
                    mapping.field_id = field_id
                    mapping.discovery_method = 'import'
                    mapping.is_active = True

        return {
            'status': 'imported',
            'mappings_count': len(mappings)
        }


@router.get("/sprints/{issue_key}")
async def get_issue_sprints(issue_key: str) -> Dict[str, Any]:
    """
    Get sprints for an issue using multiple fallback strategies
    Useful for testing sprint field mapping
    """
    with handle_api_error(operation="get_issue_sprints", status_code=500, context={"issue_key": issue_key}):
        sprints = await field_mapper.get_sprints_with_fallback(issue_key)

        return {
            'issue_key': issue_key,
            'sprints': sprints,
            'sprint_count': len(sprints),
            'active_sprint': next((s for s in sprints if s.get('state') == 'active'), None)
        }
