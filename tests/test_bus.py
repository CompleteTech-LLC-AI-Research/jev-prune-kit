"""jev-bus contract tests: claims, carrier negotiation, chain order and fail-safety.

These exercise the shared contract from this package's side. The vendored copy is also
checked for drift against the spec's recorded hash, so an edit on one side of the
two-package contract cannot pass silently.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jev_prune import bus  # noqa: E402

PACKAGE = "jev-prune-kit"
OTHER = "jev-context-fabric"


def stage(name, package, priority, claims, hosts=("*",), argv=("noop",)):
    return {"name": name, "package": package, "priority": priority, "claims": list(claims),
            "hosts": list(hosts), "transport": {"kind": "subprocess-json", "argv": list(argv)}}


# The real stage each package registers. Defined symmetrically so this file is identical in
# both repositories apart from the PACKAGE/OTHER swap and the import path.
STAGES = {
    "jev-context-fabric": ("jev-context.view", 200,
                           ["assistant-prose", "message-remove", "system-append"], ("*",)),
    "jev-prune-kit": ("jev-prune.dedup", 100, ["tool-result:read"], ("pi", "opencode", "hermes")),
}


def stage_for(package):
    name, priority, claims, hosts = STAGES[package]
    return stage(name, package, priority, claims, hosts)


class BusHomeCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.previous = os.environ.get("JEV_BUS_HOME")
        os.environ["JEV_BUS_HOME"] = str(self.home)
        self.addCleanup(self.restore)

    def restore(self):
        if self.previous is None:
            os.environ.pop("JEV_BUS_HOME", None)
        else:
            os.environ["JEV_BUS_HOME"] = self.previous

    def own_stage(self):
        return stage_for(PACKAGE)

    def other_stage(self):
        return stage_for(OTHER)

    def carriers_for(self, package):
        return {h: {"rank": bus.carrier_rank(package, h)}
                for h in bus.TRANSFORM_HOSTS if bus.carrier_rank(package, h)}


class ClaimTests(BusHomeCase):
    def test_wildcard_subsumes_its_family(self):
        self.assertTrue(bus.claims_overlap("tool-result:*", "tool-result:read"))
        self.assertTrue(bus.claims_overlap("tool-result:read", "tool-result:*"))

    def test_distinct_claims_do_not_overlap(self):
        self.assertFalse(bus.claims_overlap("tool-result:read", "assistant-prose"))
        self.assertFalse(bus.claims_overlap("system-append", "message-remove"))

    def test_unknown_claim_is_refused_not_ignored(self):
        with self.assertRaises(bus.BusError):
            bus.validate_claims(["tool-result:read", "invent-a-new-class"])

    def test_two_packages_claiming_the_same_class_is_a_hard_failure(self):
        contested = self.own_stage()["claims"][0]
        stages = [self.own_stage(), stage("rival.same", OTHER, 150, [contested])]
        with self.assertRaises(bus.BusError) as caught:
            bus.assert_no_claim_conflict(stages, "opencode")
        self.assertIn("claim conflict", str(caught.exception))

    def test_one_package_may_hold_several_claims(self):
        repeated = self.own_stage()["claims"][0]
        stages = [self.own_stage(), stage("own.extra", PACKAGE, 210, [repeated])]
        bus.assert_no_claim_conflict(stages, "opencode")  # same package: never a conflict

    def test_disjoint_claims_coexist(self):
        bus.assert_no_claim_conflict([self.own_stage(), self.other_stage()], "opencode")


class CarrierTests(BusHomeCase):
    def register_both(self, order):
        for package in order:
            bus.register(package, [stage_for(package)], self.carriers_for(package))
        return {h: bus.carrier_of(h) for h in bus.TRANSFORM_HOSTS}

    def test_carrier_assignment_is_install_order_independent(self):
        forward = self.register_both([PACKAGE, OTHER])
        second = tempfile.TemporaryDirectory()
        self.addCleanup(second.cleanup)
        os.environ["JEV_BUS_HOME"] = str(Path(second.name))
        reverse = self.register_both([OTHER, PACKAGE])
        self.assertEqual(forward, reverse)
        # The assignment the contract's rank table dictates, stated absolutely so this
        # assertion reads the same in both repositories.
        self.assertEqual(forward["opencode"], "jev-context-fabric")  # implements V1 and V2
        self.assertEqual(forward["pi"], "jev-prune-kit")             # sole Pi adapter
        self.assertEqual(forward["hermes"], "jev-prune-kit")         # real request middleware

    def test_lower_rank_defers_and_is_told_who_holds_it(self):
        bus.register(OTHER, [self.other_stage()], {"pi": {"rank": 100}})
        report = bus.register(PACKAGE, [self.own_stage()], {"pi": {"rank": 1}})
        self.assertEqual(report["deferred_to"], {"pi": OTHER})
        self.assertEqual(bus.carrier_of("pi"), OTHER)

    def test_force_carrier_takes_over_and_names_the_previous_holder(self):
        bus.register(OTHER, [self.other_stage()], {"pi": {"rank": 100}})
        report = bus.register(PACKAGE, [self.own_stage()], {"pi": {"rank": 1}}, force_carrier=True)
        self.assertEqual(report["took_over"], {"pi": OTHER})
        self.assertEqual(bus.carrier_of("pi"), PACKAGE)

    def test_a_tie_keeps_the_incumbent(self):
        bus.register(OTHER, [self.other_stage()], {"pi": {"rank": 50}})
        bus.register(PACKAGE, [self.own_stage()], {"pi": {"rank": 50}})
        self.assertEqual(bus.carrier_of("pi"), OTHER)

    def test_a_non_transform_host_cannot_have_a_carrier(self):
        for host in ("claude-code", "codex", "gemini", "cursor", "copilot", "openclaw"):
            with self.assertRaises(bus.BusError):
                bus.register(PACKAGE, [], {host: {"rank": 100}})

    def test_dry_run_reports_without_writing(self):
        report = bus.register(PACKAGE, [self.own_stage()], {"opencode": {"rank": 50}}, dry_run=True)
        self.assertEqual(report["carrier_of"], ["opencode"])
        self.assertFalse(bus.registry_path().exists())

    def test_reregistration_is_idempotent(self):
        for _ in range(3):
            bus.register(PACKAGE, [self.own_stage()], {"opencode": {"rank": 50}})
        self.assertEqual(len(bus.load()["stages"]), 1)

    def test_unregister_vacates_without_reassigning(self):
        bus.register(OTHER, [self.other_stage()], {"pi": {"rank": 100}})
        bus.register(PACKAGE, [self.own_stage()], {"opencode": {"rank": 50}})
        report = bus.unregister(OTHER)
        self.assertEqual(report["released"], ["pi"])
        # The slot is left empty on purpose: the survivor must reinstall to take the hook.
        self.assertIsNone(bus.carrier_of("pi"))
        self.assertEqual(bus.carrier_of("opencode"), PACKAGE)

    def test_unregister_removes_the_file_when_nothing_is_left(self):
        bus.register(PACKAGE, [self.own_stage()], {"opencode": {"rank": 50}})
        bus.unregister(PACKAGE)
        self.assertFalse(bus.registry_path().exists())


class ChainTests(BusHomeCase):
    def setUp(self):
        super().setUp()
        bus.register(OTHER, [self.other_stage()], self.carriers_for(OTHER))
        bus.register(PACKAGE, [self.own_stage()], self.carriers_for(PACKAGE))
        self.messages = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]

    def test_dedup_is_ordered_before_the_view(self):
        names = [s["name"] for s in bus.stages_for("opencode")]
        self.assertEqual(names, ["jev-prune.dedup", "jev-context.view"])

    def test_order_is_by_priority_then_name_not_registration_order(self):
        bus.register("zzz-pkg", [stage("aaa.late", "zzz-pkg", 100, ["message-reorder"])], {})
        names = [s["name"] for s in bus.stages_for("opencode")]
        self.assertEqual(names, ["aaa.late", "jev-prune.dedup", "jev-context.view"])

    def test_each_stage_receives_the_pristine_original(self):
        seen = []

        def invoke(stage_record, request, workspace, budget):
            seen.append(request["original_messages"])
            return {"ok": True, "messages": [{"role": "user", "content": "rewritten"}], "notes": []}

        bus.run_chain("opencode", self.messages, session="s", invoke=invoke)
        self.assertEqual(len(seen), 2)
        for original in seen:
            self.assertEqual(original, self.messages)  # never the upstream stage's output

    def test_a_failing_stage_passes_its_input_through_untouched(self):
        def invoke(stage_record, request, workspace, budget):
            if stage_record["name"].startswith("jev-prune"):
                raise RuntimeError("stage exploded")
            return {"ok": True, "messages": request["messages"] + [{"role": "system", "content": "c"}], "notes": []}

        out, notes, _ = bus.run_chain("opencode", self.messages, session="s", invoke=invoke)
        self.assertEqual(len(out), 3)  # the healthy stage still ran
        self.assertEqual(out[:2], self.messages)  # on the failed stage's own input
        self.assertTrue(any(n["action"] == "passthrough" for n in notes))

    def test_a_declining_stage_changes_nothing(self):
        out, notes, _ = bus.run_chain(
            "opencode", self.messages, session="s",
            invoke=lambda *a: {"ok": False, "error": "nope"})
        self.assertEqual(out, self.messages)
        self.assertEqual(len([n for n in notes if n["action"] == "passthrough"]), 2)

    def test_a_malformed_stage_response_changes_nothing(self):
        for bad in ({"ok": True}, {"ok": True, "messages": "not-a-list"}, "garbage", None):
            out, _, _ = bus.run_chain("opencode", self.messages, session="s", invoke=lambda *a, b=bad: b)
            self.assertEqual(out, self.messages)

    def test_register_refuses_a_conflicting_stage_at_install_time(self):
        with self.assertRaises(bus.BusError):
            bus.register("rogue", [stage("rogue.prose", "rogue", 50, ["assistant-prose"])], {})

    def test_a_claim_conflict_refuses_the_whole_chain_without_raising(self):
        # register() rejects this at install time, so reach the runtime guard the only way
        # it can actually occur: a registry that became conflicting by some other route,
        # such as a hand edit. The chain must decline, not raise into the host's turn.
        registry = bus.load()
        registry["stages"].append(stage("rogue.prose", "rogue", 50, ["assistant-prose"]))
        bus.atomic_write(bus.registry_path(), bus.dumps(registry).encode())
        out, notes, _ = bus.run_chain("opencode", self.messages, session="s",
                                      invoke=lambda *a: {"ok": True, "messages": [], "notes": []})
        self.assertEqual(out, self.messages)
        self.assertEqual(notes[0]["action"], "chain-refused")
        self.assertIn("claim conflict", notes[0]["detail"])

    def test_an_unreadable_registry_degrades_to_passthrough(self):
        bus.registry_path().write_text("{ not json", encoding="utf-8")
        out, notes, _ = bus.run_chain("opencode", self.messages, session="s",
                                      invoke=lambda *a: {"ok": True, "messages": [], "notes": []})
        self.assertEqual(out, self.messages)
        self.assertEqual(notes[0]["action"], "chain-refused")

    def test_the_carrier_tells_every_stage_whether_it_accepts_a_system_append(self):
        seen = []

        def invoke(stage_record, request, workspace, budget):
            seen.append(request["accepts_system_append"])
            return {"ok": True, "messages": request["messages"], "system_append": "EVIDENCE", "notes": []}

        _, _, appends = bus.run_chain("opencode", self.messages, session="s", invoke=invoke)
        self.assertEqual(seen, [True, True])
        self.assertEqual(appends, ["EVIDENCE", "EVIDENCE"])
        seen.clear()
        bus.run_chain("opencode", self.messages, session="s", accepts_system_append=False, invoke=invoke)
        self.assertEqual(seen, [False, False])

    def test_plan_op_never_mutates_messages(self):
        out, _, _ = bus.run_chain(
            "opencode", self.messages, session="s", op="plan",
            invoke=lambda *a: {"ok": True, "messages": [], "notes": [{"action": "x", "count": 1}]})
        self.assertEqual(out, self.messages)


class ContractDriftTests(unittest.TestCase):
    """The contract is vendored into two repositories. Catch a one-sided edit."""

    def files(self):
        root = Path(__file__).resolve().parents[1]
        return {"bus.py": root / "jev_prune" / "bus.py",
                "bus.mjs": root / "adapters" / "bus.mjs"}

    def test_vendored_copies_match_the_hashes_recorded_in_the_spec(self):
        spec = Path(__file__).resolve().parents[1] / "docs" / "BUS.md"
        self.assertTrue(spec.exists(), "docs/BUS.md is the contract spec and must exist")
        recorded = dict(re.findall(r"^\|\s*`(bus\.(?:py|mjs))`\s*\|\s*`([0-9a-f]{64})`\s*\|",
                                   spec.read_text(encoding="utf-8"), re.M))
        self.assertEqual(set(recorded), {"bus.py", "bus.mjs"},
                         "docs/BUS.md must record a sha256 for each vendored file")
        for name, path in self.files().items():
            self.assertEqual(bus.digest(path.read_bytes()), recorded[name],
                             f"{name} differs from the hash in docs/BUS.md. If the contract "
                             f"changed deliberately, update BOTH packages and the recorded hash.")


if __name__ == "__main__":
    unittest.main()
