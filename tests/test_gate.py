import unittest
from jev_prune.gate import *

class FakeHost:
    def __init__(self):
        self.rev="1"; self.eval=0; self.compactions=[]; self.fail=False; self.cas=True
        self.available=Budget(10,5,1,100,10,90,10)
    def revision(self): return self.rev
    def propose_prune(self):
        self.eval+=1
        if self.fail: raise ValueError("failure")
        return "plan"
    def commit_prune(self,expected_revision,plan):
        if not self.cas or expected_revision!=self.rev: return False
        self.rev=str(int(self.rev)+1); return True
    def budget(self): return self.available
    def native_compact(self,trigger): self.compactions.append(trigger)

class GateTests(unittest.TestCase):
    def setUp(self): self.h=FakeHost(); self.g=Gate(self.h)
    def test_manual_compact_unchanged(self):
        self.assertEqual(self.g.manual_compact(),Outcome.COMPACTED)
        self.assertEqual(self.h.eval,0); self.assertEqual(self.h.compactions,["manual"])
    def test_manual_prune_never_compacts(self):
        self.assertEqual(self.g.manual_prune(),Outcome.APPLIED); self.assertEqual(self.h.compactions,[])
    def test_choose_compact_never_evaluates(self):
        self.g.begin("a"); self.assertEqual(self.g.choose("a",Choice.COMPACT),Outcome.COMPACTED)
        self.assertEqual(self.h.eval,0)
    def test_prune_fits(self):
        self.g.begin("a"); self.assertEqual(self.g.choose("a",Choice.PRUNE),Outcome.READY)
        self.assertEqual(self.h.compactions,[])
    def test_insufficient_no_fallback(self):
        self.h.available=Budget(95,5,1,100,95,90,10); self.g.begin("a")
        self.assertEqual(self.g.choose("a",Choice.PRUNE),Outcome.WAITING)
        self.assertEqual(self.h.compactions,[])
        self.assertEqual(self.g.choose("a",Choice.COMPACT),Outcome.COMPACTED)
    def test_missing_budget_waits(self):
        self.h.available=None; self.g.begin("a")
        self.assertEqual(self.g.choose("a",Choice.PRUNE),Outcome.WAITING)
    def test_failure_does_not_authorize_compaction(self):
        self.h.fail=True; self.g.begin("a")
        self.assertEqual(self.g.choose("a",Choice.PRUNE),Outcome.WAITING)
        self.assertEqual(self.h.compactions,[])
    def test_pause_no_calls(self):
        self.g.begin("a"); self.assertEqual(self.g.choose("a",Choice.PAUSE),Outcome.PAUSED)
        self.assertEqual(self.h.eval,0); self.assertEqual(self.h.compactions,[])
    def test_duplicate_choice_rejected(self):
        self.g.begin("a"); self.g.choose("a",Choice.COMPACT)
        self.assertEqual(self.g.choose("a",Choice.COMPACT),Outcome.STALE)
        self.assertEqual(len(self.h.compactions),1)
    def test_stale_revision(self):
        self.g.begin("a"); self.h.rev="new"
        self.assertEqual(self.g.choose("a",Choice.PRUNE),Outcome.STALE)
        self.assertEqual(self.h.eval,0)
    def test_cas_failure(self):
        self.h.cas=False; self.g.begin("a")
        self.assertEqual(self.g.choose("a",Choice.PRUNE),Outcome.STALE)
        self.assertEqual(self.h.compactions,[])
    def test_one_episode_no_duplicate_popup(self):
        self.assertIs(self.g.begin("a"),self.g.begin("b"))
    def test_no_progress_repeat_refused(self):
        self.h.available=None; self.g.begin("a"); self.g.choose("a",Choice.PRUNE)
        with self.assertRaises(PruneError): self.g.choose("a",Choice.PRUNE)
    def test_budget_strict(self):
        self.assertFalse(Budget(True,0,0,100,1,100,1).fits())
        self.assertFalse(Budget(1,0,0,100,99,100,1).fits())
        self.assertFalse(Budget(-1,0,0,100,1,100,1).fits())

    def test_stale_episode_can_be_replaced(self):
        old=self.g.begin("a"); self.h.rev="new"
        self.assertEqual(self.g.choose("a",Choice.PRUNE),Outcome.STALE)
        self.assertIsNot(old,self.g.begin("b"))
