import inspect
import unittest

from cogs.leveling import Leveling
from cogs.voice import Voice


class StateRecoveryTests(unittest.TestCase):
    def test_xp_increment_is_one_atomic_database_statement(self):
        source = inspect.getsource(Leveling.on_message)
        self.assertIn("ON CONFLICT (user_id) DO UPDATE", source)
        self.assertIn("RETURNING xp, level", source)
        self.assertNotIn("SELECT xp, level", source)

    def test_voice_rooms_are_reconstructed_after_reconnect(self):
        ready_source = inspect.getsource(Voice.on_ready)
        update_source = inspect.getsource(Voice.on_voice_state_update)
        self.assertIn("_owner_from_overwrites", ready_source)
        self.assertIn("channel.delete", ready_source)
        self.assertIn("existing", update_source)
        self.assertIn("_owner_id", update_source)


if __name__ == "__main__":
    unittest.main()
