"""Import this first in every test: it points the studio at a throw-away ComfyUI folder before config is read.

    python -m unittest discover -s tests -t .          (from the repo root; no ComfyUI and no GPU needed)

tests/live/ and tests/ui/ are separate: they need the real thing and are run by hand.
"""
import atexit
import os
import shutil
import tempfile

ROOT = tempfile.mkdtemp(prefix="h3studio_test_")
os.makedirs(os.path.join(ROOT, "output"))
os.makedirs(os.path.join(ROOT, "input"))
os.environ["COMFYUI_DIR"] = ROOT
os.environ.pop("STUDIO_HOME", None)
os.environ.pop("COMFYUI_OUTPUT", None)
os.environ.pop("COMFYUI_INPUT", None)
atexit.register(shutil.rmtree, ROOT, ignore_errors=True)

from studio import config  # noqa: E402

config.ensure_home()
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def object_info():
    return config.read_json(os.path.join(FIXTURES, "object_info.json"))
