"""Immutable build identity; Docker bakes it into the image, including rollbacks."""
import json
import logging
from pathlib import Path
from . import __version__


def release():
    try:
        data = json.loads(Path(__file__).with_name('build.json').read_text())
        return {'version': data['version'], 'commit': data['commit']}
    except (OSError, ValueError, KeyError, TypeError):
        return {'version': __version__ + '-dev', 'commit': 'unknown'}


def configure_logging(level='INFO'):
    identity = release()
    factory = logging.getLogRecordFactory()
    def record_factory(*args, **kwargs):
        record = factory(*args, **kwargs)
        record.release_version = identity['version']
        record.release_commit = identity['commit']
        return record
    logging.setLogRecordFactory(record_factory)
    logging.basicConfig(level=level, format='%(asctime)s %(levelname)s [v=%(release_version)s commit=%(release_commit)s] %(name)s: %(message)s')
