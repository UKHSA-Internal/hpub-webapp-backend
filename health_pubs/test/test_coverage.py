import pytest

"""
This file contains a test for the purpose of activating coverage test
This only contains one single empty test with one fixture that will return true
"""


@pytest.fixture
def fixture_for_coverage():
    # Setup code for the fixture
    return "test_for_coverage"


def test_for_coverage(fixture_for_coverage):
    # Test logic using the fixture
    assert fixture_for_coverage == "test_for_coverage"
