"""Offline host-contract demo with explicitly simulated assessment and budgets."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from jev_prune.gate import Gate, Choice, Budget

class DemoHost:
    def __init__(self): self.rev="1"; self.compact_calls=0; self.jev_calls=0
    def revision(self): return self.rev
    def propose_prune(self): self.jev_calls+=1; return {"simulated":True}
    def commit_prune(self,expected_revision,plan):
        if expected_revision!=self.rev:return False
        self.rev="2";return True
    def budget(self): return Budget(100,10,10,1000,100,800,100)
    def native_compact(self,trigger): self.compact_calls+=1

parser=argparse.ArgumentParser()
parser.add_argument("--choice",choices=[c.value for c in Choice],default="pause")
args=parser.parse_args()
host=DemoHost();gate=Gate(host);gate.begin("demo")
print("SIMULATED HOST — no model or actual harness called")
print("Outcome:",gate.choose("demo",Choice(args.choice)).value)
print("Simulated evaluator calls:",host.jev_calls,"; simulated native compact calls:",host.compact_calls)
