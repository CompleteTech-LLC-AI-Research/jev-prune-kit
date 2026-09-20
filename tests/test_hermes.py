import copy
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fixtures import openai_messages,yes

spec=importlib.util.spec_from_file_location("hermes_adapter",Path(__file__).resolve().parents[1]/"adapters/hermes.py")
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)

class Host:
    def register_middleware(self,name,handler): self.middleware=handler
    def register_command(self,name,handler,**kw): self.command=handler; self.name=name

class HermesTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.ctx=Host(); module.register(self.ctx,{"stateDir":self.tmp.name,"profile":"p"})
    def test_shared_gateway_disabled(self):
        with patch.dict(os.environ,{},clear=True):
            self.assertIn("disabled",self.ctx.command(""))
            self.assertIsNone(self.ctx.middleware({"messages":openai_messages()},session_id="s"))
    def test_single_user_projection(self):
        original=openai_messages(); request={"messages":copy.deepcopy(original),"model":"test"}
        with patch.dict(os.environ,{"JEV_PRUNE_HERMES_SINGLE_USER":"1"},clear=True),patch.object(module.client,"evaluate",yes):
            self.assertIsNone(self.ctx.middleware(request,session_id="s"))
            self.assertIn("approved 1",self.ctx.command(""))
            result=self.ctx.middleware(request,session_id="s")
            self.assertNotEqual(result["request"]["messages"][2],original[2])
            self.assertEqual(request["messages"],original)
            self.assertEqual(result["request"]["model"],"test")
    def test_opaque_lineage_not_supported(self):
        with patch.dict(os.environ,{"JEV_PRUNE_HERMES_SINGLE_USER":"1"},clear=True):
            self.assertIsNone(self.ctx.middleware({"messages":openai_messages(),"previous_response_id":"resp"},session_id="s"))
    def test_no_session_guess_with_multiple(self):
        with patch.dict(os.environ,{"JEV_PRUNE_HERMES_SINGLE_USER":"1"},clear=True):
            self.ctx.middleware({"messages":openai_messages()},session_id="s")
            self.ctx.middleware({"messages":openai_messages()},session_id="t")
            self.assertIn("No unambiguous",self.ctx.command(""))
    def test_api_capabilities_checked(self):
        with self.assertRaises(RuntimeError): module.register(object(),{"stateDir":self.tmp.name,"profile":"p"})
