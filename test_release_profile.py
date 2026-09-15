"""Release profile unification tests (Task 1A)."""
import sys
sys.path.insert(0, '.')

from ultimate_pipeline.contracts.stage_contracts import ReleaseProfile, resolve_release_profile
from ultimate_pipeline.contracts.release_profile import resolve_experimental_unsafe


def test_canonical_names():
    """Test that all canonical profile names resolve correctly."""
    for profile in ReleaseProfile:
        result = resolve_release_profile(profile.value)
        assert result == profile, f'{profile} resolved to {result}, expected {profile}'
    print('PASS: test_canonical_names')


def test_documented_aliases():
    """Test that all documented aliases resolve correctly."""
    aliases = {
        'development': ReleaseProfile.STRUCTURAL_RELEASE,
        'structural_release': ReleaseProfile.STRUCTURAL_RELEASE,
        'carla_release': ReleaseProfile.STRUCTURAL_RELEASE,
        'visual_release': ReleaseProfile.VISUAL_BUILD,
        'perception_release': ReleaseProfile.VISUAL_BUILD,
        'experimental_unsafe': ReleaseProfile.EXPERIMENTAL_UNSAFE,
    }
    for alias, expected in aliases.items():
        result = resolve_release_profile(alias)
        assert result == expected, f'{alias} resolved to {result}, expected {expected}'
    print('PASS: test_documented_aliases')


def test_unknown_name():
    """Test that unknown profile names raise ValueError."""
    try:
        resolve_release_profile('unknown_profile')
        assert False, 'Should have raised ValueError'
    except ValueError:
        pass
    print('PASS: test_unknown_name')


def test_empty_name():
    """Test that empty profile name raises ValueError."""
    try:
        resolve_release_profile('')
        assert False, 'Should have raised ValueError'
    except ValueError:
        pass
    print('PASS: test_empty_name')


def test_resolve_experimental_unsafe():
    """Test that resolve_experimental_unsafe works correctly."""
    # Profiles that allow experimental unsafe
    assert resolve_experimental_unsafe('experimental_unsafe') == True
    assert resolve_experimental_unsafe('debug') == True
    # Profiles that don't allow experimental unsafe
    assert resolve_experimental_unsafe('structural_release') == False
    assert resolve_experimental_unsafe('visual_build') == False
    assert resolve_experimental_unsafe('debug') == True
    assert resolve_experimental_unsafe('scenario_augmentation') == False
    print('PASS: test_resolve_experimental_unsafe')


if __name__ == '__main__':
    test_canonical_names()
    test_documented_aliases()
    test_unknown_name()
    test_empty_name()
    test_resolve_experimental_unsafe()
    print()
    print('All Task 1A tests PASSED!')