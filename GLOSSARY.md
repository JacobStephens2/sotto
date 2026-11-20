# Sotto

Sotto keeps saved narrations in each account's Library.

## Language

**Library**: An account's collection of saved narrations.

**Library entry**: A filename-keyed audio file with optional source, display-title
and provenance sidecars. The filename identifies the entry, its title can change,
and its audio timestamp is the sync rename revision.

**Narration job**: A server-side request to turn submitted text into audio.
It has its own progress and restart state. Saving its result creates a separate
Library entry.
