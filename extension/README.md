# Install the Chrome extension

The extension adds fit details, saves postings, and fills supported application forms. Use it with the hosted web app alone, or connect it to the Internship Engine running on your computer.

## Choose a mode

- **Web app only:** Open the web app once so it can share your profile with the extension. In the extension popup, choose a resume PDF (up to 5 MB). The extension keeps the profile, PDF, learned answers, and queued job events in `chrome.storage.local`; it sends queued events back to the web app's tracker.
- **Laptop engine:** Follow the setup below, start `engine serve`, and save the token in the popup. The extension sends supported page details and form questions to your local engine at `127.0.0.1:8765`; the engine supplies the profile and resume.

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

1. Open [the latest GitHub Release](https://github.com/omar-colab/internship-engine/releases/latest) and download the extension ZIP and its `.sha256` file.
2. Set `archive` to the downloaded ZIP filename, replacing `0.2.0` with the version in that filename:

   ```sh
   archive="internship-engine-extension-0.2.0.zip"
   ```

3. Verify the checksum. On macOS, run:

   ```sh
   shasum -a 256 -c "$archive.sha256"
   ```

   On Linux, run:

   ```sh
   sha256sum -c "$archive.sha256"
   ```

4. Install the [GitHub CLI](https://cli.github.com/) and verify the build provenance before extracting the ZIP:

   ```sh
   gh attestation verify "$archive" -R omar-colab/internship-engine
   ```

5. Extract the ZIP. The extracted folder must contain `manifest.json` at its top level.
6. In Chrome, open `chrome://extensions`, turn on **Developer mode**, choose **Load unpacked**, and select that extracted folder.
7. Open the extension, paste the token printed by `engine token`, and choose **Save token**.

The GitHub ZIP is not installed automatically. Chrome allows one-click installation through the Chrome Web Store; until this project has a published Web Store listing, use the steps above. To install directly from a source checkout, select the repository's `extension` folder in step 3.

## 3. Use it

On a supported job-board page, the extension shows a fit summary and a panel when an application form is open. Review every answer before submitting. The extension never clicks Submit and leaves questions unsupported by your profile for you to answer.

For laptop-engine mode, if it says **Engine not running**, start `engine serve`. If it says **token doesn't match**, copy the output from `engine token` again. The token is stored in Chrome's local extension storage and can be cleared by removing the extension or clearing its data.

## What it can access

The extension runs on supported applicant-tracking pages listed in [`manifest.json`](manifest.json) and on the hosted app route `https://omar-colab.github.io/internship-engine/app/*` to exchange the profile and queued events with that page. In web-app-only mode, its profile, selected resume PDF, learned answers, and queued events stay in `chrome.storage.local`; extension data is not uploaded to a server. In laptop-engine mode, the extension sends the page details and form questions it needs to `http://127.0.0.1:8765` with your local engine token and gets the resume from that same local engine. The extension does not send data to a project-operated server or to the maintainers. The job site receives form information only if you choose to submit it yourself.

See the project [privacy notice](../site/privacy.html).
