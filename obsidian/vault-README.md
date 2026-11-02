# Amadeus

This folder is where you and Amadeus share notes.

- **ToDo.md** and **Notes.md** are yours. Amadeus adds or ticks off items only when you ask, and only after you approve.
- **_Amadeus/** belongs to the assistant. It keeps it tiny.
- **Projects/** has one folder per work project. Work runs (Claude Code) can read and write only there, nothing
  else in your vault.

Every hour a snapshot of the vault is saved in `~/.local/share/amadeus/vault-snapshots/`, so any change can be undone.
