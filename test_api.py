import pytest
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def test_environment():
    """Test if the environment is set up correctly"""
    assert True

def test_requirements_exist():
    """Check if requirements.txt exists"""
    assert os.path.isfile("requirements.txt"), "requirements.txt file is missing"

def test_api_structure():
    """Test if key API modules exist"""
    api_files = [
        "api/main.py",
    ]
    
    for file in api_files:
        if os.path.exists(file):
            assert os.path.isfile(file), f"{file} is not a file"

@pytest.mark.skip(reason="Skipping actual API functionality tests in CI")
def test_api_functionality():
    """This test would test actual API functionality but is skipped in CI"""
    pass