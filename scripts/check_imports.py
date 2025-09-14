import sys
import importlib.util

def check_required_imports(modules: list[str], pip_extras: str|None = None) -> None:
    """Check if required modules are available and exit with helpful message if not"""
    missing_modules = []
    for module_name in modules:
        if importlib.util.find_spec(module_name) is None:
            missing_modules.append(module_name)
    
    if missing_modules:
        print("Error: Required modules not found (installation method has changed)")
        if pip_extras:
            print(f"Please run the install script or `pip install .[{pip_extras}]`")
        else:
            print("Please run the install script or `pip install .`")
        sys.exit(1)