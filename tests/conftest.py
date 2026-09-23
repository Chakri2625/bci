from pathlib import Path
import os
import sys

# Ensure current Day 9 workspace directory is first in sys.path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
    
real_root = os.path.realpath(project_root)
if real_root not in sys.path:
    sys.path.insert(0, real_root)

import inspect
import asyncio

def pytest_pyfunc_call(pyfuncitem):
    if inspect.iscoroutinefunction(pyfuncitem.obj):
        argnames = pyfuncitem._fixtureinfo.argnames
        kwargs = {arg: pyfuncitem.funcargs[arg] for arg in argnames if arg in pyfuncitem.funcargs}
        asyncio.run(pyfuncitem.obj(**kwargs))
        return True


