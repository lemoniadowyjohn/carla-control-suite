"""R2 canonical traffic-control digest tests (C0 remediation).

Required behaviors (from the C0 review):
- empty collection != missing collection
- empty collection != parse failure
- empty != count-only serialization (sha256("0"))
- adding one reference changes signalReference digest and combined digest
- adding one controller changes controller digest and combined digest
- canonical ordering is deterministic (document order does not matter)
- mutation of a semantic field changes the digest
"""
import hashlib

import pytest

from phase_q.signal_digest import (
    controller_digest,
    signal_reference_digest,
    traffic_control_digests_v2,
    traffic_control_digests_v2_from_text,
)
from phase_q.common import XodrTree

HEADER = '<OpenDRIVE><header revMajor="1" revMinor="6"/>'

EMPTY_ELEMENTS_DOC = '<OpenDRIVE>{}</OpenDRIVE>'.format(
    '<header revMajor="1" revMinor="6"/><road id="1"><signals/></road>')
MISSING_DOC = '<OpenDRIVE>{}</OpenDRIVE>'.format(
    '<header revMajor="1" revMinor="6"/><road id="1"/>')
REF_DOC = '<OpenDRIVE>{}</OpenDRIVE>'.format(
    '<header revMajor="1" revMinor="6"/><road id="1"><signals>'
    '<signalReference id="r1" s="10.5" t="-2" type="1000000" subtype="1"/></signals>'
    '</road>')
REF_DOC_REORDERED = '<OpenDRIVE>{}</OpenDRIVE>'.format(
    '<header revMajor="1" revMinor="6"/><road id="2"/>'
    '<road id="1"><signals>'
    '<signalReference id="r1" s="10.5" t="-2" type="1000000" subtype="1"/></signals>'
    '</road>')
CTRL_EMPTY_WRAPPER_DOC = '<OpenDRIVE>{}</OpenDRIVE>'.format(
    '<header revMajor="1" revMinor="6"/><road id="1"/><controllers/>')
CTRL_DOC = '<OpenDRIVE>{}</OpenDRIVE>'.format(
    '<header revMajor="1" revMinor="6"/>'
    '<controllers><controller id="c1" name="K1" type="traffic_light" delay="0.4" plugin="0.0"/></controllers>')
BAD_DOC = '<OpenDRIVE><header revMajor="1"'

SIGNAL_DOC = '<OpenDRIVE>{}</OpenDRIVE>'.format(
    '<header revMajor="1" revMinor="6"/><road id="1"><signals>'
    '<signal id="s1" type="R1" subtype="100" s="5.0" t="0.0" dynamic="yes"/></signals>'
    '</road>')
SIGNAL_DOC_MUTATED = SIGNAL_DOC.replace('subtype="100"', 'subtype="101"')


def v2(text):
    return traffic_control_digests_v2_from_text(text)


@pytest.mark.unit
class TestCanonicalTrafficControlDigestsV2:
    def test_empty_vs_missing_signal_elements(self):
        assert (v2(EMPTY_ELEMENTS_DOC)["signal_element_digest"]
                != v2(MISSING_DOC)["signal_element_digest"])

    def test_empty_vs_missing_signal_references(self):
        assert (v2(EMPTY_ELEMENTS_DOC)["signal_reference_digest"]
                != v2(MISSING_DOC)["signal_reference_digest"])

    def test_empty_vs_missing_controllers(self):
        assert (v2(CTRL_EMPTY_WRAPPER_DOC)["controller_digest"]
                != v2(MISSING_DOC)["controller_digest"])

    def test_empty_equals_count_only_is_rejected(self):
        # the C0 defect: old v1 collapsed to sha256("0")
        empty = v2(EMPTY_ELEMENTS_DOC)
        assert empty["signal_reference_digest"] != hashlib.sha256(b"0").hexdigest()
        assert empty["controller_digest"] != hashlib.sha256(b"0").hexdigest()

    def test_empty_vs_parse_failure_elements(self):
        assert (v2(BAD_DOC)["signal_element_digest"]
                != v2(EMPTY_ELEMENTS_DOC)["signal_element_digest"])

    def test_parse_failure_state_and_flag(self):
        res = v2(BAD_DOC)
        assert res["parse_failure"] is True
        assert res["signal_element_state"] == "PARSE_FAILURE"
        assert res["signal_reference_state"] == "PARSE_FAILURE"

    def test_add_one_reference_changes_reference_digest(self):
        ref_digest_with_one = v2(REF_DOC)["signal_reference_digest"]
        ref_digest_empty = v2(EMPTY_ELEMENTS_DOC)["signal_reference_digest"]
        assert ref_digest_with_one != ref_digest_empty

    def test_add_one_reference_changes_combined(self):
        assert (v2(REF_DOC)["combined_traffic_control_digest"]
                != v2(EMPTY_ELEMENTS_DOC)["combined_traffic_control_digest"])

    def test_add_one_controller_changes_combined(self):
        assert (v2(CTRL_DOC)["combined_traffic_control_digest"]
                != v2(CTRL_EMPTY_WRAPPER_DOC)["combined_traffic_control_digest"])

    def test_canonical_ordering_deterministic(self):
        assert v2(REF_DOC)["signal_reference_digest"] == \
            v2(REF_DOC_REORDERED)["signal_reference_digest"]

    def test_semantic_field_mutation_changes_digest(self):
        assert v2(SIGNAL_DOC)["signal_element_digest"] != \
            v2(SIGNAL_DOC_MUTATED)["signal_element_digest"]

    def test_states_recorded(self):
        res = v2(EMPTY_ELEMENTS_DOC)
        assert res["signal_element_state"] == "EMPTY_COLLECTION"
        assert res["signal_reference_state"] == "EMPTY_COLLECTION"
        # no controllers in doc -> MISSING_COLLECTION
        assert res["controller_state"] == "MISSING_COLLECTION"