#!/usr/bin/env bash
# KDE Plasma (Wayland): the KWin rule for Amadeus' mini core (the window titled "Amadeus core"): always on top, not in
# the taskbar or the task switcher, and KWin remembers where you dragged it. The first time it starts bottom-right on
# the second monitor (or the only one). Running this again keeps the place you chose. Also the dashboard: no title
# bar. Only touches the "amadeus-call" and "amadeus-dash" rules.
set -euo pipefail
W=300; H=300  # the mini core window (desktop/popup.py)
F=kwinrulesrc; G=amadeus-call
kw() { kwriteconfig6 --file "$F" --group "$G" --key "$1" "$2"; }
kr() { kreadconfig6 --file "$F" --group "$G" --key "$1"; }
first=0
[[ "$(kr title)" == "Amadeus core" ]] || first=1  # a new rule, or the older one for the small call window
kw Description "Amadeus mini core"
kw wmclass amadeus-call; kw wmclassmatch 1
kw title "Amadeus core"; kw titlematch 1    # only the mini core, not the dashboard (same app)
kw above true; kw aboverule 2               # always on top (force)
kw noborder true; kw noborderrule 2         # no title bar: it closes from its own controls
kw skiptaskbar true; kw skiptaskbarrule 2
kw skippager true; kw skippagerrule 2
kw skipswitcher true; kw skipswitcherrule 2
if (( first )); then  # where it starts: bottom-right of the monitor KScreen ranks second, else the first one
  geo=$(kscreen-doctor -o | sed 's/\x1b\[[0-9;]*m//g' | python3 -c '
import re, sys
outs, cur = [], None
for l in sys.stdin.read().splitlines():
    if l.startswith("Output:"):
        cur = {}; outs.append(cur)
    m = re.search(r"priority (\d+)", l)
    if m and cur is not None: cur["p"] = int(m.group(1))
    m = re.search(r"Geometry: (\S+) (\S+)", l)
    if m and cur is not None: cur["g"] = m.group(1) + " " + m.group(2)
outs = [o for o in outs if "g" in o]
o = next((o for o in outs if o.get("p") == 2), outs[0] if outs else None)
print(o["g"] if o else "0,0 1920x1080")')
  read -r pos size <<<"$geo"
  X0=${pos%,*}; Y0=${pos#*,}; SW=${size%x*}; SH=${size#*x}
  kw position "$((X0 + SW - W - 16)),$((Y0 + SH - H - 8))"
fi
kw positionrule 4                           # remember: wherever you drag it, it opens there again
# the dashboard (same app, the window titled "Amadeus"): no title bar, its own top bar moves it
D=amadeus-dash
kd() { kwriteconfig6 --file "$F" --group "$D" --key "$1" "$2"; }
kd Description "Amadeus dashboard"
kd wmclass amadeus-call; kd wmclassmatch 1
kd title "Amadeus"; kd titlematch 1
kd noborder true; kd noborderrule 2
rules=$(kreadconfig6 --file "$F" --group General --key rules)
case ",$rules," in *",$G,"*) ;; *) rules=${rules:+$rules,}$G ;; esac
case ",$rules," in *",$D,"*) ;; *) rules=${rules:+$rules,}$D ;; esac
kwriteconfig6 --file "$F" --group General --key rules "$rules"
kwriteconfig6 --file "$F" --group General --key count "$(tr ',' '\n' <<<"$rules" | grep -c .)"
qdbus6 org.kde.KWin /KWin reconfigure
echo "KWin rule set: the mini core stays on top, at $(kr position) (remembered when you move it)"
