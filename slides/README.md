# Cyberdeck club talk

`cyberdeck-talk.md` — a [Marp](https://marp.app) deck, 31 slides, about 22–25 minutes for a
club audience.

Assertion-evidence: every headline is a full sentence making a claim, and the body
of the slide is the evidence for that claim. There are no bullet-point agendas.

## Previewing it

The styling lives in the deck's own front matter, so there is nothing to register
or configure.

- **VS Code** — install the *Marp for VS Code* extension (`marp-team.marp-vscode`)
  and open the file. The preview pane renders it.
- **Command line** — `npx @marp-team/marp-cli@latest cyberdeck-talk.md --preview`,
  **if node is installed.** It is not on this laptop, and `npx` does not
  exist here — the PDFs in this directory were exported from VS Code. See
  "Building without node" below for the headless route.

## Exporting it

```sh
npx @marp-team/marp-cli@latest cyberdeck-talk.md --pdf          # for projecting
npx @marp-team/marp-cli@latest cyberdeck-talk.md --pptx         # if the venue wants PowerPoint
npx @marp-team/marp-cli@latest cyberdeck-talk.md --html         # self-contained page
```

In VS Code the same exports are under *Marp: Export Slide Deck* in the command
palette.

## Images

`img/` holds anything made specifically for the talk. Figures and screens that
already live elsewhere in this repository are referenced in place rather than
copied, so they stay in step with the project.

## Building without node

There is no `nodejs` or `npm` package on this machine and no `npx` on the
PATH. The Marp **VS Code extension** carries its own `marp-cli`, and VS
Code's Electron runs as a node interpreter, so the deck can be built from a
terminal without opening the editor:

```bash
cd ~/git_repos/ham-radio-cyberdeck/slides
MARP=~/.vscode/extensions/marp-team.marp-vscode-*/node_modules/@marp-team/marp-cli/marp-cli.js
ELECTRON_RUN_AS_NODE=1 CHROME_PATH=/usr/bin/google-chrome \
  /usr/share/code/code $MARP cyberdeck-talk.md --pdf --allow-local-files
```

`--allow-local-files` is required because the slides pull images from
`../docs/screens/` and `img/`; without it they render blank and the build
still reports success. The version glob in `MARP` means an extension update
does not break the command.

Swap `--pdf` for `--pptx` or `--html` as needed.
