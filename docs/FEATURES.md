# Features and settings

## What it does

| Area | Details |
|---|---|
| **Chat** | One conversation per day for the small window, the dashboard and the phone. The small window opens empty each time; the dashboard shows the whole day. When a day is over, it summarizes the day into its long-term memory. Clean Markdown, streaming answers, and `search_chats` finds what was said on earlier days. |
| **Approvals** | Every action that changes or sends something becomes a card with the exact details. Approve or reject it in the chat, on the Approvals page, in a call on the PC or on the phone. **Adjust**: say what should be different, and the assistant redrafts the same action, which waits for your approval again. |
| **Dashboard** | The assistant as a living core of its memories in the middle, the views as small CRT screens around it. The core's topics grow with what it knows, and signals only run through it while it really works. Calendar shows a week you edit in place, Mail keeps one inbox per account (and you choose which accounts it may read at all), Projects show their state: amber needs you, cyan active, grey idle, green done. Three main colours (Default blue, Purple, Red) at the top of Settings change the whole look including the core; amber always means "needs you". Every settings page is there too, and a click on the clock opens your day (morning brief, evening summary). |
| **Calls** | When something needs you (an approval, a reminder, a calendar alert, important mail, a finished work run), it "calls": the small window rings with cards you can act on. Quiet hours (23:00–07:00 by default) hold calls until the morning. |
| **Desktop** | The mini core: a see-through, always-on-top window on your second monitor with only the core. She speaks in bubbles that fade a few seconds later (the history is in the dashboard's Chat), with voice on by default (the mic icon when you hover below the core: every answer, only when you talked, or off), and calls you without a ringing screen: the core beats like a heart, the ring plays on each beat, and the actions (Got it, Snooze, Reject / Adjust / Approve) are in an amber bubble. Click the core for the dashboard, a normal window. The tray icon (the dot shell in the theme colour, an amber dot beating during a call, small bars while she speaks) has a menu to show or hide the mini core. |
| **Your day** | Click the clock on the dashboard: the 07:00 morning brief (to-dos, today's calendar, work runs) and the 21:00 evening summary of your mail. "Summarize so far" makes one on the spot. |
| **Calendar** | Month view and day agenda, repeats, alerts that call you before an event. One step to block whole days ("from the 14th to the 17th X, nothing else") that clears everything else on those days, with repeating events skipped only there. Deleting a single day of a weekly event never deletes the series. |
| **Mail** | Through Thunderbird: overviews of everything open, a whole mail with its links, verification codes, search, mark read, flag, move and file, folders, trash and junk, forward, attachments, contacts, drafts in your style, sending. New mail is checked the moment it arrives. Only urgent mail and mail from people you marked as important call you right away. |
| **To-dos and notes** | Your `ToDo.md` and `Notes.md`, plain Markdown in the `Notes/` part of your folder, so Obsidian or any other notes app can open them. It changes them only when you ask, with your approval. |
| **Reminders** | One-off and repeating (`daily`, `weekdays`, `weekly mon`, …). |
| **Learning** | 👍 / 👎 under every answer (with an optional note), plus approved and rejected actions, are the signal. Every night (03:00) the local model turns the day's mistakes into at most a few short lessons; each lesson counts how often it helped or hurt, and lessons that hurt more than they help are dropped. New lessons are kept only if a test on your own past requests (and a few basics) doesn't get worse. See and remove them under Settings → Memory, or "Learn from today now". |
| **Memory** | Long-term memory in Hindsight, a profile of you (including how you communicate), and what it learned about how you phrase requests. You can read and edit all of it under Settings → Memory. |
| **Playbooks** | Fixed recipes run by code: *plan my day*, *week ahead* (also a Sunday-evening call), *sort my inbox*, *newsletter cleanup*, *new project* (a short interview, a spec you confirm, then a work run). With **＋ Add your own playbook** you write a recipe in your own words (a title, the phrases that start it, the steps); when you say one of the phrases, it follows the steps with its normal tools. |
| **Skills** | Instructions in the open [agentskills.io](https://agentskills.io) format (a folder with `SKILL.md`) that load only when your message matches their trigger words (calendar, replies in your style, work briefs, …). **＋ Add your own skill** on the Skills page writes one for you, or takes a `SKILL.md` file from a public library; they are saved in `~/.local/share/amadeus/core/skills/`. |
| **Connectors** | The built-in ones (calendar, mail, notes, memory, …) can each be switched off. **＋ Add your own connector** adds any [MCP](https://modelcontextprotocol.io) server that runs on your PC (a name and the command that starts it). Every tool of your own connectors asks you first and shows exactly what it sends, and what comes back is treated as data, never as instructions. |
| **Projects and work runs** | One folder per project in a projects folder apart from your notes (shown and changed on the Projects page; moving takes the projects and their Claude Code sessions along). Talk about a project with Amadeus, or write to Claude Code directly from the project page. You see the filtered text first, and **Open in Claude Code** opens the session in a terminal. |
| **Voice** | Spoken answers (the VOICE tag on the dashboard, the mic icon on the mini core): when you talked to it (default), always, or off; the chat always keeps the full text, and what is said is a short spoken line the model writes for that answer (the overall picture, not the first items), with times like "2 PM" and no links. Wake word (its name, as you set it), push-to-talk, local Whisper speech recognition (English, German, Spanish), a word list it extends when you ask and "voice off" to close the microphone. Saying only its name gets a short spoken greeting, and answering a call on the mini core a short "Okay" or "Done"; these are made once in the voice you picked. |
| **Phone** | An Android app over your Tailscale network: chat, approvals, calls that ring like a phone call, today, mail. "It is where you are": while you use the PC the phone stays quiet, and the other way round. |
| **Desktop actions** | Opening apps and web pages ("open Steam", "open YouTube"). A link from a mail it just read, for a site you never named yourself, is shown to you first. |
| **Not on purpose** | No web search, no reading of WhatsApp, Discord or other messengers (for the privacy of the people writing to you), no handling of passwords. It says so instead of guessing. |

## Security and privacy

- **Local only.** Every service listens on `127.0.0.1`. The dashboard is served only to its own window, which
  logs in with a token from `~/.local/share/amadeus/core/token`; a normal browser gets nothing.
- **Approvals.** Nothing that changes data or sends anything runs without your click.
- **Mail is untrusted.** Mail text reaches the model fenced as data, with a rule that it can never give orders.
  Actions proposed right after reading mail get a warning on their card, and saving to memory then needs
  approval too.
- **The privacy filter** for everything that leaves the PC is described in [ARCHITECTURE.md](ARCHITECTURE.md#the-privacy-filter).
- **Work runs** can only write in your projects folder and never read your notes (a pre-tool hook, deny rules and
  Claude Code's sandbox without network), and a nightly leak scan checks that no canary marker ever reached them.
- **The phone** needs your Tailscale network and its own key from a one-time pairing code.

## Settings

Put any of these into `~/.config/amadeus-core/config.json`, then run `systemctl --user restart amadeus-core`.

| Key | Default | What |
|---|---|---|
| `default_model` | `qwen3.5-9b-48k` | Any Ollama model |
| `folder` | `~/Amadeus` | Your folder, with `Notes/` and `Projects/` in it |
| `notes_dir` | `Notes/` in your folder | Where your to-dos and notes live, if somewhere else (Settings → Connectors → Your folder) |
| `assistant_name` | `Amadeus` | Its name, everywhere (also the default wake word) |
| `persona` | `default` | A persona file (see [Make it yours](INSTALL.md#make-it-yours)), or `""` for none |
| `avatar` | empty | An animated sprite set; empty = the default chibi agent |
| `quiet_hours` | `[23, 7]` | No calls in this window |
| `morning_brief`, `morning_hour` | `true`, `7` | The morning brief |
| `digest`, `digest_hour` | `true`, `21` | The evening summary |
| `week_ahead_hour` | `19` | The Sunday week-ahead call |
| `mail_notify` | `important` | `all`, `important` or `off` |
| `mail_check_minutes` | `10` | Backup mail check (new mail is also checked the moment it arrives) |
| `keep_running` | `["thunderbird"]` | Apps it restarts when they get closed |
| `work_model`, `work_effort`, `work_timeout_min` | `claude-sonnet-5-5`, `medium`, `120` | Claude Code work runs |
| `filter_allow` | `[]` | Words the privacy filter never replaces (it can add more when you ask) |
| `wake_words`, `wake_confidence` | its name and `"assistant"`, `0.6` | The wake words |
| `stt_language` | empty | For example `"en"` to lock speech recognition to one language |
| `learning`, `reflect_hour` | `true`, `3` | The nightly learning from your feedback |
| `tts_voice` | empty | A Piper voice (`.onnx`) for reading the briefs aloud; empty = the first one installed |
| `llm_threads` | a quarter of the CPU threads | CPU threads for the local model (it runs on the GPU; more threads make the desktop stutter). `2` is enough when the whole model fits on the GPU |
| `llm_keep_alive` | `30m` | How long the model stays loaded between questions |
| `llm_gpu_free_mib` | `1024` | An idle model unloads when the graphics card has less free memory than this, so videos and games don't stutter (NVIDIA only; `0` turns it off) |
| `gpu_rendering` | `true` | Draw the window on the GPU (smooth). `false` only if the window stays blank or crashes with your graphics driver |
| `serve_apk` | `false` | Offer the phone app for download over Tailscale while you install it |

## Useful commands

```bash
amadeus                                          # open the dashboard
systemctl --user status amadeus-core amadeus-desktop amadeus-voice
journalctl --user -u amadeus-core -f             # the log
journalctl --user -u amadeus-desktop -f           # the window's log
core/desktop/install-kwin-rule.sh                # after changing your monitor layout
```
