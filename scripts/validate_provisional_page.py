#!/usr/bin/env python3
import re, os, sys
p = os.path.expanduser("~/CaseLaw/SOoL_QueryTool.html")
s = open(p, encoding="utf-8").read()
print("size:", len(s))
S, E = "<!--PROVISIONAL-FINDINGS-START-->", "<!--PROVISIONAL-FINDINGS-END-->"
print("markers:", s.count(S), s.count(E))
a = s.index(S); b = s.index(E)
frag = s[a:b]
ok = True
for tag in ("div", "table", "tr", "td", "th", "ul", "li", "span", "strong", "code", "em"):
    o = len(re.findall(r"<%s[ >]" % tag, frag)); c = len(re.findall(r"</%s>" % tag, frag))
    good = (o == c)
    ok &= good
    print("  frag %-7s open=%-4d close=%-4d %s" % (tag, o, c, "OK" if good else "*** MISMATCH ***"))
# The page has a long-standing div delta of 1 -- a false positive from a <div>
# inside a JS template string, present since well before the provisional panel.
# Assert the known delta rather than equality, so a real regression still trips.
KNOWN_DELTA = {"div": 1}
for tag in ("div", "table", "script", "style"):
    o = len(re.findall(r"<%s[ >]" % tag, s)); c = len(re.findall(r"</%s>" % tag, s))
    good = (o - c == KNOWN_DELTA.get(tag, 0))
    ok &= good
    print("  PAGE %-7s open=%-4d close=%-4d %s" % (tag, o, c, "OK" if good else "*** MISMATCH ***"))
i = s.index('id="tab-hypotheses"')
print("fragment sits inside #tab-hypotheses:", i < a)
# fragment must close before the next tab panel begins
nxt = s.find('class="tab-panel"', b)
print("no tab-panel opened between marker start and end:", 'class="tab-panel"' not in frag)
print("RESULT:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
