"""Shared harness of the attached-part surface smokes (smoke_attached_part_closed, _seam, _shading, _junction,
_window) — not a smoke itself: the leading underscore keeps it out of run_smokes.py's ``smoke_*`` glob.

Each of those smokes builds its fixture INSIDE Blender (its own ``blender_side(scripts, directory)``), once with the
current ``app/blender/scripts`` and once with the scripts of a pinned old commit, and judges the JSON the Blender side
writes. The three pieces they had in five copies live here:

    run_blender(__file__, scripts, directory, "seam.json")   # one niced Blender run of the smoke file itself
    old_scripts(Path(directory) / "old-scripts", OLD_COMMIT)  # the builder as of that commit, from git
    blender_entry(blender_side, main)                         # the ``__main__`` dispatch (Blender side / host side)

Only the standard library is used, so the module imports inside Blender's Python as well.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BLENDER = Path.home() / 'tools/blender-5.2.2-linux-x64/blender'


def run_blender(smoke_file, scripts, directory, result_name):
    """Run ``smoke_file`` inside Blender (``--blender scripts directory``) and return the JSON it wrote to
    ``directory/result_name``; a failed run prints the log tail and exits with Blender's code."""
    env = {**os.environ, 'OMP_NUM_THREADS': '2', 'OPENBLAS_NUM_THREADS': '1', 'PYTHONUNBUFFERED': '1'}
    Path(directory).mkdir()
    log = Path(directory) / 'blender.log'
    with log.open('w') as stream:
        result = subprocess.run(['nice', '-n', '15', 'timeout', '900', str(BLENDER), '-b', '-noaudio', '--factory-startup',
                                 '--python-exit-code', '1', '--python', str(Path(smoke_file).resolve()), '--',
                                 '--blender', scripts, directory], stdout=stream, stderr=subprocess.STDOUT, env=env)
    if result.returncode:
        print(log.read_text()[-6000:])
        raise SystemExit(result.returncode)
    return json.loads((Path(directory) / result_name).read_text())


def old_scripts(target, commit, names=('attached_part.py', '_common.py')):
    """Write the Blender scripts ``names`` as of ``commit`` into the new directory ``target`` and return it."""
    target = Path(target)
    target.mkdir()
    for name in names:
        source = subprocess.run(['git', '-C', str(ROOT), 'show', f'{commit}:app/blender/scripts/{name}'],
                                capture_output=True, text=True, check=True).stdout
        (target / name).write_text(source)
    return target


def blender_entry(blender_side, main):
    """The smoke's ``__main__``: inside Blender run ``blender_side(scripts, directory)`` and hard-exit (the host
    audio destructor stalls otherwise), on the host run ``main()``."""
    if '--blender' in sys.argv:
        try:
            index = sys.argv.index('--blender')
            blender_side(sys.argv[index + 1], sys.argv[index + 2])
        except BaseException:
            import traceback
            traceback.print_exc()
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(1)
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)
    else:
        main()
