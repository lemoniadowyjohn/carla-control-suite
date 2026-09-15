"""Quality status model tests (Task 2)."""
import sys
sys.path.insert(0, '.')

from ultimate_pipeline.contracts.stage_contracts import QualityStatus, from_legacy_bool, from_legacy_exception, from_skipped_mandatory, from_missing_external


def test_quality_status_enum():
    """Test all QualityStatus enum members."""
    # StrEnum members have string values
    assert QualityStatus.PASS.value == 'pass'
    assert QualityStatus.FAIL.value == 'fail'
    assert QualityStatus.INCOMPLETE.value == 'incomplete'
    assert QualityStatus.NOT_RUN.value == 'not_run'
    assert QualityStatus.BLOCKED_EXTERNAL.value == 'blocked_external'
    assert QualityStatus.WAIVED.value == 'waived'
    print('PASS: test_quality_status_enum')


def test_from_legacy_bool():
    """Test legacy Boolean mapping."""
    assert from_legacy_bool(True) == QualityStatus.PASS
    assert from_legacy_bool(False) == QualityStatus.FAIL
    print('PASS: test_from_legacy_bool')


def test_from_legacy_exception():
    """Test legacy exception mapping."""
    assert from_legacy_exception(None) == QualityStatus.PASS
    assert from_legacy_exception(ValueError()) == QualityStatus.FAIL
    print('PASS: test_from_legacy_exception')


def test_from_skipped_mandatory():
    """Test skipped mandatory returns INCOMPLETE."""
    assert from_skipped_mandatory() == QualityStatus.INCOMPLETE
    print('PASS: test_from_skipped_mandatory')


def test_from_missing_external():
    """Test missing external runtime mapping."""
    assert from_missing_external(None) == QualityStatus.NOT_RUN
    assert from_missing_external('CARLA') == QualityStatus.BLOCKED_EXTERNAL
    print('PASS: test_from_missing_external')


if __name__ == '__main__':
    test_quality_status_enum()
    test_from_legacy_bool()
    test_from_legacy_exception()
    test_from_skipped_mandatory()
    test_from_missing_external()
    print()
    print('All Task 2 tests PASSED!')