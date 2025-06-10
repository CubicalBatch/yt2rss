#!/usr/bin/env python3
"""
Simple test runner for the YouTube RSS project.
"""

import subprocess
import sys
from pathlib import Path


def run_tests():
    """Run all tests and show coverage report."""
    print("🧪 Running YouTube RSS Web Server Tests...")
    print("=" * 50)
    
    try:
        # Run tests with coverage
        result = subprocess.run([
            sys.executable, '-m', 'pytest', 
            'tests/', 
            '--cov=src.web_server',
            '--cov-report=term-missing',
            '-v'
        ], cwd=Path(__file__).parent)
        
        if result.returncode == 0:
            print("\n✅ All tests passed!")
        else:
            print("\n❌ Some tests failed!")
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n🛑 Tests interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 Error running tests: {e}")
        sys.exit(1)


if __name__ == "__main__":
    run_tests()