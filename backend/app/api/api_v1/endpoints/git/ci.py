"""
CI/CD results handler module.
Processes test results, coverage reports, and build artifacts.
"""

from __future__ import annotations
import xml.etree.ElementTree as ET
import logging
from typing import Dict, Any, List, Optional, cast

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models import Artifact, ArtifactLink, CoverageReport, TestResult
from app.utils import transactional_session
from app.core.metrics import metrics

logger = logging.getLogger(__name__)


def parse_junit_xml(xml_text: str) -> List[Dict[str, Any]]:
    """Parse JUnit XML test results."""
    results: List[Dict[str, Any]] = []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.error(f"Failed to parse JUnit XML: {e}")
        return results

    def handle_test_case(suite_name: Optional[str], case_el: ET.Element):
        """Process individual test case element."""
        name = case_el.attrib.get("name")
        classname = case_el.attrib.get("classname")
        time_str = case_el.attrib.get("time")

        # Default to passed
        status = "passed"
        message = None
        raw = {}

        # Check for failure/error/skipped elements
        for child in case_el:
            tag = child.tag.lower()

            if "failure" in tag:
                status = "failed"
                message = child.attrib.get("message") or (child.text or "").strip()
                raw["failure"] = child.attrib

            elif "error" in tag:
                status = "error"
                message = child.attrib.get("message") or (child.text or "").strip()
                raw["error"] = child.attrib

            elif "skipped" in tag:
                status = "skipped"
                message = child.attrib.get("message")

        # Parse time duration
        try:
            time_float = float(time_str) if time_str is not None else None
        except (ValueError, TypeError):
            time_float = None

        results.append(
            {
                "suite": suite_name,
                "classname": classname,
                "name": name,
                "time": time_float,
                "status": status,
                "message": message,
                "raw": raw if raw else None,
            }
        )

    # Handle different JUnit XML structures
    root_tag = root.tag.lower()

    if "testsuites" in root_tag:
        # Multiple test suites
        for testsuite in root.findall(".//testsuite"):
            suite_name = testsuite.attrib.get("name")
            for testcase in testsuite.findall("testcase"):
                handle_test_case(suite_name, testcase)

    elif "testsuite" in root_tag:
        # Single test suite
        suite_name = root.attrib.get("name")
        for testcase in root.findall("testcase"):
            handle_test_case(suite_name, testcase)

    else:
        # Try generic search for testcase elements
        for testcase in root.findall(".//testcase"):
            handle_test_case(None, testcase)

    return results


def parse_cobertura_xml(xml_text: str) -> Optional[Dict[str, Any]]:
    """Parse Cobertura coverage XML."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.error(f"Failed to parse Cobertura XML: {e}")
        return None

    # Extract coverage rates
    line_rate = root.attrib.get("line-rate") or root.attrib.get("lineRate")
    branch_rate = root.attrib.get("branch-rate") or root.attrib.get("branchRate")

    def to_percentage(val: Optional[str]) -> Optional[float]:
        """Convert rate to percentage."""
        try:
            if val is not None:
                rate = float(val)
                # Convert to percentage if needed (0-1 range to 0-100)
                return rate * 100 if rate <= 1.0 else rate
            return None
        except (ValueError, TypeError):
            return None

    line_coverage = to_percentage(line_rate)
    branch_coverage = to_percentage(branch_rate)

    # Parse file-level coverage
    files: List[Dict[str, Any]] = []

    for class_el in root.findall(".//class"):
        file_path = class_el.attrib.get("filename") or class_el.attrib.get("name")
        if not file_path:
            continue

        # Class-level coverage rates
        class_line_rate = to_percentage(
            class_el.attrib.get("line-rate") or class_el.attrib.get("lineRate")
        )
        class_branch_rate = to_percentage(
            class_el.attrib.get("branch-rate") or class_el.attrib.get("branchRate")
        )

        # Count covered lines
        lines = class_el.findall(".//lines/line") or class_el.findall(".//line")
        covered_lines = 0
        total_lines = 0

        for line in lines:
            hits = line.attrib.get("hits") or line.attrib.get("count")
            try:
                hit_count = int(hits) if hits is not None else 0
            except (ValueError, TypeError):
                hit_count = 0

            total_lines += 1
            if hit_count > 0:
                covered_lines += 1

        # Calculate file coverage
        file_line_coverage = (
            (covered_lines / total_lines * 100) if total_lines > 0 else class_line_rate
        )

        files.append(
            {
                "file_path": file_path,
                "line_coverage": file_line_coverage,
                "branch_coverage": class_branch_rate,
                "lines_covered": covered_lines if total_lines > 0 else None,
                "lines_total": total_lines if total_lines > 0 else None,
            }
        )

    result: Dict[str, Any] = {}

    if line_coverage is not None:
        result["line"] = line_coverage

    if branch_coverage is not None:
        result["branch"] = branch_coverage

    if files:
        result["files"] = files

    return result if result else None


def parse_jacoco_xml(xml_text: str) -> Optional[Dict[str, Any]]:
    """Parse JaCoCo coverage XML."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        logger.error(f"Failed to parse JaCoCo XML: {e}")
        return None

    # JaCoCo uses counter elements
    counters = root.findall(".//counter")
    total_covered = 0
    total_missed = 0
    branch_covered = 0
    branch_missed = 0

    for counter in counters:
        counter_type = (counter.attrib.get("type") or "").lower()

        try:
            covered = int(counter.attrib.get("covered") or 0)
            missed = int(counter.attrib.get("missed") or 0)
        except (ValueError, TypeError):
            continue

        if counter_type in ("instruction", "line"):
            total_covered += covered
            total_missed += missed
        elif counter_type == "branch":
            branch_covered += covered
            branch_missed += missed

    result = {}

    # Calculate line coverage
    total = total_covered + total_missed
    if total > 0:
        result["line"] = round((total_covered / total) * 100, 2)

    # Calculate branch coverage
    branch_total = branch_covered + branch_missed
    if branch_total > 0:
        result["branch"] = round((branch_covered / branch_total) * 100, 2)

    return result if result else None


async def process_ci_results(db: AsyncSession, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Process CI/CD results including tests and coverage."""

    provider = (payload.get("provider") or "generic").lower()
    commit_sha = payload.get("commit_sha")
    pr_number = payload.get("pr_number")
    junit_xml = payload.get("junit_xml")
    coverage = payload.get("coverage") or {}
    report_url = payload.get("report_url")

    tests_created = 0
    tests_failed = 0
    tests_passed = 0
    tests_skipped = 0

    # Process JUnit test results
    if junit_xml:
        try:
            test_results = parse_junit_xml(junit_xml)

            for result in test_results:
                test_record = TestResult(
                    provider=provider,
                    commit_sha=commit_sha,
                    pr_number=pr_number,
                    suite=result.get("suite"),
                    classname=result.get("classname"),
                    name=result.get("name"),
                    status=result.get("status"),
                    duration=result.get("time"),
                    message=result.get("message"),
                    raw=result.get("raw"),
                )
                db.add(test_record)
                tests_created += 1

                # Count by status
                status = result.get("status", "").lower()
                if status in ("failed", "error"):
                    tests_failed += 1
                elif status == "passed":
                    tests_passed += 1
                elif status == "skipped":
                    tests_skipped += 1

            logger.info(
                f"Processed {tests_created} tests: "
                f"{tests_passed} passed, {tests_failed} failed, {tests_skipped} skipped"
            )

        except Exception as e:
            logger.error(f"Error processing JUnit XML: {e}")
            metrics.inc("ci_parse_errors", labels={"provider": provider, "type": "junit"})

    # Parse coverage from XML if not provided directly
    if not coverage:
        # Try JaCoCo
        jacoco_xml = payload.get("jacoco_xml")
        if jacoco_xml:
            coverage = parse_jacoco_xml(jacoco_xml) or coverage

        # Try Cobertura
        if not coverage:
            cobertura_xml = payload.get("cobertura_xml")
            if cobertura_xml:
                coverage = parse_cobertura_xml(cobertura_xml) or coverage

    # Store coverage report
    coverage_obj = None
    if coverage:
        try:
            coverage_obj = CoverageReport(
                provider=provider,
                commit_sha=commit_sha,
                pr_number=pr_number,
                line_coverage=coverage.get("line"),
                branch_coverage=coverage.get("branch"),
                report_url=report_url,
            )
            db.add(coverage_obj)
            await db.flush()

            # Store file-level coverage if available
            files = coverage.get("files")
            if files and isinstance(files, list):
                # Import FileCoverage if exists
                try:
                    from app.models.testing import FileCoverage

                    for file_data in files:
                        try:
                            file_cov = FileCoverage(
                                coverage_report_id=coverage_obj.id,
                                provider=provider,
                                commit_sha=commit_sha,
                                file_path=file_data.get("file_path"),
                                line_coverage=file_data.get("line_coverage"),
                                branch_coverage=file_data.get("branch_coverage"),
                                lines_covered=file_data.get("lines_covered"),
                                lines_total=file_data.get("lines_total"),
                            )
                            db.add(file_cov)
                        except Exception as e:
                            logger.warning(f"Failed to store file coverage: {e}")
                            continue

                except ImportError:
                    logger.debug("FileCoverage model not available, skipping file-level coverage")

            logger.info(
                f"Stored coverage report: line={coverage.get('line')}%, "
                f"branch={coverage.get('branch')}%"
            )

        except Exception as e:
            logger.error(f"Error storing coverage report: {e}")
            metrics.inc("ci_parse_errors", labels={"provider": provider, "type": "coverage"})

    # Create test_run artifact and link to commit
    if commit_sha:
        try:
            # Ensure commit artifact exists
            res = await db.execute(
                select(Artifact).where(
                    Artifact.type == "commit", Artifact.external_id == commit_sha
                )
            )
            commit_art = res.scalar_one_or_none()

            if not commit_art:
                commit_art = Artifact(
                    type="commit",
                    source=provider,
                    external_id=commit_sha,
                    display_key=commit_sha[:8],
                    title=f"Commit {commit_sha[:8]}",
                )
                db.add(commit_art)
                await db.flush()

            # Create test_run artifact
            run_external_id = f"{provider}:{commit_sha}"
            res = await db.execute(
                select(Artifact).where(
                    Artifact.type == "test_run",
                    Artifact.source == "ci",
                    Artifact.external_id == run_external_id,
                )
            )
            test_art = res.scalar_one_or_none()

            if not test_art:
                test_art = Artifact(
                    type="test_run",
                    source="ci",
                    external_id=run_external_id,
                    title=f"CI Tests for {commit_sha[:8]}",
                    status="passed" if tests_failed == 0 else "failed",
                )
                db.add(test_art)
                await db.flush()
            else:
                # Update status based on test results
                test_art.status = "passed" if tests_failed == 0 else "failed"

            # Update test artifact metadata
            test_art.meta = test_art.meta or {}
            test_art.meta.update(
                {
                    "tests_total": tests_created,
                    "tests_passed": tests_passed,
                    "tests_failed": tests_failed,
                    "tests_skipped": tests_skipped,
                    "coverage_line": coverage.get("line") if coverage else None,
                    "coverage_branch": coverage.get("branch") if coverage else None,
                }
            )

            # Link test_run to commit
            res = await db.execute(
                select(ArtifactLink).where(
                    ArtifactLink.from_artifact_id == test_art.id,
                    ArtifactLink.to_artifact_id == commit_art.id,
                    ArtifactLink.link_type == "tests",
                )
            )
            link = cast(ArtifactLink | None, res.scalar_one_or_none())

            if not link:
                link = ArtifactLink(
                    from_artifact_id=test_art.id,
                    to_artifact_id=commit_art.id,
                    link_type="tests",
                    confidence=0.95,
                    confidence_factors={"source": "ci_results"},
                )
                db.add(link)

        except Exception as e:
            logger.error(f"Error creating test artifacts: {e}")

    # Commit all changes
    async with transactional_session(db):
        pass  # All db operations already executed above

    # Update metrics
    if tests_created:
        metrics.inc("ci_tests_total", tests_created, labels={"provider": provider})
        if tests_failed:
            metrics.inc("ci_tests_failed", tests_failed, labels={"provider": provider})
        if tests_passed:
            metrics.inc("ci_tests_passed", tests_passed, labels={"provider": provider})

    if coverage_obj:
        metrics.inc("ci_coverage_reports", labels={"provider": provider})

    return {
        "ok": True,
        "provider": provider,
        "tests_created": tests_created,
        "tests_passed": tests_passed,
        "tests_failed": tests_failed,
        "tests_skipped": tests_skipped,
        "coverage_saved": bool(coverage_obj),
        "coverage": {"line": coverage.get("line"), "branch": coverage.get("branch")}
        if coverage
        else None,
    }
