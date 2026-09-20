import io
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch
from jev_prune.installer import *
from jev_prune.fsutil import ReceiptStore, atomic_write

SOURCE=Path(__file__).resolve().parents[1]

class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name)/"home with spaces"; self.data=self.home/".jev-prune"
    def run_cli(self, *argv):
        out,err=io.StringIO(),io.StringIO()
        with patch.dict(os.environ,{},clear=True),redirect_stdout(out),redirect_stderr(err):
            code=main(["--home",str(self.home),*argv])
        return code,out.getvalue(),err.getvalue()
    def plan(self,exp=False):
        roots=list(root_paths(self.home,{}).items())
        return build_plan(SOURCE,self.data,roots,exp,False,sys.executable)
    def test_plan_writes_nothing(self):
        code,out,_=self.run_cli("--all")
        self.assertEqual(code,0); self.assertFalse(self.home.exists()); self.assertFalse(json.loads(out)["applied"])
    def test_all_ten_targets(self):
        writes,targets=self.plan()
        self.assertEqual(set(t["harness"] for t in targets),set(TARGETS))
        self.assertTrue(all(not t["native_prune_command"] for t in targets))
    def test_env_roots(self):
        env={"CLAUDE_CONFIG_DIR":str(self.home/"profile1"),"HERMES_HOME":str(self.home/"profile2"),"XDG_CONFIG_HOME":str(self.home/"xdg")}
        roots=root_paths(self.home,env)
        self.assertEqual(roots["claude"],self.home/"profile1")
        self.assertEqual(roots["hermes"],self.home/"profile2")
        self.assertEqual(roots["opencode"],self.home/"xdg"/"opencode")
    def test_current_codex_user_skill_root(self):
        self.assertEqual(root_paths(self.home,{"CODEX_HOME":str(self.home/"auth-only")})["codex"],self.home/".agents")
    def test_install_idempotent(self):
        tx=Transaction(self.data); writes,targets=self.plan(True)
        report=tx.apply(writes,targets)
        self.assertTrue(any(x["action"]=="create" for x in report["actions"]))
        report=tx.apply(writes,targets)
        self.assertTrue(all(x["action"]=="unchanged" for x in report["actions"]))
        self.assertTrue((self.home/".claude/skills/jev-prune/SKILL.md").is_file())
    def test_native_wrappers(self):
        writes,targets=self.plan(True); Transaction(self.data).apply(writes,targets)
        self.assertTrue((self.home/".pi/agent/extensions/jev-prune.ts").is_file())
        self.assertTrue((self.home/".config/opencode/plugins/jev-prune.ts").is_file())
        self.assertTrue((self.home/".hermes/plugins/jev-prune/__init__.py").is_file())
        self.assertEqual(sum(t["native_prune_command"] for t in targets),3)
    def test_foreign_file_not_replaced(self):
        dest=self.home/".claude/skills/jev-prune/SKILL.md"; atomic_write(dest,b"mine")
        writes,targets=self.plan()
        with self.assertRaises(PruneError): Transaction(self.data).apply(writes,targets)
        self.assertEqual(dest.read_bytes(),b"mine")
        self.assertFalse((self.data/"runtime/runner.py").exists())
    def test_modified_owned_file_not_overwritten(self):
        writes,targets=self.plan(); tx=Transaction(self.data); tx.apply(writes,targets)
        dest=self.home/".claude/skills/jev-prune/SKILL.md"; dest.write_bytes(b"user edit")
        with self.assertRaises(PruneError): tx.apply(writes,targets)
        self.assertEqual(dest.read_bytes(),b"user edit")
    def test_backup_on_upgrade(self):
        tx=Transaction(self.data); p=self.home/"file"
        tx.apply([Write(p,b"v1","test")],[]); tx.apply([Write(p,b"v2","test")],[])
        self.assertEqual(p.read_bytes(),b"v2")
        self.assertIn(b"v1",[f.read_bytes() for f in (self.data/"backups").glob("*.bak")])
    def test_uninstall_preserves_user_edit(self):
        tx=Transaction(self.data); p=self.home/"mine"; q=self.home/"untouched"
        tx.apply([Write(p,b"v1","test"),Write(q,b"v1","test")],[]); p.write_bytes(b"edited")
        tx.uninstall(True)
        self.assertEqual(p.read_bytes(),b"edited"); self.assertFalse(q.exists())
    def test_uninstall_plan_no_mutation(self):
        tx=Transaction(self.data); p=self.home/"file"; tx.apply([Write(p,b"v1","test")],[])
        tx.uninstall(False); self.assertTrue(p.exists())
    def test_symlink_destination_rejected(self):
        self.home.mkdir(); link=self.home/"link"
        try: link.symlink_to(self.home,target_is_directory=True)
        except OSError: self.skipTest("symlinks unavailable")
        with self.assertRaises(PruneError): Transaction(self.data).validate([Write(link/"owned",b"data","test")],{"files":{}})
    def test_profiles_additive(self):
        code,_,err=self.run_cli("--root",f"claude={self.home/'a'}","--root",f"claude={self.home/'b'}","--apply")
        self.assertEqual(code,0,err)
        self.assertTrue((self.home/"a/skills/jev-prune/SKILL.md").is_file())
        self.assertTrue((self.home/"b/skills/jev-prune/SKILL.md").is_file())
    def test_native_flag_required_for_pi_choice(self):
        code,_,_=self.run_cli("--all","--pi-choice")
        self.assertEqual(code,1); self.assertFalse(self.home.exists())
    def test_receipt_storage_cas(self):
        store=ReceiptStore(self.data/"state","profile")
        receipt,ver=store.load("s"); self.assertEqual(receipt,[]); self.assertIsNone(ver)
        store.save("s",[],ver)
        with self.assertRaises(PruneError): store.save("s",[],None)
    def test_no_vendor_configuration_written(self):
        writes,targets=self.plan(True)
        names={w.path.name for w in writes}
        self.assertNotIn("settings.json",names); self.assertNotIn("config.toml",names); self.assertNotIn("config.yaml",names)
    def test_doctor_does_not_claim_live_verification(self):
        code,out,_=self.run_cli("--doctor")
        self.assertEqual(code,0); self.assertFalse(json.loads(out)["live_runtime_verified"])
        self.assertFalse(self.home.exists())
    def test_native_install_cannot_silently_downgrade_report(self):
        code,_,err=self.run_cli("--target","pi","--apply","--experimental-adapters")
        self.assertEqual(code,0,err)
        code,_,err=self.run_cli("--target","pi","--apply")
        self.assertEqual(code,1)
        self.assertIn("Existing native adapter",err)
    def test_modified_wrapper_keeps_runtime_on_uninstall(self):
        tx=Transaction(self.data); runtime=self.data/"runtime/code.py"; wrapper=self.home/"plugin.ts"
        tx.apply([Write(runtime,b"runtime","runtime"),Write(wrapper,b"wrapper","native-wrapper")],[])
        wrapper.write_bytes(b"my edited wrapper")
        tx.uninstall(True)
        self.assertTrue(runtime.exists())
        self.assertEqual(wrapper.read_bytes(),b"my edited wrapper")
