# Aegis Jail MCP demo video

A [Remotion](https://www.remotion.dev) project that renders the 46-second product demo
(1080p, 30 fps): an agent does a task, a hidden prompt injection tries to steal keys, and the
attempt is blocked. The log lines on screen follow the real output of `aegis demo`.

```sh
cd video
npm install
npm run studio        # live preview
npm run render        # -> out/aegis-demo.mp4
```

Structure: `src/scenes/` has one file per scene (Hook, Brand, Demo, Review, Features, Cta),
`src/AegisDemo.tsx` stitches them together, `src/theme.ts` holds the palette shared with the README images.

**License note:** Remotion is source-available, not open source. It is free for individuals and
small teams, while larger companies need a paid license (check
[remotion.dev/license](https://www.remotion.dev/license)). It is only a build-time tool for this
video: nothing from it ships in the Aegis package, and `video/` is not part of the Python distribution.
