# Installing Amadeus

Amadeus runs as a few user services on your own Linux PC. Everything it knows is stored on that PC
(`~/.local/share/amadeus/`, `~/.config/amadeus-core/` and your Obsidian vault) and never in this repository.

The basics take two scripts. Mail, voice, the phone app and work runs are optional and can be added later.

## 1. What you need

Tested on CachyOS (Arch) with KDE Plasma 6 on Wayland and an RTX 3080 Ti (12 GB). Other systemd distros with
KDE should work; the window and tray need KDE.

| Package (Arch names) | For |
|---|---|
| `ollama` (or `ollama-cuda`), enabled: `sudo systemctl enable --now ollama` | the local model |
| `docker`, enabled, and your user in the `docker` group | memory and the privacy filter |
| `python`, `python-gobject`, `gtk3`, `webkit2gtk-4.1`, `python-pyqt6` | the assistant, its window and tray |
| `gst-plugins-good`, `ffmpeg` | sound in the window, voice |
| `curl`, `zstd` | the installer, vault snapshots |
| an NVIDIA GPU with ~12 GB and working `nvidia-smi` | recommended (without it the model runs slowly on the CPU) |

Optional: `obsidian` (notes and work projects), `thunderbird` from your distribution, not Flatpak (mail),
`tailscale` (phone), `claude` with `bubblewrap` and `socat` (work runs).

## 2. The local services

```bash
git clone https://github.com/IAbrahamI/Amadeus.git && cd Amadeus
cp amadeus.env.example amadeus.env      # optional: set OBSIDIAN_VAULT to your vault's absolute path
./install.sh --check                    # shows what's there and what's missing, changes nothing
./install.sh
```

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
5. **The Obsidian folder** (only with `OBSIDIAN_VAULT` set). Creates `Amadeus/` in your vault (`ToDo.md` and
   `Notes.md` are yours, `Projects/` is for work runs), installs the guard for work runs and an hourly
   snapshot of the vault.

Run a single step with `./install.sh --only ollama|secrets|presidio|hindsight|obsidian`.

## 3. The assistant itself

```bash
core/deploy/install.sh --dry-run        # shows what it would write
core/deploy/install.sh
amadeus                                 # opens its window
```

This installs the user services (`amadeus-core`, `amadeus-tray`, voice and the nightly leak scan), the
`amadeus` command, the app-menu entry and a KWin rule for the small window. Run it again after moving the
repository folder.

The first time, open **Settings → Memory** and tell it a bit about yourself; it builds its profile of you from
your chats over time. To give it your own name, personality, face or voice, see [Make it yours](#make-it-yours).

## 4. Optional: mail

1. Install Thunderbird from your distribution and add your accounts there (Amadeus never sees your passwords).
2. Run `core/thunderbird/install.sh`. It registers the bridge and prints the add-on file.
3. In Thunderbird: *Add-ons and Themes → gear icon → Install Add-on From File…* and pick that file.

Thunderbird starts minimised at login. If you close it, Amadeus starts it again after a minute.

## 5. Optional: voice

```bash
python -m venv ~/.local/share/amadeus/voice/venv-lite
~/.local/share/amadeus/voice/venv-lite/bin/pip install faster-whisper soundfile vosk
mkdir -p ~/.local/share/amadeus/voice/models && cd ~/.local/share/amadeus/voice/models
curl -LO https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip && unzip vosk-model-small-en-us-0.15.zip
cd - && core/deploy/install.sh          # now also starts the voice and wake-word services
```

Whisper (speech recognition) downloads itself on first use. Everything runs on the CPU, so the GPU stays free
for the model. Say "voice off" to close the microphone completely.

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
2. Make sure the Obsidian step of `install.sh` ran (it needs `OBSIDIAN_VAULT`), because it installs the guard.
3. Ask Amadeus to "send … to work", or start a project on the **Projects** page.

Runs use your Claude subscription. The model and limits are in the settings (`work_model`, `work_effort`,
`work_timeout_min`).

## Make it yours

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

**Voice.** Put short `.ogg` clips into `~/.local/share/amadeus/voice/clips/`, plus a `voice-pack.json` there that
says which clip plays when (all keys are optional; a random clip from a list is picked):

```json
{
  "ringtone": "my_ringtone",
  "wake_greet": { "": ["hello", "what_is_it"] },
  "actions": { "hello": ["hi"], "heard": ["ok"], "approved": ["nice"], "rejected": ["you_sure"], "failed": ["sorry"] },
  "hear":  [["\\b(thank you|thanks)\\b", ["youre_welcome"]]],
  "reply": [["^done", ["ok"]]]
}
```

`wake_greet` plays when you say only its name (keys are wake words, `""` for all), `actions` when you answer a call
(`hello`), after the wake word (`heard`), and on approvals and errors,
`hear` when what *you* say matches a pattern, `reply` when its answer does. Without a pack it stays silent, and calls
ring with a soft built-in tone (the phone uses its own ringtone).

## Settings

Defaults live in `core/amadeus_core/config.py`. Change any of them in `~/.config/amadeus-core/config.json`,
then run `systemctl --user restart amadeus-core`. The most useful ones are listed in [FEATURES.md](FEATURES.md#settings).

## Troubleshooting

| Problem | What to do |
|---|---|
| `amadeus` opens nothing | `journalctl --user -u amadeus-core -f` and `~/.local/share/amadeus/core/popup.log` |
| The window opens blank on an NVIDIA GPU | Already handled (`WEBKIT_DISABLE_DMABUF_RENDERER`); update `webkit2gtk-4.1` if it persists |
| Hindsight doesn't answer right after installing | The first start downloads models: `docker logs -f hindsight` |
| "Send to work" says the text was held | It contained a deny-list word or a canary, or Presidio couldn't start: `docker start presidio-analyzer presidio-anonymizer` |
| A work run fails with a sandbox error | `bubblewrap` or `socat` is missing; the sandbox refuses to run without them |
| Ollama runs on the CPU | Check `nvidia-smi` and install `ollama-cuda` |

## Uninstall

```bash
systemctl --user disable --now amadeus-core amadeus-tray amadeus-voice amadeus-wake \
  amadeus-leak-scan.timer amadeus-vault-snapshot.timer
docker rm -f hindsight presidio-analyzer presidio-anonymizer
```

That removes the programs and keeps your data. Deleting the data (`~/.local/share/amadeus/`, the
`hindsight-data` volume and the vault's `Amadeus/` folder) is permanent, so back it up first.
