# Put your Spotify export here

1. Request **Extended streaming history** at <https://www.spotify.com/account/privacy/> (it takes up to 30 days to arrive).
2. Unzip it into this folder. Subfolders are fine: the pipeline searches for `Streaming_History_Audio_*.json`.
3. From the project root run `make run`.

Everything in this folder except this README is git-ignored, so your raw data never gets committed.
