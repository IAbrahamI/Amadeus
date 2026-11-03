# Architecture

Amadeus has two sides with one narrow door between them:

- **The private side** runs entirely on your PC: the assistant, a local model, its memory, your mail, calendar,
  notes and to-dos. It works offline, and nothing on it ever goes to a cloud model.
- **The work side** is Claude Code, for things a local model can't do well (code, documents, research).
  It only ever receives text that went through the privacy filter *and* that you approved word for word.

## Components

```mermaid
flowchart TB
    subgraph clients ["Where you talk to it"]
      win["Desktop window<br/>small call window + dashboard<br/>(GTK + WebKit)"]
      tray["Tray icon<br/>(PyQt)"]
      phone["Android app<br/>(over Tailscale)"]
      voice["Voice<br/>wake word (Vosk) + Whisper"]
    end

    subgraph core ["Amadeus Core · Python · 127.0.0.1:8095"]
      server["HTTP API + web UI"]
      agent["Agent loop<br/>tools · approvals · skills · playbooks"]
      bg["Background jobs<br/>reminders · calendar alerts · mail watch<br/>morning brief · evening summary"]
      db[("SQLite<br/>chats · calendar · approvals")]
    end

    subgraph local ["Local services"]
      ollama["Ollama<br/>Qwen 3.5 9B"]
      hindsight["Hindsight<br/>long-term memory"]
      presidio["Presidio<br/>privacy filter<br/>(Docker, no internet)"]
      tb["Thunderbird<br/>+ Amadeus Bridge add-on"]
      vault["Obsidian vault<br/>Amadeus/ folder"]
    end

    cc["Claude Code<br/>one run per approved task"]

    win & tray & phone & voice --> server
    server --> agent
    agent --> db
    bg --> db
    agent --> ollama
    agent --> hindsight
    agent --> tb
    agent --> vault
    agent -- "send to work" --> presidio
    presidio -- "filtered text,<br/>after your approval" --> cc
    cc -- "works only in" --> projects["your projects folder<br/>(outside the vault)"]
```

| Part | Where | Notes |
|---|---|---|
| Amadeus Core | `core/amadeus_core/` | `server` (API + static files), `agent` (model loop, approvals), `tools` (everything it can do), `privacy` (the filter), `work` (Claude Code runs), `background` (timed jobs), `quickchat` (one chat per day), `digest` (morning brief, evening summary) |
| Web UI | `core/web/` | Plain HTML/CSS/JS, no build step: dashboard (`index.html` with `hud.js`, `hud-views.js`, `hud-settings.js`, and `core.js` drawing the core on the GPU), the small call window (`call.html`), the default avatar (`agent.svg`) |
| Desktop | `core/desktop/` | `popup.py` (the window), `tray.py` (tray icon) |
| Voice | `core/voice/` | `voice_server.py` (Whisper speech recognition), `wake.py` (wake word) |
| Mail | `core/thunderbird/` | A Thunderbird add-on plus a native-messaging host; Thunderbird keeps your accounts and logins |
| Phone | `android/` | Kotlin + Compose; pairs with a one-time code and talks to Core over Tailscale |
| Memory extension | `core/hindsight_ext/` | Makes every Hindsight request need your local key |
| Your own connectors | `core/amadeus_core/mcp.py` | A small MCP client (stdio): the servers you add on Settings → Connectors, their tools always need approval |
| Work guard | `core/amadeus_core/workguard.py`, `core/deploy/work-guard.py` | Hook, deny rules and sandbox settings that keep Claude Code inside your projects folder and out of your vault |

## A request, end to end

```mermaid
sequenceDiagram
    actor You
    participant UI as Window / phone
    participant Core as Amadeus Core
    participant LLM as Local model
    participant Tool as Calendar, mail, notes…

    You->>UI: "Move the dentist to Friday 3 pm"
    UI->>Core: message (today's chat)
    Core->>LLM: message + profile + matching skill + tools
    LLM-->>Core: calendar_update(...)
    Core-->>UI: approval card: before → after
    You->>UI: Approve
    UI->>Core: approve
    Core->>Tool: change the event
    Core->>LLM: result
    LLM-->>UI: "Done, it's on Friday at 15:00."
```

Reading things (calendar, mail, memory) runs straight away. Anything that changes or sends something waits for
your click: on the card in the chat, on the Approvals page, in a call on the PC, or on the phone.

## The privacy filter

Everything that would leave the PC (a work run, a follow-up to one, a message to Claude Code from a project page)
goes through `core/amadeus_core/privacy.py`:

```mermaid
flowchart LR
    t["text"] --> hold{"canary marker or<br/>deny-list word?"}
    hold -- yes --> stop["held: never sent"]
    hold -- no --> pat["fixed patterns<br/>e-mail, phone, IBAN, IP,<br/>keys, home paths, local URLs"]
    pat --> ner["Presidio<br/>names, places, groups<br/>(English + German)"]
    ner -- "Presidio down" --> stop
    ner --> card["approval card shows<br/>exactly this text"]
    card -- you approve --> out["Claude Code run"]
```

- Replacements are fixed labels such as `[PERSON]`, `[EMAIL]` or `[LOCATION]`. It's anonymisation, not
  pseudonymisation: two different people both become `[PERSON]`, and nothing is mapped back.
- Company and brand names are kept on purpose, so a task about GitHub or a framework still makes sense.
  Words you add to the allow-list are never replaced.
- Canary markers are random strings created at install time. A nightly leak scan checks that none of them
  ever shows up in a work run's conversation or in the projects folder.
- If Presidio isn't reachable, the text is held, never sent unchecked.

## Limits

What the design does and doesn't promise, so you can judge it yourself:

- **Your approval is the real guarantee.** The privacy filter is best effort. It catches the fixed patterns above
  and the names, places and groups Presidio recognises, but it can miss an unusual name, and context ("my sister
  who works at the bakery in our street") can identify someone without any name in it. That's why nothing goes to
  Claude Code until you've read and approved the exact text, and the approval card shows what the filter replaced.
- **The local model can be wrong or be tricked.** Mail and web pages can hide instructions. They are treated as data,
  outbound actions suggested right after reading mail are marked, and every change still needs your OK, but read
  what you approve.
- **What does go online:** the work runs to Claude Code (only the approved text); downloads at install and update
  time (the model, container images, voices); Tailscale's coordination servers when you use the phone (your data
  itself goes directly between your devices, encrypted); and Thunderbird talking to your mail provider, as usual.
- **Not a multi-user system.** It assumes one person and their own PC. Anyone who can use your desktop session can
  use Amadeus.

## How it learns

The local model isn't retrained. It gets better through what it is told, from your own feedback
(`core/amadeus_core/learning.py`, inspired by the playbook approach in [OpenJarvis](https://github.com/open-jarvis/OpenJarvis)):

```mermaid
flowchart LR
    fb["👍 / 👎 on answers<br/>approved / rejected actions<br/>failed tools"] --> night["every night:<br/>local model writes<br/>short lessons"]
    night --> test{"test on your past<br/>requests + basics:<br/>no worse?"}
    test -- yes --> book["playbook of lessons"]
    test -- no --> drop["dropped"]
    book --> prompt["the relevant lessons go<br/>into each new request"]
    prompt --> fb
```

Each lesson counts how often the answers it was used in were rated good or bad, so a lesson that does more harm
than good disappears by itself. The lessons are listed under Settings → Memory, where you can remove any of them.

## The work side

A work run is one `claude -p` call in `<projects folder>/<Name>/`, on your own Claude subscription. You choose
the projects folder (`./install.sh` asks, or **Change** on the Projects page), and it's never inside your vault.
The guard (a pre-tool hook, deny rules and Claude Code's sandbox, rewritten whenever the folder changes) lets a run
write only in that folder and keeps it out of your vault, Amadeus's data and your keys. If a run ends with questions, your answers continue the same session. The project page has an
**Open in Claude Code** button that opens the session in a terminal.

## Where data lives

| What | Where | In git? |
|---|---|---|
| Chats, calendar, approvals, settings | `~/.local/share/amadeus/core/amadeus.db` | never |
| Memory | Docker volume `hindsight-data` | never |
| Keys, canary markers, deny-list | `~/.local/share/amadeus/secrets/` (mode 700) | never |
| Your settings | `~/.config/amadeus-core/config.json` | never |
| Notes, to-dos | your Obsidian vault, `Amadeus/` folder | never |
| Work projects | the projects folder you chose (e.g. `~/Amadeus/Projects`) | only the approved text of each run |
| Your own skills, playbooks and connectors | `~/.local/share/amadeus/core/skills/`, the database | never |
| Your persona, avatar sprites | `~/.local/share/amadeus/core/personas/`, `…/core/avatar/` | never |

## Network

| Port | Service | Reachable from |
|---|---|---|
| 8095 | Amadeus Core | this PC, and your paired phone through `tailscale serve` (tailnet only) |
| 8896 | Voice service | this PC |
| 11434 | Ollama | this PC |
| 8888 / 9999 | Hindsight API / UI | this PC |
| 172.30.77.10-11 | Presidio | this PC only (an internal Docker network without internet) |
