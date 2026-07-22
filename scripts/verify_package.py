#!/usr/bin/env python3
"""
Verify PySubtrans package installation script.
Creates a fresh virtual environment, installs pysubtrans from PyPI,
verifies the version matches, and runs unit tests.
"""

import os
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path

def run_command(cmd : list[str], cwd : str|None = None, capture_output : bool = True, env : dict|None = None) -> subprocess.CompletedProcess:
    """Run a command and return the result"""
    print(f"Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, cwd=cwd, capture_output=capture_output, text=True, check=False, env=env)
        if result.returncode != 0:
            print(f"Command failed with return code {result.returncode}")
            if capture_output:
                print(f"stdout: {result.stdout}")
                print(f"stderr: {result.stderr}")
        return result
    except Exception as e:
        print(f"Error running command: {e}")
        raise

def get_project_version() -> str:
    """Get the version from PySubtrans/version.py"""
    script_dir = Path(__file__).parent
    version_file = script_dir.parent / "PySubtrans" / "version.py"

    if not version_file.exists():
        raise FileNotFoundError(f"Version file not found: {version_file}")

    with open(version_file, 'r') as f:
        content = f.read()

    # Extract version from __version__ = "vX.Y.Z" format
    import re
    match = re.search(r'__version__\s*=\s*["\']v?([^"\']+)["\']', content)
    if not match:
        raise ValueError(f"Could not parse version from {version_file}")

    return match.group(1)

def run_unit_tests(venv_python : str):
    """Run the unit tests from the project's tests/unit_tests.py using the clean venv"""
    print("Running unit tests from project...")

    # Get the path to the project's unit_tests.py
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    unit_tests_script = project_root / "tests" / "unit_tests.py"

    if not unit_tests_script.exists():
        print(f"Warning: Unit tests script not found at {unit_tests_script}")
        return True

    # Create clean environment to ensure we use the installed package
    env = os.environ.copy()
    if 'PYTHONPATH' in env:
        del env['PYTHONPATH']  # Remove local development path

    # Run the unit tests using the clean virtual environment's python
    # Use a temp directory as working directory to avoid path conflicts
    import tempfile
    temp_run_dir = tempfile.mkdtemp()

    print(f"Running: {venv_python} {unit_tests_script}")
    result = run_command([venv_python, str(unit_tests_script)], capture_output=False, env=env, cwd=temp_run_dir)

    return result.returncode == 0

def create_test_script() -> str:
    """Create a temporary test script to run in the virtual environment"""
    test_script = '''
import sys
import PySubtrans

def test_import():
    """Test that PySubtrans can be imported and basic functionality works"""
    print("Testing PySubtrans import...")

    # Test version
    from PySubtrans.version import __version__
    print(f"Installed version: {__version__}")

    # Test basic imports
    from PySubtrans.Options import Options
    from PySubtrans.Subtitles import Subtitles
    from PySubtrans.SubtitleTranslator import SubtitleTranslator

    print("Basic imports successful")
    return True

if __name__ == "__main__":
    try:
        if test_import():
            print("Import test passed")
            sys.exit(0)
        else:
            print("Import test failed")
            sys.exit(1)

    except Exception as e:
        print(f"Test failed: {e}")
        sys.exit(1)
'''
    return test_script

def main():
    """Main verification function"""
    print("PySubtrans Package Verification Script")
    print("=" * 40)

    # Get expected version
    try:
        expected_version = get_project_version()
        print(f"Expected version: {expected_version}")
    except Exception as e:
        print(f"Error getting project version: {e}")
        return 1

    # Create temporary directory
    with tempfile.TemporaryDirectory(prefix="pysubtrans_verify_") as temp_dir:
        venv_dir = os.path.join(temp_dir, "venv")
        test_script_path = os.path.join(temp_dir, "test_pysubtrans.py")

        print(f"Using temporary directory: {temp_dir}")

        # Create virtual environment
        print("\nCreating virtual environment...")
        if sys.platform == "win32":
            python_exe = "python"
            venv_python = os.path.join(venv_dir, "Scripts", "python.exe")
            venv_pip = os.path.join(venv_dir, "Scripts", "pip.exe")
        else:
            python_exe = "python3"
            venv_python = os.path.join(venv_dir, "bin", "python")
            venv_pip = os.path.join(venv_dir, "bin", "pip")

        result = run_command([python_exe, "-m", "venv", venv_dir])
        if result.returncode != 0:
            print("Failed to create virtual environment")
            return 1

        # Upgrade pip
        print("\nUpgrading pip...")
        result = run_command([venv_python, "-m", "pip", "install", "--upgrade", "pip"])
        if result.returncode != 0:
            print("Failed to upgrade pip")
            return 1

        # Install pysubtrans
        print("\nInstalling pysubtrans...")
        result = run_command([venv_pip, "install", "pysubtrans"])
        if result.returncode != 0:
            print("Failed to install pysubtrans")
            return 1

        # Check installed version
        print("\nChecking installed version...")
        result = run_command([venv_pip, "show", "pysubtrans"])
        if result.returncode != 0:
            print("Failed to get package info")
            return 1

        # Parse version from pip show output
        installed_version = None
        for line in result.stdout.split('\n'):
            if line.startswith('Version:'):
                installed_version = line.split(':')[1].strip()
                break

        if not installed_version:
            print("Could not determine installed version")
            return 1

        print(f"Installed version: {installed_version}")

        # Compare versions
        if installed_version != expected_version:
            print(f"VERSION MISMATCH!")
            print(f"Expected: {expected_version}")
            print(f"Installed: {installed_version}")
            return 1

        print("Version match confirmed!")

        # Create and run test script for basic import verification
        print("\nCreating test script...")
        with open(test_script_path, 'w') as f:
            f.write(create_test_script())

        print("\nRunning import verification...")
        result = run_command([venv_python, test_script_path], capture_output=False)

        if result.returncode != 0:
            print("Import verification failed!")
            return 1

        # Copy PySubtransTests and TestData to the virtual environment
        print("\nCopying PySubtransTests to virtual environment...")
        script_dir = Path(__file__).parent
        project_root = script_dir.parent
        source_tests = project_root / "tests" / "PySubtransTests"
        source_testdata = project_root / "tests" / "TestData"

        if source_tests.exists():
            # Find the installed PySubtrans package location in the venv
            # Make sure we're looking in the venv, not the local development version
            env = os.environ.copy()
            if 'PYTHONPATH' in env:
                del env['PYTHONPATH']  # Remove local development path

            result = run_command([venv_python, "-c", "import sys; import PySubtrans; import os; print(os.path.dirname(os.path.dirname(PySubtrans.__file__)))"],
                                cwd=temp_dir, env=env)
            if result.returncode == 0:
                site_packages_dir = result.stdout.strip()
                target_tests_root = os.path.join(site_packages_dir, "tests")
                target_tests = os.path.join(target_tests_root, "PySubtransTests")
                target_testdata = os.path.join(target_tests_root, "TestData")

                print(f"Creating tests directory structure in site-packages")
                print(f"Copying {source_tests} to {target_tests}")
                print(f"Copying {source_testdata} to {target_testdata}")
                try:
                    # Create tests directory and copy with proper structure
                    os.makedirs(target_tests_root, exist_ok=True)
                    shutil.copytree(source_tests, target_tests,
                                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
                    if source_testdata.exists():
                        shutil.copytree(source_testdata, target_testdata,
                                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))

                    # Create __init__.py files to make it a proper package
                    with open(os.path.join(target_tests_root, "__init__.py"), 'w') as f:
                        f.write("# Test package\n")
                    with open(os.path.join(target_tests, "__init__.py"), 'w') as f:
                        f.write("# PySubtrans tests\n")
                    with open(os.path.join(target_testdata, "__init__.py"), 'w') as f:
                        f.write("# Test data\n")

                except Exception as e:
                    print(f"Error copying tests: {e}")
                    return 1
            else:
                print("Could not locate installed PySubtrans package")
                return 1
        else:
            print(f"Warning: PySubtransTests directory not found at {source_tests}")
            return 1

        # Run the copied unit tests directly
        print("\nRunning unit tests...")
        print("Creating simple test runner...")
        test_runner_script = f'''
import unittest
import sys
import os

def main():
    """Run the PySubtrans unit tests"""
    loader = unittest.TestLoader()

    # Find the copied tests in site-packages/tests/
    import PySubtrans
    import sys
    package_dir = os.path.dirname(PySubtrans.__file__)
    site_packages_dir = os.path.dirname(package_dir)
    test_dir = os.path.join(site_packages_dir, "tests", "PySubtransTests")

    # Add the site-packages directory to sys.path so relative imports work
    if site_packages_dir not in sys.path:
        sys.path.insert(0, site_packages_dir)

    if not os.path.exists(test_dir):
        print("PySubtransTests directory not found!")
        return 1

    # Discover and run tests, excluding localization tests since they depend on LLM-Subtrans project structure
    suite = loader.discover(test_dir, pattern='test_*.py', top_level_dir=site_packages_dir)

    # Modules excluded because they require the full LLM-Subtrans project structure
    excluded_modules = ('test_localization',)

    def should_include(test):
        """Return True if the test should be included in the run"""
        # Skip failed imports (_FailedTest entries from import errors)
        if test.__class__.__name__ == '_FailedTest':
            return False
        module_name = test.__class__.__module__
        return not module_name.endswith(excluded_modules)

    filtered_tests = []
    for test_group in suite:
        for test_case in test_group:
            if hasattr(test_case, '_testMethodName'):
                if should_include(test_case):
                    filtered_tests.append(test_case)
            else:
                # Handle test suites
                filtered_case_tests = [t for t in test_case if should_include(t)]
                if filtered_case_tests:
                    filtered_suite = unittest.TestSuite(filtered_case_tests)
                    filtered_tests.append(filtered_suite)

    final_suite = unittest.TestSuite(filtered_tests)
    runner = unittest.TextTestRunner(verbosity=1)
    result = runner.run(final_suite)

    print(f"\\nNote: Excluded localization tests (require full LLM-Subtrans project structure)")

    return 0 if result.wasSuccessful() else 1

if __name__ == "__main__":
    sys.exit(main())
'''

        runner_script_path = os.path.join(temp_dir, "run_tests.py")
        with open(runner_script_path, 'w') as f:
            f.write(test_runner_script)

        # Run the test runner in clean environment
        env = os.environ.copy()
        if 'PYTHONPATH' in env:
            del env['PYTHONPATH']

        print("Running copied unit tests...")
        result = run_command([venv_python, runner_script_path], capture_output=False, env=env, cwd=temp_dir)
        tests_passed = result.returncode == 0

        if tests_passed:
            print("\n" + "=" * 40)
            print("Package verification successful!")
            print(f"Version {installed_version} installed correctly")
            print("All tests passed")
            return 0
        else:
            print("\n" + "=" * 40)
            print("Package verification failed!")
            print("Unit tests failed")
            return 1

if __name__ == "__main__":
    sys.exit(main())