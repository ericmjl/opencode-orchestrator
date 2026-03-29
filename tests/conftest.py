"""
Pytest configuration for Playwright tests.
"""

import pytest


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    """Add headless mode by default."""
    return {
        **browser_type_launch_args,
        "headless": True,
    }


@pytest.fixture
def context(browser):
    """Create a new browser context for each test."""
    return browser.new_context()


@pytest.fixture
def page(context):
    """Create a new page for each test."""
    return context.new_page()
