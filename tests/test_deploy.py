import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which('git') and shutil.which('bash'), 'requires git and bash')
class DeploymentTests(unittest.TestCase):
    def run_release(self, failure):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'scripts').mkdir()
            (root / 'data').mkdir()
            (root / 'src' / 'shopping_bot').mkdir(parents=True)
            (root / 'src' / 'shopping_bot' / '__init__.py').write_text('__version__ = \"0.2.0\"\n')
            (root / 'bin').mkdir()
            script = root / 'scripts' / 'deploy.sh'
            shutil.copyfile(Path(__file__).resolve().parents[1] / 'scripts' / 'deploy.sh', script)
            subprocess.run(['git', 'init', '-q', str(root)], check=True)
            subprocess.run(['git', '-C', str(root), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '--allow-empty', '-qm', 'test'], check=True)
            docker = root / 'bin' / 'docker'
            docker.write_text('''#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$DOCKER_TEST_LOG"
case "$*" in
  'compose ps -q bot') echo test-container ;;
  'inspect test-container --format {{.Image}}') echo previous-image ;;
  *'/healthz'*) [[ "$DEPLOY_TEST_FAILURE" != 'health' ]] ;;
  *'shopping_bot.backup'*) [[ "$DEPLOY_TEST_FAILURE" != 'backup' ]] ;;
  *) exit 0 ;;
esac
''')
            docker.chmod(0o700)
            sleep = root / 'bin' / 'sleep'
            sleep.write_text('#!/bin/sh\nexit 0\n')
            sleep.chmod(0o700)
            log = root / 'docker.log'
            env = dict(os.environ, PATH=str(root / 'bin') + os.pathsep + os.environ['PATH'], DOCKER_TEST_LOG=str(log), DEPLOY_TEST_FAILURE=failure)
            result = subprocess.run(['bash', str(script)], env=env, capture_output=True, text=True)
            return result.returncode, log.read_text(), (root / 'data' / 'deployments.log').exists()

    def test_success_records_release_without_restarting_tunnel(self):
        code, log, recorded = self.run_release('none')
        self.assertEqual(code, 0)
        self.assertTrue(recorded)
        self.assertNotIn('tunnel', log)
        self.assertIn('compose up -d --no-deps bot', log)
        self.assertIn('--build-arg APP_COMMIT=', log)
        self.assertIn('--build-arg APP_RELEASE=0.2.0-dev+', log)
        self.assertIn('Running image identity differs from release', log)

    def test_failed_health_restores_previous_image_without_restoring_database(self):
        code, log, recorded = self.run_release('health')
        self.assertEqual(code, 1)
        self.assertFalse(recorded)
        self.assertIn('tag previous-image family-shopping-bot-bot:latest', log)
        self.assertIn('--no-build --no-deps --force-recreate bot', log)
        self.assertNotIn('tunnel', log)

    def test_failed_backup_prevents_build_and_restart(self):
        code, log, recorded = self.run_release('backup')
        self.assertEqual(code, 1)
        self.assertFalse(recorded)
        self.assertNotIn('compose build', log)
        self.assertNotIn('compose up', log)
