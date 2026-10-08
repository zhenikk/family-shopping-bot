import io
import sqlite3
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shopping_bot.backup import backup, verify_archive
from shopping_bot.store import Store


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.output = self.root / 'backups'
        self.store = Store(self.root / 'shopping.sqlite3')
        self.store.join(1, 'User')
        self.store.add_need(self.store.ensure_product('Milk'), 1)

    def tearDown(self):
        self.temporary.cleanup()

    def test_private_verified_snapshots_have_bounded_retention(self):
        archives = [backup(self.root, self.output, keep=2) for _ in range(3)]
        self.assertEqual(len(list(self.output.glob('*.tar.gz'))), 2)
        self.assertEqual(archives[-1].stat().st_mode & 0o777, 0o600)
        self.assertEqual(verify_archive(archives[-1])['databases'], 1)
        self.assertFalse(list(self.output.glob('*.partial')))

    def test_failed_verification_never_publishes_or_deletes_previous_copy(self):
        original = backup(self.root, self.output, keep=1)
        with patch('shopping_bot.backup.verify_archive', side_effect=ValueError('corrupt')):
            with self.assertRaises(ValueError):
                backup(self.root, self.output, keep=1)
        self.assertEqual(list(self.output.glob('*.tar.gz')), [original])
        self.assertFalse(list(self.output.glob('.backup-*.partial')))

    def test_restore_verification_rejects_traversal_links_and_corrupt_database(self):
        for name, kind in (('../outside', 'file'), ('link', 'link'), ('shopping.sqlite3', 'file')):
            archive = self.root / 'unsafe.tar.gz'
            with tarfile.open(archive, 'w:gz') as tar:
                entry = tarfile.TarInfo(name)
                if kind == 'link':
                    entry.type = tarfile.SYMTYPE
                    entry.linkname = '/etc/passwd'
                    tar.addfile(entry)
                else:
                    entry.size = 3
                    tar.addfile(entry, io.BytesIO(b'bad'))
            with self.assertRaises((ValueError, sqlite3.DatabaseError)):
                verify_archive(archive)
            self.assertFalse((self.root / 'outside').exists())
