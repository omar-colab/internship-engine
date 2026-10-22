# Install the Chrome extension

The extension adds fit details, saves postings, and fills application forms from your local profile. It talks to the Internship Engine running on **your own computer**; it is not a standalone hosted service.

## 1. Set up your local engine

You need macOS or Linux, Chrome, Python 3.13+, and [`uv`](https://docs.astral.sh/uv/).

```sh
git clone https://github.com/omar-colab/internship-engine.git
cd internship-engine
uv sync
mkdir -p data
cp profile.example.json data/profile.json
```

Edit `data/profile.json` with facts you are comfortable using for applications. Keep your resume and profile in `data/`; that directory is ignored by Git. See the main [README](../README.md) for optional setup with Claude Code and the daily search pipeline.

Start the local engine and get its token in two terminals:

```sh
uv run python -m engine serve
```

```sh
uv run python -m engine token
```

## 2. Install from GitHub

1. Open [the latest GitHub Release](https://github.com/omar-colab/internship-engine/releases/latest) and download `internship-engine-extension-*.zip`.
2. Extract the ZIP. The extracted folder must contain `manifest.json` at its top level.
3. In Chrome, open `chrome://extensions`, turn on **Developer mode**, choose **Load unpacked**, and select that extracted folder.
4. Open the extension, paste the token printed by `engine token`, and choose **Save token**.

The GitHub ZIP is not installed automatically. Chrome allows one-click installation through the Chrome Web Store; until this project has a published Web Store listing, use the steps above. To install directly from a source checkout, select the repository's `extension` folder in step 3.

## 3. Use it

Keep `engine serve` running. On a supported job-board page, the extension shows a fit summary and a panel when an application form is open. Review every answer before submitting. The extension never clicks Submit and leaves questions unsupported by your profile for you to answer.

If it says **Engine not running**, start `engine serve`. If it says **token doesn't match**, copy the output from `engine token` again. The token is stored in Chrome's local extension storage and can be cleared by removing the extension or clearing its data.

## What it can access

The extension runs on the supported applicant-tracking pages listed in [`manifest.json`](manifest.json), reads the current page's posting and application fields, and sends the information it needs to `http://127.0.0.1:8765` with your local engine token. It retrieves your resume from that same local engine when a form has a file field. It does not contact a project server or send your profile to the maintainers. When you choose to submit an application, the job site's own form receives the information you approved.

See the project [privacy notice](../site/privacy.html).
