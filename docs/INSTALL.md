# Installing Amadeus

Amadeus runs as a few user services on your own Linux PC. Everything it knows is stored on that PC
(`~/.local/share/amadeus/`, `~/.config/amadeus-core/`, and your Obsidian vault if you connect one) and never in this repository.

## Quick install

Install the packages from [What you need](#1-what-you-need) first. Then:

```bash
git clone https://github.com/IAbrahamI/Amadeus.git && cd Amadeus
./install.sh --check     # what's there and what's missing (changes nothing)
./install.sh             # installs what's missing after asking, asks three questions, then sets everything up
amadeus                  # opens it
```

It tests this PC's speed (with a small model if none is installed, removed again afterwards), reads the newest models
that can use tools from Ollama's library and suggests three that fit: the newest strong one, the one Amadeus is tuned on,
and a lighter one. After you pick, it downloads that model, measures it and checks that it really calls tools. Offline it
uses a built-in list. Run
`./install.sh --benchmark` any time to do this again.

The first run also asks three things:

1. **A folder for Claude Code projects** (suggested: `~/Amadeus/Projects`), so a work run never sees your notes. You
   can change it later on the Projects page.
2. **Thunderbird for mail?** Optional: you can also connect accounts directly on the Mail page, without Thunderbird. Yes if you use Thunderbird; your logins stay there.
3. **Voice?** Speech recognition and the wake word, about 1 GB, running on the CPU.

Long steps show the command and its latest lines as they run, then fold away into one line. The full output stays in `~/.local/share/amadeus/install.log`, and `./install.sh --verbose` shows all of it instead. The answers are kept in `amadeus.env`; `./install.sh --setup` asks again. The first run takes a while, mostly for
downloading the local model (about 6.6 GB). Afterwards it lists what's left to do by hand: installing the
Thunderbird add-on (one click in Thunderbird), logging in to Claude Code for work runs, and the phone app. All three
are optional.

**Updating:** `amadeus update` gets the newest version, installs it and restarts Amadeus. Your data stays. It does
nothing when you changed files in the repository yourself, and it only runs when you start it.

The sections below explain each step in detail, and how to do one on its own.

## 1. What you need

Tested on CachyOS (Arch) with KDE Plasma 6 on Wayland and an RTX 3080 Ti (12 GB). Any systemd Linux works.
**KDE Plasma** gives the best experience. On other desktops (GNOME, Xfce, …) everything works, but the small window
opens as a normal window instead of sitting in the corner (on X11 it is still placed there), and GNOME needs the
*AppIndicator* extension to show the tray icon.

**Needed:** Ollama (the local model), Docker (memory and the privacy filter) and the packages below. On Arch, Debian/Ubuntu
and Fedora the installer offers to install whatever is missing (it shows what and asks before using `sudo`), so you
normally don't need to do this by hand. **Everything else
is optional and can be added later:** Thunderbird (mail), Obsidian (notes in your vault), Claude Code (work runs),
Tailscale (the phone app), KDE Plasma (window placement) and an NVIDIA GPU (speed). Without one of them, only that part
stays off, and Settings → Connectors says what it needs.

| For | Arch | Debian / Ubuntu | Fedora |
|---|---|---|---|
| the local model | `ollama` or `ollama-cuda` | [ollama.com/download](https://ollama.com/download) | [ollama.com/download](https://ollama.com/download) |
| memory and the privacy filter | `docker` | `docker.io` | `moby-engine` |
| the assistant, its window and tray (the installer builds the app, and fetches Rust for that into the repo folder) | `base-devel gtk3 webkit2gtk-4.1 pkgconf` | `build-essential libgtk-3-dev libwebkit2gtk-4.1-dev pkg-config` | `gcc gtk3-devel webkit2gtk4.1-devel pkgconf` |
| sound and voice | `gst-plugins-good ffmpeg` | `gstreamer1.0-plugins-good ffmpeg` | `gstreamer1-plugins-good ffmpeg-free` |
| the installer, snapshots if you connect Obsidian | `curl zstd` | `curl zstd` | `curl zstd` |

Enable Ollama and Docker (`sudo systemctl enable --now ollama docker`) and add yourself to the `docker` group.
An NVIDIA GPU with ~12 GB is recommended; without one the model runs slowly on the CPU.

Optional: `obsidian` (notes and work projects), `thunderbird` from your distribution, not Flatpak (mail),
`tailscale` (phone), `claude` with `bubblewrap` and `socat` (work runs).

## 2. What install.sh does

`install.sh` can run as often as you like. It skips what's already in place and never deletes data.
It sets up, in this order:

1. **The local model.** Pulls `qwen3.5:9b` (about 6.6 GB) and creates `qwen3.5-9b-48k`, the same model with a
   48k context, which Amadeus uses.
2. **Private keys** in `~/.local/share/amadeus/secrets/`: the memory's API key, a random canary marker and an
   empty deny-list. Put words that must never leave your PC into `denylist.txt`, one per line.
3. **The privacy filter.** Builds a Presidio image with English and German models and creates two containers
   on an internal Docker network without internet access. Amadeus starts them when it needs them.
4. **Memory.** A Hindsight container that only answers requests carrying your key, with its data in the Docker
   volume `hindsight-data`. The first start downloads embedding models and can take a few minutes.
5. **Obsidian is not part of the install.** Your to-dos and notes start in `~/.local/share/amadeus/notes/`. To keep
   them in a vault, use **Settings → Connectors → Obsidian**: it copies them into an `Amadeus/` folder there (nothing
   of yours is overwritten) and sets up an hourly snapshot of the vault. Scripted installs can set `OBSIDIAN_VAULT`.
6. **The projects folder and the guard for work runs:** writes the guard for the folder you chose (see
   [work runs](#7-optional-work-runs-with-claude-code)).
7. **Voice** (if you said yes): speech recognition and the wake word, see [Optional: voice](#5-optional-voice).
8. **The assistant itself** (`core/deploy/install.sh`), see below.
9. **The mail bridge** (if you said yes), see [Optional: mail](#4-optional-mail).

Run a single step with `./install.sh --only ollama|secrets|presidio|hindsight|obsidian|work|voice|app|mail`.

## 3. The assistant itself

`install.sh` runs `core/deploy/install.sh` for you (`--dry-run` shows what it would write). It also builds the desktop app (mini core, dashboard, tray) with `core/desktop-tauri/build.sh`: the first time it downloads Rust into `.tauri-build/` inside the repo (about 2 GB with the build files) and takes a few minutes. `amadeus update` rebuilds it. It installs the user services (`amadeus-core`, `amadeus-desktop`, voice and the nightly leak scan), the
`amadeus` command, the app-menu entry and a KWin rule for the small window. Run it again after moving the
repository folder.

The first time, open **Settings → Memory** and tell it a bit about yourself; it builds its profile of you from
your chats over time. To give it your own name, personality, face or voice, see [Make it yours](#make-it-yours).

## 4. Optional: mail

1. Install Thunderbird from your distribution and add your accounts there (Amadeus never sees your passwords).
2. Say yes to mail in `./install.sh` (or run `core/thunderbird/install.sh`). It registers the bridge and builds
   the add-on, `~/.local/share/amadeus/amadeus-bridge.xpi`.
3. In Thunderbird: *Add-ons and Themes → gear icon → Install Add-on From File…* and pick that file.

In the dashboard's Mail view you choose which accounts Amadeus may read at all (**+ Add account**).

Thunderbird starts minimised at login. If you close it, Amadeus starts it again after a minute.

## 5. Optional: voice

Say yes to voice in `./install.sh` (or set `AMADEUS_VOICE=1` in `amadeus.env` and run `./install.sh --only voice`,
then `./install.sh --only app`). It creates a Python environment in `~/.local/share/amadeus/voice/venv-lite` with
faster-whisper and Vosk, downloads the small English wake-word model and starts the voice and wake-word services.
With [uv](https://docs.astral.sh/uv/) installed it also sets up speech normalization ([NeMo Text Processing](https://github.com/NVIDIA/NeMo-text-processing),
about 900 MB, in its own Python 3.12 environment), so numbers, money, units and dates are read as words. Without it,
Amadeus' own rules still handle times and dates.

Whisper (speech recognition) downloads itself on first use. Everything runs on the CPU, so the GPU stays free
for the model. Say "voice off" to close the microphone completely.

**Reading aloud (optional).** To have the morning brief and the evening summary read to you (▶ Listen under
*Your day*), add a local [Piper](https://github.com/OHF-Voice/piper1-gpl) voice:

```bash
~/.local/share/amadeus/voice/venv-lite/bin/pip install piper-tts
~/.local/share/amadeus/voice/venv-lite/bin/python -m piper.download_voices en_US-lessac-medium \
  --data-dir ~/.local/share/amadeus/voice/models/piper
systemctl --user restart amadeus-voice
```

Then pick, test or download more voices under **Settings → Voice**: Piper voices (US and UK English, a calm
British voice, German, Spanish) and the more natural Kokoro voices (George, Lewis, Emma, …; one
download of about 340 MB for all of them). **＋ Add a voice** takes any other Piper voice by name or your own files.

## 6. Optional: the phone app

The phone reaches Amadeus only through your private Tailscale network, never the open internet.

1. Install Tailscale on the PC and the phone, sign in to the same account, and run once on the PC:
   `sudo tailscale set --operator=$USER`. Then tell Amadeus "visible mode" (or use **Settings → Phone**).
2. Build the app. You need the Android SDK (Android Studio, or only the command-line tools with
   `ANDROID_HOME` set) and Java 17 or newer:
   ```bash
   cd android && ./gradlew assembleRelease
   ```
   The APK is `android/app/build/outputs/apk/release/app-release.apk`. It is signed with the debug key, which
   is fine for your own phone.
3. Install it. Either connect the phone and run `adb install` with that file, or set `"serve_apk": true` in
   `~/.config/amadeus-core/config.json`, restart Amadeus, open `https://<your-pc>.<tailnet>.ts.net/amadeus.apk`
   on the phone, and set it back to `false` afterwards.
4. In the app, pair with the 6-digit code from **Settings → Phone**, and allow notifications and full-screen
   notifications so it can ring.

"Private mode" switches phone access off again.

## 7. Optional: work runs with Claude Code

1. Install Claude Code, `bubblewrap` and `socat`, and log in once by running `claude`.
2. `install.sh` has set up your projects folder and the guard for it (`./install.sh --only work` redoes it).
3. Ask Amadeus to "send … to work", or start a project on the **Projects** page.

Runs use your Claude subscription. The model and limits are in the settings (`work_model`, `work_effort`,
`work_timeout_min`).

## Make it yours

The easy way is **Settings → Assistant**: set the name, pick or write a personality, upload your own avatar images
(or keep the default agent), or press "Use the defaults". The details below are what that page does.

Everything here lives on your PC, outside the repository. After a change, run `systemctl --user restart amadeus-core`
(and `amadeus-wake` for the wake words).

**Name.** In `~/.config/amadeus-core/config.json`:

```json
{ "assistant_name": "Nova" }
```

The name shows everywhere (window, phone app, notifications) and is the default wake word, next to "assistant".
The wake-word spotter only knows real English words, so a made-up name may not be heard; set your own list with
`"wake_words": ["nova", "assistant"]` if needed.

**Personality.** Copy `core/personas/default.md` to `~/.local/share/amadeus/core/personas/<name>.md`, describe the
character you want (tone, humour, quirks), and set `"persona": "<name>"`. Lines starting with `>` are notes for you.
The rules (approvals, tools, facts) always win over the persona.

**Face.** Without anything added, a small chibi agent (`core/web/agent.svg`) is shown. For an animated avatar, add
transparent PNG sprites as `~/.local/share/amadeus/core/avatar/<set>/<set>_<mood><frame>.png` and set
`"avatar": "<set>"`. Moods: `normal`, `happy`, `sided_thinking`, `sided_surprised`, `sided_worried`, `sad`,
`annoyed`, `blush`, `winking`; frames `1` (mouth closed) to `3` (open) make the lip-sync. Your own logo goes into
`core/web/logo-512.png`, `logo-192.png`, `logo-wide.png` and `favicon.png` (ignored by git).

**Voice.** Pick the voice that reads answers aloud under Settings → Voice. Calls ring with a soft built-in tone
(the phone uses its own ringtone).

## Skills

Skills are short instructions that load only when your message needs them (calendar, replies in your style, …).
They use the open [agentskills.io](https://agentskills.io) format: a folder with a `SKILL.md` that starts with a
`name` and a `description`. The built-in ones are in `core/skills/`. To add your own, or one from a public skill
library, copy its folder into `~/.local/share/amadeus/core/skills/`. Optional keys under `metadata:` are
`triggers` (comma-separated words that load it) and `mode` (`auto`, `manual` or `background`); without triggers, a
skill loads when a word of its name comes up. You can switch each one off on the Skills page.

The easiest way is **＋ Add your own skill** on the Skills page: write it there, or pick a `SKILL.md` file.
Playbooks work the same way (**＋ Add your own playbook**: a title, the phrases that start it, the steps).

### Your own connectors (MCP)

On Settings → Connectors, **＋ Add your own connector** takes any [MCP](https://modelcontextprotocol.io) server
that runs on this PC: a name, the command that starts it, and optional `KEY=value` settings it needs. For example
`npx -y @modelcontextprotocol/server-filesystem ~/Documents` (needs Node.js). Amadeus starts it once to check it
and list its tools. Each of its tools asks you before it runs.

## Running the tests

```bash
cd core && python -m unittest -v
```

They use a throw-away home folder and need no network, Ollama or Docker. GitHub runs them (and builds the phone
app) on every push.

## Settings

Defaults live in `core/amadeus_core/config.py`. Change any of them in `~/.config/amadeus-core/config.json`,
then run `systemctl --user restart amadeus-core`. The most useful ones are listed in [FEATURES.md](FEATURES.md#settings).

## Making the model fit on the GPU

On a 12 GB card the model and its working memory (48k context) only just fit next to the desktop, so a couple of
layers can end up on the CPU, which is slower and keeps the CPU busy. Two Ollama settings halve the working memory
with practically no quality loss:

```bash
sudo mkdir -p /etc/systemd/system/ollama.service.d && printf '[Service]\nEnvironment="OLLAMA_FLASH_ATTENTION=1"\nEnvironment="OLLAMA_KV_CACHE_TYPE=q8_0"\n' | sudo tee /etc/systemd/system/ollama.service.d/override.conf
sudo systemctl daemon-reload && sudo systemctl restart ollama
```

`journalctl -u ollama | grep offloaded` then shows every layer on the GPU.

## Troubleshooting

| Problem | What to do |
|---|---|
| `amadeus` opens nothing | `journalctl --user -u amadeus-core -f` and `journalctl --user -u amadeus-desktop -f` |
| The window opens blank or keeps crashing on an NVIDIA GPU | After three crashes in a row it switches to software drawing by itself (slower when scrolling in a big window). You can also set `"gpu_rendering": false`. To try the GPU again, delete `~/.local/share/amadeus/core/popup-software-rendering`. Updating `webkit2gtk-4.1` and the driver usually helps |
| Hindsight doesn't answer right after installing | The first start downloads models: `docker logs -f hindsight` |
| "Send to work" says the text was held | It contained a deny-list word or a canary, or Presidio couldn't start: `docker start presidio-analyzer presidio-anonymizer` |
| A work run fails with a sandbox error | `bubblewrap` or `socat` is missing; the sandbox refuses to run without them |
| Ollama runs on the CPU | Check `nvidia-smi` and install `ollama-cuda` |

## Mail

Optional. On the Mail page, **+ Add account** gives you two ways, and each account can use either:

| | How | Limits |
|---|---|---|
| **Gmail** | Directly, with an [app password](https://myaccount.google.com/apppasswords) | Personal accounts with 2-Step Verification. Workspace accounts don't offer app passwords: use Thunderbird |
| **Outlook / Hotmail** | Directly, by signing in with Microsoft in your browser | Some work accounts need their admin to allow it |
| **Yahoo, iCloud, Fastmail, Zoho** | Directly, with an app password from the provider | |
| **GMX, WEB.DE** | Directly, after turning on IMAP in their mail settings | |
| **Proton Mail** | Directly, through [Proton Mail Bridge](https://proton.me/mail/bridge) on this PC | Bridge needs a paid Proton plan. Free accounts can't connect any other way |
| **Any other** | Directly, with its IMAP and SMTP servers | |
| **Thunderbird** | Add the account in Thunderbird, with its add-on from `./install.sh --setup` | Only while Thunderbird runs, and only what its add-on can reach, so some mail may not work |

Direct logins stay in a file only you can read, in `~/.local/share/amadeus/secrets/`, and only go to that provider's server.

## Updates

Amadeus asks GitHub once a day whether there's a newer release and sends nothing about you. A new version shows up in the
dashboard's top bar, in the tray menu and under Settings → Assistant, where you can also turn the check off. **Update
now** there, or `amadeus update`, gets the newest release. On a branch other than `main` it pulls that branch instead.

Each release also has `.deb`, `.rpm` and pacman packages with the app ready-built. Add the repository once, and updates
then arrive with your system's other updates. Run `amadeus setup` once per user after the first install.

Debian / Ubuntu:

```bash
curl -fsSL https://iabrahami.github.io/Amadeus/amadeus-repo.gpg | sudo gpg --dearmor -o /usr/share/keyrings/amadeus.gpg
echo "deb [signed-by=/usr/share/keyrings/amadeus.gpg] https://iabrahami.github.io/Amadeus/apt stable main" | sudo tee /etc/apt/sources.list.d/amadeus.list
sudo apt update && sudo apt install amadeus
```

Fedora:

```bash
sudo tee /etc/yum.repos.d/amadeus.repo <<'R'
[amadeus]
name=Amadeus
baseurl=https://iabrahami.github.io/Amadeus/rpm
repo_gpgcheck=1
gpgcheck=1
gpgkey=https://iabrahami.github.io/Amadeus/amadeus-repo.gpg
R
sudo dnf install amadeus
```

Arch / CachyOS:

```bash
curl -fsSL https://iabrahami.github.io/Amadeus/amadeus-repo.gpg | sudo pacman-key --add -
sudo pacman-key --lsign-key 96EE112C59BC2335
printf '\n[amadeus]\nServer = https://iabrahami.github.io/Amadeus/arch/$arch\n' | sudo tee -a /etc/pacman.conf
sudo pacman -Sy amadeus
```

Maintainers: raise the version in `VERSION`, `core/desktop-tauri/Cargo.toml` and `tauri.conf.json`, then push a tag `vX.Y.Z`.
The release workflow runs the tests, builds the packages and publishes them.

## Uninstall

```bash
core/deploy/install.sh --uninstall            # services, the amadeus command, menu and autostart entries,
                                              # the KWin rule, the Thunderbird bridge registration, the work-run guard
docker rm -f hindsight presidio-analyzer presidio-anonymizer
```

Then remove the Amadeus Bridge add-on in Thunderbird (Add-ons and Themes). That removes the programs and keeps your data. The desktop app and Rust stay in `.tauri-build/` until you delete the repo folder. Deleting the data (`~/.local/share/amadeus/`, the
`hindsight-data` volume and, if you connected one, the vault's `Amadeus/` folder) is permanent, so back it up first.
