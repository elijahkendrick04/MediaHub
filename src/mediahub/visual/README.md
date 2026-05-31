# visual

The bridge to the video-maker. It lets the Python code make MP4 story cards and
reels without having to deal with JavaScript directly (it calls the `remotion`
folder for you).

## voiceover.py + pronunciation.py

`voiceover.py` reads a card's **already-approved caption out loud** and saves it as
an MP3 (plus an `.srt` subtitle file for muted autoplay). It speaks the caption
**word for word** — there is no AI writing a script, because a spoken mistake about a
real swimmer is even harder to spot than a written one. `pronunciation.py` lets a club
fix how a name is said (a plain `{ "written": "spoken" }` list), so the voice never
mangles a swimmer's name.

It's **off by default**: an operator turns it on with `MEDIAHUB_VOICEOVER=1` and by
installing the speech backend (`edge-tts`). If it isn't available, the app says so
honestly (a clear error) instead of using a fake robot voice. Audio is only made for a
card a human has **approved**.

Not done yet (on purpose): burning the subtitles into the video and stitching a whole
narrated meet recap. The `.srt` is produced now; the rest waits until it can be tested
on the real server.
