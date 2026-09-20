import copy
import unittest
from unittest.mock import patch
from jev_prune.core import *
from jev_prune.client import evaluate
from jev_prune.worker import handle
from fixtures import pi_messages,openai_messages,opencode_messages,yes,TEXT

class CoreTests(unittest.TestCase):
    def snap(self, msgs=None): return snapshot("pi","s",msgs if msgs is not None else pi_messages())
    def receipt(self,snap=None):
        return assess(snap or self.snap(),[],yes)["receipts"]

    def test_select_exact_duplicate(self):
        s=self.snap(); result=assess(s,[],yes)
        self.assertEqual(result["added"],1)
        self.assertEqual(result["receipts"][0]["source"]["id"],"a")
        self.assertEqual(result["receipts"][0]["witness"]["id"],"b")

    def test_native_source_not_mutated(self):
        original=pi_messages(); before=copy.deepcopy(original); s=self.snap(original)
        out,report=project(s,self.receipt(s))
        self.assertEqual(original,before)
        self.assertEqual(s.messages,before)
        self.assertNotEqual(out[2],before[2])
        self.assertEqual(out[:2]+out[3:],before[:2]+before[3:])
        self.assertGreater(report["body_bytes_removed"],0)

    def test_current_turn_protected(self):
        m=pi_messages(); m[5]={"role":"assistant","content":[{"type":"text","text":"no new user"}]}
        self.assertEqual(assess(self.snap(m),[],yes)["added"],0)

    def test_recent_protected(self):
        self.assertEqual(assess(self.snap(pi_messages()[:7]),[],yes)["added"],0)

    def test_not_exact_duplicate_retained(self):
        m=pi_messages(); m[4]["content"][0]["text"]+=" changed"
        self.assertEqual(assess(self.snap(m),[],yes)["added"],0)

    def test_side_effecting_tools_not_selected(self):
        m=pi_messages()
        for i in (1,3): m[i]["content"][0]["name"]="bash"
        self.assertEqual(assess(self.snap(m),[],yes)["added"],0)

    def test_missing_explicit_pi_success_retained(self):
        m=pi_messages(); del m[2]["isError"]
        self.assertEqual(assess(self.snap(m),[],yes)["added"],0)

    def test_failed_witness_retained(self):
        m=pi_messages(); m[4]["isError"]=True
        self.assertEqual(assess(self.snap(m),[],yes)["added"],0)

    def test_duplicate_ids_disqualified(self):
        m=pi_messages(); m.insert(3,copy.deepcopy(m[2]))
        self.assertEqual(assess(self.snap(m),[],yes)["added"],0)

    def test_multimodal_retained(self):
        m=pi_messages(); m[2]["content"].append({"type":"image","data":"x"})
        self.assertEqual(assess(self.snap(m),[],yes)["added"],0)

    def test_secret_veto(self):
        m=pi_messages()
        for i in (2,4): m[i]["content"][0]["text"]+=" password=private"
        self.assertEqual(assess(self.snap(m),[],yes)["added"],0)

    def test_oversized_goal_not_truncated(self):
        m=pi_messages(); m[5]["content"]="a"*(MAX_TEXT+1)
        self.assertEqual(assess(self.snap(m),[],yes)["added"],0)

    def test_unknown_latest_user_content_invalidates_goal(self):
        m=pi_messages(); m[5]["content"]=[{"type":"image","data":"x"}]
        self.assertEqual(assess(self.snap(m),[],yes)["added"],0)

    def test_oversized_result_not_truncated(self):
        m=pi_messages()
        for i in (2,4): m[i]["content"][0]["text"]="a"*(MAX_TEXT+1)
        self.assertEqual(assess(self.snap(m),[],yes)["added"],0)

    def test_session_bound_receipt(self):
        with self.assertRaises(PruneError): project(snapshot("pi","other",pi_messages()),self.receipt())

    def test_changed_payload_does_not_apply(self):
        m=pi_messages(); m[2]["content"][0]["text"]+="new"
        out,r=project(self.snap(m),self.receipt())
        self.assertEqual(out,m); self.assertEqual(r["invalid"],1)

    def test_missing_witness_does_not_apply(self):
        m=pi_messages(); del m[4]
        out,r=project(self.snap(m),self.receipt())
        self.assertEqual(out,m); self.assertEqual(r["invalid"],1)

    def test_missing_source_is_inactive(self):
        m=pi_messages(); del m[2]
        _,r=project(self.snap(m),self.receipt())
        self.assertEqual(r["inactive"],1)

    def test_already_pruned_does_not_reassess(self):
        calls=[]
        def no(body): calls.append(body); return yes(body)
        result=assess(self.snap(),self.receipt(),no)
        self.assertEqual(result["added"],0); self.assertEqual(calls,[])

    def test_response_probabilities_strict(self):
        body,_=prepare(self.snap(),[])
        for value in (True,False,None,"0.99",float("nan"),float("inf"),-1,1.01):
            with self.subTest(value=value):
                response=yes(body); response["answers"]["c0_coverage"]["noul"]=value
                with self.assertRaises(PruneError): validate_answers(body,response)

    def test_wrong_model_rejected(self):
        body,_=prepare(self.snap(),[]); response=yes(body); response["model"]="jev-latest"
        with self.assertRaises(PruneError): validate_answers(body,response)

    def test_missing_answer_rejected(self):
        body,_=prepare(self.snap(),[]); response=yes(body); response["answers"].pop("c0_unique")
        with self.assertRaises(PruneError): validate_answers(body,response)

    def test_uncertain_answer_retains(self):
        def uncertain(body):
            r=yes(body); r["answers"]["c0_coverage"]["noul"]=.9; return r
        self.assertEqual(assess(self.snap(),[],uncertain)["added"],0)

    def test_duplicate_json_rejected(self):
        for raw in ('{"a":1,"a":2}', '{"x":NaN}', '{"x":Infinity}'):
            with self.assertRaises(PruneError): strict_json(raw)

    def test_no_candidates_no_api_call(self):
        def broken(_): raise AssertionError("Should not be called")
        self.assertEqual(assess(self.snap([]),[],broken)["added"],0)

    def test_remote_opt_in_required(self):
        with patch.dict("os.environ",{},clear=True):
            with self.assertRaises(PruneError): evaluate({})

    def test_missing_key_no_network(self):
        with patch.dict("os.environ",{"JEV_PRUNE_ALLOW_REMOTE":"1"},clear=True):
            with self.assertRaises(PruneError): evaluate({})

    def test_openai_format_projection(self):
        m=openai_messages(); s=snapshot("openai","s",m)
        result=assess(s,[],yes); out,report=project(s,result["receipts"])
        self.assertEqual(report["applied"],1); self.assertEqual(out[2]["tool_call_id"],"a")
        self.assertEqual(out[:2]+out[3:],m[:2]+m[3:])

    def test_opencode_format_projection(self):
        m=opencode_messages(); s=snapshot("opencode","s",m)
        result=assess(s,[],yes); out,report=project(s,result["receipts"])
        self.assertEqual(report["applied"],1)
        self.assertEqual(out[2]["parts"][0]["state"]["input"],m[2]["parts"][0]["state"]["input"])
        self.assertEqual(out[:2]+out[3:],m[:2]+m[3:])

    def test_rpc_inspection_no_network(self):
        with patch("jev_prune.client.evaluate",side_effect=AssertionError("network")):
            result=handle({"schema":"jev-prune.rpc.v1","op":"inspect","format":"pi","session":"s","messages":pi_messages()})
        self.assertEqual(result["result"]["eligible_pairs"],1)
        self.assertFalse(result["result"]["remote_called"])

    def test_unknown_format_no_guess(self):
        with self.assertRaises(PruneError): snapshot("codex-rollout","s",[])

    def test_receipt_dependency_conflict(self):
        r=self.receipt(); second=copy.deepcopy(r[0]); second["source"],second["witness"]=second["witness"],second["source"]
        with self.assertRaises(PruneError): project(self.snap(),r+[second])

    def test_request_bound(self):
        body,_=prepare(self.snap(),[])
        self.assertLessEqual(len(dumps(body).encode()),MAX_REQUEST)
    def test_control_characters_in_native_ids_disqualified(self):
        m=pi_messages()
        m[1]["content"][0]["id"]="a\nunsafe"; m[2]["toolCallId"]="a\nunsafe"
        self.assertEqual(assess(self.snap(m),[],yes)["added"],0)
