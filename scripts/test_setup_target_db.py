import importlib.util
import unittest
from pathlib import Path
from unittest.mock import mock_open, patch

spec = importlib.util.spec_from_file_location('seed', Path(__file__).with_name('setup_target_db.py'))
seed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(seed)

class SeedContainerTest(unittest.TestCase):
    def test_uses_compose_container_and_configured_user(self):
        with patch.object(seed, 'run_cmd', side_effect=[(True, 'actual-container\n'), (True, 'postgres\n')]) as run:
            container, user = seed.get_postgres_container()
        self.assertEqual((container, user), ('actual-container', 'postgres'))
        self.assertIn('compose', run.call_args_list[0].args[0])
        self.assertEqual(run.call_args_list[1].args[0], ['docker', 'exec', 'actual-container', 'printenv', 'POSTGRES_USER'])

    def test_missing_container_stops_before_seed(self):
        with patch.object(seed, 'run_cmd', return_value=(True, '')) as run:
            with self.assertRaises(SystemExit):
                seed.get_postgres_container()
        self.assertEqual(run.call_count, 1)

    def test_seed_commands_use_resolved_container_and_user(self):
        with (
            patch.object(seed, 'run_cmd', return_value=(True, '')) as run,
            patch.object(seed, 'get_postgres_container', return_value=('actual-container', 'postgres')),
            patch.object(seed.os.path, 'exists', return_value=True),
            patch('builtins.open', mock_open(read_data='-- fixture SQL')),
            patch('builtins.print'),
        ):
            seed.main()
        self.assertEqual(run.call_count, 5)
        for call in run.call_args_list:
            command = call.args[0]
            self.assertEqual(command[:4], ['docker', 'exec', '-i', 'actual-container'])
            self.assertEqual(command[command.index('-U') + 1], 'postgres')
            self.assertIn('ON_ERROR_STOP=1', command)

if __name__ == '__main__':
    unittest.main()
