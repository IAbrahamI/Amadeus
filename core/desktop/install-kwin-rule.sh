#!/usr/bin/env bash
# KDE Plasma (Wayland): keep Amadeus' small call window on top and open it in the bottom-right corner
# of the primary screen. Re-run after changing your monitor layout. Only touches the "amadeus-call" rule.
set -euo pipefail
W=400; H=760; MARGIN=${MARGIN:-0}; PANEL=${PANEL:-0}   # H = window incl. title bar; flush with the screen corner
geo=$(kscreen-doctor -o | sed 's/\x1b\[[0-9;]*m//g' | awk '/^Output/{o=$0} /priority 1/{p=1} /Geometry/{if(p){print $2,$3; exit}}')
read -r pos size <<<"$geo"
X0=${pos%,*}; Y0=${pos#*,}; SW=${size%x*}; SH=${size#*x}
X=$((X0 + SW - W - MARGIN)); Y=$((Y0 + SH - H - MARGIN - PANEL))
F=kwinrulesrc; G=amadeus-call
kw() { kwriteconfig6 --file "$F" --group "$G" --key "$1" "$2"; }
kw Description "Amadeus call window"
kw wmclass amadeus-call; kw wmclassmatch 1
kw above true; kw aboverule 3            # on top when it opens (apply initially)
kw position "$X,$Y"; kw positionrule 3   # bottom-right of the primary screen (apply initially)
rules=$(kreadconfig6 --file "$F" --group General --key rules)
case ",$rules," in *",$G,"*) ;; *) rules=${rules:+$rules,}$G ;; esac
kwriteconfig6 --file "$F" --group General --key rules "$rules"
kwriteconfig6 --file "$F" --group General --key count "$(tr ',' '\n' <<<"$rules" | grep -c .)"
qdbus6 org.kde.KWin /KWin reconfigure
echo "KWin rule set: amadeus-call at $X,$Y, kept above"
