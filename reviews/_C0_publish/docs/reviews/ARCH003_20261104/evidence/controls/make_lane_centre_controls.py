"""Synthetic positive / negative controls for lane_centre_continuity.py (ARCH-003 D9).

Builds three tiny OpenDRIVE files (straight roads, 3.25 m lanes, right-hand traffic):
  A_continuous : incoming lane -2 -> connector lane -1; the connector reference line starts on the
                 inner border of incoming lane -2 (lateral -3.25 m). Expected: entry and exit gap 0, kink 0.
  B_shifted    : same, but the connector reference line starts on the incoming reference line
                 (what the snap does). Expected: entry gap 3.25 m (one lane width).
  C_kinked     : as A, but the connector heading is rotated by atan(1/2) = 26.565 deg about its start.
                 Expected: entry kink 26.565 deg, entry gap 0.
Usage: python make_lane_centre_controls.py <out_dir>
"""
import math
import os
import sys

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
W = 3.25


def lanes(ids, width=W):
    right = "".join(
        f'<lane id="{i}" type="driving" level="false"><link><predecessor id="{i}"/><successor id="{i}"/></link>'
        f'<width sOffset="0" a="{width}" b="0" c="0" d="0"/></lane>' for i in ids)
    return ('<lanes><laneSection s="0"><center><lane id="0" type="none" level="false"/></center>'
            f'<right>{right}</right></laneSection></lanes>')


def road(rid, junction, x, y, hdg, length, link, lane_ids, lane_links=None):
    lane_xml = lanes(lane_ids)
    if lane_links:
        # connector lane -1: predecessor = incoming lane, successor = exit lane
        lane_xml = lane_xml.replace('<link><predecessor id="-1"/><successor id="-1"/></link>',
                                    f'<link><predecessor id="{lane_links[0]}"/><successor id="{lane_links[1]}"/></link>')
    return (f'<road name="" length="{length}" id="{rid}" junction="{junction}">{link}'
            f'<planView><geometry s="0" x="{x}" y="{y}" hdg="{hdg}" length="{length}"><line/></geometry></planView>'
            f'{lane_xml}</road>')


def build(name, conn_x, conn_y, conn_hdg, conn_len, exit_x, exit_y):
    inc = road("1", "-1", -50.0, 0.0, 0.0, 50.0,
               '<link><successor elementType="junction" elementId="100"/></link>', [-1, -2])
    con = road("2", "100", conn_x, conn_y, conn_hdg, conn_len,
               '<link><predecessor elementType="road" elementId="1" contactPoint="end"/>'
               '<successor elementType="road" elementId="3" contactPoint="start"/></link>', [-1], lane_links=(-2, -1))
    ext = road("3", "-1", exit_x, exit_y, 0.0, 50.0,
               '<link><predecessor elementType="junction" elementId="100"/></link>', [-1])
    junc = ('<junction id="100" name=""><connection id="0" incomingRoad="1" connectingRoad="2" contactPoint="start">'
            '<laneLink from="-2" to="-1"/></connection></junction>')
    xml = f'<?xml version="1.0"?><OpenDRIVE><header revMajor="1" revMinor="4"/>{inc}{con}{ext}{junc}</OpenDRIVE>'
    with open(os.path.join(OUT, name + ".xodr"), "w", encoding="utf-8") as f:
        f.write(xml)


# A: connector reference line on the inner border of lane -2 (y = -3.25); its lane -1 centre is y = -4.875,
#    the same as the incoming lane -2 centre. The exit road reference line is at y = -3.25, so its lane -1 centre is -4.875 too.
build("A_continuous", 0.0, -W, 0.0, 10.0, 10.0, -W)
# B: connector reference line moved onto the incoming reference line (y = 0), the snap's behaviour.
build("B_shifted", 0.0, 0.0, 0.0, 10.0, 10.0, -W)
# C: rotated by atan(1/2) about its start; the exit is placed at the rotated end.
a = math.atan(0.5)
build("C_kinked", 0.0, -W, a, 10.0, 10.0 * math.cos(a), -W + 10.0 * math.sin(a))
print("written", sorted(os.listdir(OUT)))
