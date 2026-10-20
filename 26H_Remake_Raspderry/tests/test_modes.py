"""Mode entry has one reply; normal data has no command ACK machinery."""

from concurrent.futures import Future
import unittest

from ballbeam.communication.session import ModeRequest
from ballbeam.communication.protocol import Mode, ModeReply


class ModeRequestTests(unittest.TestCase):
    def test_only_matching_reply_selects_mode(self):
        state = ModeRequest()
        reply = Future()
        state.begin(Mode.TUNING, reply, 1)
        state.receive(ModeReply(Mode.RUN, state.seq, 0))
        state.receive(ModeReply(Mode.TUNING, state.seq + 1, 0))
        self.assertFalse(reply.done())
        self.assertEqual(state.current_mode, Mode.NONE)
        state.receive(ModeReply(Mode.TUNING, state.seq, 0))
        self.assertTrue(reply.result())
        self.assertEqual(state.current_mode, Mode.TUNING)

    def test_rejection_and_timeout_do_not_enable_data(self):
        state = ModeRequest()
        reply = Future()
        state.begin(Mode.RUN, reply, 1)
        state.receive(ModeReply(Mode.RUN, state.seq, 1))
        self.assertFalse(reply.result())
        next_reply = Future()
        state.begin(Mode.TUNING, next_reply, 1)
        state.check_timeout(state.deadline)
        self.assertFalse(next_reply.result())
        state.receive(ModeReply(Mode.TUNING, state.seq, 0))
        self.assertEqual(state.current_mode, Mode.NONE)

    def test_second_pending_selection_is_rejected(self):
        state = ModeRequest()
        first, second = Future(), Future()
        state.begin(Mode.RUN, first, 1)
        self.assertFalse(state.begin(Mode.TUNING, second, 1))
        self.assertFalse(second.result())
        self.assertFalse(first.done())
        state.fail("stopped")
        self.assertFalse(first.result())
