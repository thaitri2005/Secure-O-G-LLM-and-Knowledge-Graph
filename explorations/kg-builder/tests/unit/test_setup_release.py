"""Pinned-clone setup refuses drift and does not rewrite its lock."""
import csv
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE=Path(__file__).resolve().parents[2]/'scripts/clone_repos.py'
spec=importlib.util.spec_from_file_location('publication_clone',SOURCE)
clone=importlib.util.module_from_spec(spec)
spec.loader.exec_module(clone)


class PinnedSetupTest(unittest.TestCase):
    def fixture(self,folder):
        root=Path(folder)
        lock=root/'configs/runtime/repos.lock.csv';lock.parent.mkdir(parents=True)
        lock.write_text('name,url,sha,status\nexample,https://github.com/example/project,'+'a'*40+',ok\n',encoding='utf-8')
        return root,lock

    def test_clone_checks_out_exact_commit_and_keeps_lock(self):
        with tempfile.TemporaryDirectory() as folder:
            root,lock=self.fixture(folder);before=lock.read_bytes();calls=[]
            def git(*args):
                calls.append(args)
                if args[-2:]==('rev-parse','HEAD'):return 'a'*40
                return ''
            with patch.object(clone,'ROOT',root),patch.object(clone,'git',side_effect=git):
                self.assertEqual(clone.run(),1)
            self.assertTrue(any(args[-3:]==('checkout','--detach','a'*40) for args in calls))
            self.assertEqual(lock.read_bytes(),before)

    def test_verify_missing_clone_never_uses_network(self):
        with tempfile.TemporaryDirectory() as folder:
            root,_=self.fixture(folder)
            with patch.object(clone,'ROOT',root),patch.object(clone,'git') as git:
                with self.assertRaisesRegex(RuntimeError,'Missing pinned clone'):clone.run(True)
                git.assert_not_called()

    def test_existing_head_drift_is_rejected_without_checkout(self):
        with tempfile.TemporaryDirectory() as folder:
            root,lock=self.fixture(folder);(root/'third_party/example').mkdir(parents=True)
            before=lock.read_bytes()
            with patch.object(clone,'ROOT',root),patch.object(clone,'git',side_effect=['b'*40,'']) as git:
                with self.assertRaisesRegex(RuntimeError,'mismatch'):clone.run()
                self.assertEqual(git.call_count,2)
            self.assertEqual(lock.read_bytes(),before)

    def test_dirty_existing_clone_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root,_=self.fixture(folder);(root/'third_party/example').mkdir(parents=True)
            with patch.object(clone,'ROOT',root),patch.object(clone,'git',side_effect=['a'*40,'!! cache/']):
                with self.assertRaisesRegex(RuntimeError,'dirty tree'):clone.run(True)


class RequirementVerificationTest(unittest.TestCase):
    def setUp(self):
        source=SOURCE.with_name('verify_requirements.py')
        spec=importlib.util.spec_from_file_location('publication_requirements',source)
        self.verify=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.verify)

    def test_bom_and_inactive_platform_pins(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'requirements.txt'
            path.write_text('example==1.2.3\nabsent==9; python_version < "2"\n',encoding='utf-8-sig')
            with patch.object(self.verify.importlib.metadata,'version',return_value='1.2.3') as version:
                self.verify.verify(path)
                version.assert_called_once_with('example')

    def test_installed_version_drift_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'requirements.txt'
            path.write_text('example==1.2.3\n',encoding='utf-8')
            with patch.object(self.verify.importlib.metadata,'version',return_value='1.2.4'):
                with self.assertRaisesRegex(RuntimeError,'does not satisfy'):
                    self.verify.verify(path)
