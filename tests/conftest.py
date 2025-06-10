"""
Shared pytest configuration and fixtures.
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch
import sys

# Add the project root to the Python path to ensure imports work
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture(scope="session")
def project_root_path():
    """Provide the project root path."""
    return Path(__file__).parent.parent


@pytest.fixture
def temp_directory():
    """Create a temporary directory for test files."""
    temp_dir = tempfile.mkdtemp()
    yield Path(temp_dir)
    shutil.rmtree(temp_dir)


@pytest.fixture
def mock_logging():
    """Mock the logging setup to avoid file creation during tests."""
    with patch('src.web_server.setup_logging') as mock_log:
        mock_log.return_value.info = lambda x: None
        mock_log.return_value.error = lambda x: None
        mock_log.return_value.warning = lambda x: None
        yield mock_log


@pytest.fixture
def mock_atexit():
    """Mock atexit.register to avoid cleanup issues during tests."""
    with patch('atexit.register') as mock_exit:
        yield mock_exit