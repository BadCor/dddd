# Voice Assistant (Windows AI Voice Assistant)

A Windows desktop AI voice assistant, built stage by stage. This README
covers **Stage 1: Project Foundation** — configuration, logging, and
error handling only. No voice, no LLM, no Windows actions yet.

## Project structure

```
voice_assistant/
├── main.py                    # Entry point
├── requirements.txt
├── .gitignore
├── README.md
├── config/
│   ├── __init__.py
│   ├── config_manager.py      # Loads/merges/validates config
│   ├── default_config.yaml    # Shipped defaults (do not edit)
│   └── config.yaml            # Your local overrides (auto-created, gitignored)
├── core/
│   ├── __init__.py
│   ├── logger.py               # Logging setup (console + rotating file)
│   └── exceptions.py           # Shared exception types
├── logs/
│   └── app.log                 # Generated at runtime (gitignored)
└── tests/
    ├── __init__.py
    └── test_stage1.py          # Stage 1 test suite (pytest)
```

## Requirements

- Python 3.10+ (developed against 3.12)
- Windows 11 (target platform; also runs on other OSes at this stage,
  since nothing Windows-specific has been added yet)

## Setup

1. Create and activate a virtual environment:

   ```powershell
   python -m venv venv
   venv\Scripts\activate
   ```

2. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

3. Run the app:

   ```powershell
   python main.py
   ```

   On first run, `config/config.yaml` is created automatically from
   `config/default_config.yaml`. Edit `config/config.yaml` to change
   settings — never edit `default_config.yaml` directly.

## Using Stage 1

At this stage there's no command system yet — just a minimal loop to
prove the foundation works:

```
Voice Assistant v0.1.0 - Stage 1 (Foundation)
No commands are implemented yet. Type 'status' to check health,
or 'exit' to quit.

> status
OK - config loaded, logging active, no crashes so far.
> exit
```

Logs are written to `logs/app.log` (rotating, 1 MB per file, 3 backups
kept) and mirrored to the console.

## Configuration reference

See `config/default_config.yaml` for all available keys and comments.
Key sections:

- `app` — name, version, environment
- `logging` — level, log directory/file, rotation size, console output
- `llm` / `speech` — placeholders reserved for later stages (unused now)

## Running tests

```powershell
pip install -r requirements.txt   # includes pytest
pytest -v
```

The Stage 1 suite covers: config loading and merging, missing/malformed
config handling, invalid log-level rejection, log file creation and
fallback behavior, and clean (non-crashing) startup failure handling.

## Error handling philosophy

Every module raises a subclass of `AssistantError` (see
`core/exceptions.py`) instead of letting raw exceptions escape.
`main.py` catches these at the top level, logs them, and exits with a
non-zero status — the app never crashes with an unhandled traceback.
This pattern will be extended, not replaced, as later stages add the
action layer, LLM integration, and speech I/O.

## Roadmap

This is Stage 1 of 12. Later stages (not yet implemented) add: a safe
Windows action layer, a text command parser, LLM-based intent
understanding with strict validation, speech-to-text, text-to-speech, a
desktop GUI, safe file/app discovery, persistent user settings, a full
safety audit, performance cleanup, and a packaged `.exe` build.

## Stage 2 — Safe Windows actions

Stage 2 adds a small, allowlist-based action layer. It does **not** add an
LLM, speech recognition, microphone input, text-to-speech, or memory.

### Supported actions

Each action uses the shape `{ "action": "...", "target": "..." }`:

- `open_file` — opens an existing file.
- `open_folder` — opens an existing folder.
- `open_url` — opens only `http://` or `https://` URLs.
- `launch_application` — launches an application only when its name is present
  in the configured `apps` allowlist.

Example:

```python
manager.execute({"action": "open_folder", "target": "C:\\Users\\Me\\Downloads"})
manager.execute({"action": "open_url", "target": "https://example.com"})
manager.execute({"action": "launch_application", "target": "chrome"})
```

### Approved applications

Edit the separate `config/apps.yaml` file and add only applications you
explicitly approve:

```yaml
apps:
  chrome: "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
  notepad: "C:\\Windows\\System32\\notepad.exe"
```

The caller supplies only the configured **name** (`chrome`, `notepad`, etc.).
It cannot supply an arbitrary executable path through `launch_application`.

For Russian voice commands, you may give the same application several code
words by mapping them to the same approved path:

```yaml
apps:
  telegram: "C:\\Users\\YOUR_NAME\\AppData\\Roaming\\Telegram Desktop\\Telegram.exe"
  "телеграм": "C:\\Users\\YOUR_NAME\\AppData\\Roaming\\Telegram Desktop\\Telegram.exe"
  "тг": "C:\\Users\\YOUR_NAME\\AppData\\Roaming\\Telegram Desktop\\Telegram.exe"
```

After saving the configuration and restarting the assistant, it understands
requests such as `открой, пожалуйста, Телеграм`, `можешь открыть Телеграм`,
and the short code word `тг`.

### Results

All actions return an `ActionResult` with the same predictable fields:
`success`, `action`, `message`, and `error`. A failed validation or OS operation
is converted to a clean failure result rather than an unhandled exception.

### Testing

```powershell
pytest -v
```

The Stage 1 suite remains unchanged. Stage 2 tests mock the isolated OS/browser
functions, so the test suite never launches Explorer, Chrome, a website, or an
arbitrary executable.

### Security limitations

- Only the four explicitly supported action names are accepted.
- Unknown actions, missing targets, invalid target types, malformed paths, and
  unsupported URL schemes are rejected.
- URLs are restricted to HTTP(S); `file:`, `javascript:`, `data:`, `vbscript:`
  and other schemes are rejected.
- Applications are resolved by configured allowlist name only.
- No shell command execution is used by the action layer.
- Stage 2 is a local Windows action layer; it is not a general-purpose command
  execution system.

## Stage 3 — Offline text command system

Stage 3 adds a deterministic, offline text-command parser on top of the Stage 2
safe action layer. The architecture is:

```text
Typed text
  -> CommandParser
  -> Stage 2 ActionManager validation
  -> Stage 2 action handler
  -> Windows action
```

The parser does not execute Windows operations and does not contain duplicate
action logic. It produces one of four typed outcomes: `action`,
`needs_clarification`, `unsupported`, or `invalid`.

### Supported text commands

The initial command vocabulary maps only to Stage 2 actions:

- `open file <path>` → `open_file`
- `open folder <path>` → `open_folder`
- `open <folder name>` → a known Windows user folder such as Downloads
- `open <URL>` → `open_url` for HTTP(S) URLs only
- `open <approved app>` → `launch_application`
- `launch <approved app>`, `start <approved app>`, and `run <approved app>`
  are also supported.

Examples:

```text
Open Downloads
please open my Downloads folder
Open file C:\Users\Me\Documents\notes.txt
Open https://github.com
Open Chrome
launch Chrome
```

An ambiguous command such as `Open Minecraft` is not executed when the parser
cannot safely determine whether Minecraft means an approved application or a
folder. It returns a clarification request instead.

### Run the Stage 3 text interface

```powershell
python main.py
```

Then type a command at the `>` prompt. The terminal displays the original
command, what the parser understood, and the Stage 2 action result. Type
`exit` or `quit` to stop.

### Testing

Run the complete regression suite:

```powershell
pytest -v
```

Stage 1 and Stage 2 tests remain part of the same suite. Stage 3 tests cover
parser variations, ambiguity handling, invalid/unsupported commands, pipeline
integration, Stage 2 validation failures, and the rule that the parser never
calls Windows action functions directly. Automated tests mock action execution
where required and do not launch Chrome, Explorer, browsers, or arbitrary
applications.

### Current limitations

- The parser is intentionally deterministic and rule-based; it is not an AI or
  LLM.
- It supports only the four Stage 2 action types.
- It does not infer arbitrary intents or perform general natural-language
  understanding.
- Ambiguous targets are rejected/clarified instead of guessed.
- No microphone, speech recognition, text-to-speech, voice activation, API
  calls, or AI memory are included.

Stage 4 is planned to add LLM-based natural-language understanding while
retaining the Stage 2 validation and ActionManager safety boundary.


## Stage 4 — LLM integration

Stage 4 adds an LLM interpretation layer for typed natural-language commands. The LLM is an **untrusted interpreter only**:

`typed text -> LLM -> strict schema validation -> Stage 2 ActionManager -> Windows action`

The model never receives Windows execution tools and the application never sends model output directly to Windows APIs. Invalid or unsafe model output is rejected before execution.

### Supported provider

The built-in provider is an **OpenAI-compatible HTTP provider**, configured as either `openai` or `openai_compatible`. The default endpoint is the OpenAI Chat Completions endpoint. Other OpenAI-compatible servers can be used by changing `llm.endpoint` and `llm.model`.

The implementation uses the standard Python HTTP library; no provider SDK is required.

### Configuration

`config/default_config.yaml` contains the safe defaults. On first run it is copied to `config/config.yaml`.

Example:

```yaml
llm:
  provider: "openai_compatible"
  model: "gpt-5.6-luna"
  endpoint: "https://api.openai.com/v1/chat/completions"
  api_key_env_var: "ASSISTANT_LLM_API_KEY"
  timeout: 20
  max_response_size: 8192
```

Set the API key in the environment instead of putting it in YAML:

```text
ASSISTANT_LLM_API_KEY=<your-key>
```

Never commit the key or place it in `README.md` or `config/config.yaml`.

### Structured command format

The only executable action objects are:

```json
{"status":"action","action":{"action":"open_folder","target":"Downloads"},"message":"Opening Downloads."}
```

The allowed actions are `open_file`, `open_folder`, `open_url`, and `launch_application`. Non-action responses can use `needs_clarification`, `unsupported`, or `invalid`.

### Security model

- LLM output is treated as untrusted data.
- Only the four Stage 2 actions are accepted.
- Applications must exist in the configured approved-application registry.
- Application targets cannot be executable paths.
- URLs are restricted to HTTP/HTTPS.
- File/folder targets are resolved and checked before execution.
- Unexpected JSON fields are rejected.
- Shell, PowerShell, Python, and arbitrary command attempts are rejected.
- Stage 2 `ActionManager` remains the only execution path.
- Provider failures never expose raw provider exceptions to the user.
- API keys are never logged.

### Running without an API key

The full automated test suite does not contact an external LLM. Provider behavior is mocked. If the application has no LLM key/provider configured, it safely falls back to the deterministic Stage 3 parser.

Run all tests:

```bash
python -m pytest -q
```

### Current limitations

The LLM layer handles command interpretation only. It does not include microphone input, speech recognition, wake words, Text-to-Speech, audio processing, or AI memory. Those are outside Stage 4.

Stage 5 will introduce speech recognition and microphone input.

## Stage 5 — Speech Recognition and Microphone Input

Stage 5 adds explicit, one-shot microphone input. The path is:

`Microphone -> Speech-to-Text -> recognized text -> existing Stage 4 pipeline -> Stage 2 ActionManager`

Typed input continues to use the same existing Stage 4 pipeline. Voice input does not create a second command-processing system.

### Microphone setup

Microphone capture uses the `sounddevice` package with PortAudio. Install the project requirements, then make sure Windows has microphone access enabled for the Python/terminal application. The application can list available input devices from the Stage 5 terminal menu.

Stage 5 records only after the user explicitly selects `v` / `listen once`. It stops after detected silence or the configured maximum recording duration. There is no wake word, always-listening mode, or background recording.

### Speech-to-text provider

The first provider is an HTTP OpenAI transcription provider. It is isolated behind `SpeechRecognitionProvider`, so another provider can be added without changing the command/action layers. The default model is `gpt-transcribe` and the default endpoint is `/v1/audio/transcriptions`.

The provider receives the completed WAV recording only when transcription is requested. The recording is kept in memory and is not written to a permanent audio file by the application.

### Configuration

Stage 5 settings are under `speech:` in the user `config/config.yaml`:

- `provider`: `none` or `openai`
- `model`: default `gpt-transcribe`
- `endpoint`: default OpenAI transcription endpoint
- `api_key_env_var`: default `ASSISTANT_SPEECH_API_KEY`
- `microphone_index`: optional selected input device
- `sample_rate`: safe default 16000 Hz
- `channels`: default mono
- `start_timeout`: time allowed for speech to begin
- `silence_timeout`: silence needed to stop after speech starts
- `max_duration`: hard recording limit
- `silence_threshold`: voice-activity threshold
- `block_duration`: internal capture block size
- `recognition_timeout`: provider request timeout
- `max_response_size`: response size limit

Extreme values are rejected by configuration validation to prevent excessive resource use.

### Environment variable

When the OpenAI speech provider is enabled, set the configured environment variable, for example:

`ASSISTANT_SPEECH_API_KEY=<your-key>`

Never place the key in source code or commit it to the repository. The application does not log API keys.

### Terminal test interface

Start the application and choose:

- `m` — list available microphones
- `v` — record one explicit voice command
- `t` — enter a typed command through the same Stage 4 pipeline
- `q` — quit

For automated tests, the microphone and provider are replaced with fakes, so no physical microphone or network access is required.

### Real microphone smoke test

A real-device smoke test requires a Windows environment with the `sounddevice` dependency installed and an accessible input device. The automated test suite never depends on hardware. If no microphone is available, the smoke test is reported as unavailable rather than failing the automated suite.

### Privacy behavior

- Microphone capture starts only after an explicit listen request.
- There is no continuous/background recording.
- Audio is held in memory and not permanently stored by default.
- Raw audio is sent only to the configured speech-recognition provider when transcription is requested.
- API keys and raw audio are not written to application logs.
- Only recognized text is passed to Stage 4.
- Microphone data cannot directly reach the Windows action layer.

### Current limitations

- The implemented provider requires network access and a configured API key when enabled.
- Offline speech recognition is not implemented.
- Wake-word detection is not implemented.
- Always-listening/background recording is not implemented.
- Text-to-Speech and voice responses are not implemented; those belong to Stage 6.

## Stage 6 — Text-to-Speech and Voice Responses

Stage 6 adds an optional text-to-speech output layer. It does not change the command/action architecture and does not add any new Windows actions.

### Architecture

```text
Typed input ───────┐
                   ├→ Stage 4 command pipeline → Stage 2 ActionManager → action result
Stage 5 voice ─────┘                                              ↓
                                                          text response
                                                           ├→ terminal display
                                                           └→ Stage 6 TTS → default audio output
```

TTS only receives normal response text. It has no reference to `ActionManager`, microphone audio, or command execution.

### Provider

The first provider is `windows_sapi`, implemented through `pyttsx3`. On Windows it uses the installed Windows SAPI voices locally and does not require an external API key or network connection.

Generated WAV data is held in memory for playback. The provider uses a short-lived temporary WAV internally because `pyttsx3` exposes file synthesis; the file is deleted immediately after synthesis.

### Configuration

The default configuration contains:

```yaml
tts:
  enabled: true
  provider: "windows_sapi"
  voice: null
  rate: 180
  volume: 1.0
  timeout: 30
  max_chars: 2000
```

Set `enabled: false` to disable TTS completely. When disabled, no provider is created or called and text responses continue to work.

`voice` may be left as `null` to use the Windows/default installed SAPI voice. `rate`, `volume`, and `max_chars` have bounded safe values.

No TTS environment variable is required by the local provider. There is therefore no TTS API credential to configure or log.

### Playback behavior

Playback uses the Windows default audio device through `winsound` and is synchronous. A lock prevents overlapping speech: if multiple responses are produced, they are handled one at a time in the order that acquires the playback lock.

Audio is not saved permanently by normal operation.

### Testing without speakers

The Stage 6 automated tests use fake TTS providers and fake audio outputs. They do not require Windows speakers, headphones, or a network TTS service.

Run:

```text
python -m pytest -q
```

### Real audio smoke test

On Windows:

1. Install dependencies with `python -m pip install -r requirements.txt`.
2. Confirm Windows has a working default output device.
3. Leave `tts.enabled: true` and `tts.provider: "windows_sapi"`.
4. Start the assistant with `python main.py`.
5. Enter a simple typed command such as `Open Downloads`.
6. Confirm the text response appears and is spoken through the default output device.

The real-device smoke test is separate from the automated suite.

### Privacy and security

The selected provider is local/offline on Windows. Response text is not sent to a remote TTS service. Credentials are not used or logged. Generated audio is not permanently stored. TTS cannot execute commands and does not receive an `ActionManager` or filesystem-action interface.

Internal exceptions and secrets are not spoken aloud. TTS failures do not turn a successful Windows action into a failed command; the text response remains available.

### Current limitations

- The first provider is Windows/SAPI-oriented and is not intended as a cross-platform TTS backend.
- Voice quality depends on installed Windows SAPI voices.
- No advanced emotional/conversational voice controls are implemented.
- No GUI, wake word, always-listening, background recording, or voice activation is implemented.
- Stage 7 has not been started.

## Stage 7 — Desktop GUI

Stage 7 adds a Windows desktop interface built with **PySide6**. The GUI is an interface layer only and reuses the existing Stage 3–6 pipelines.

### GUI features
- Typed command input and Send button.
- Explicit Start Listening / Stop Listening controls.
- Microphone selection from Stage 5's device list.
- Conversation area showing typed commands, recognized speech, and assistant responses.
- Status indicator: Ready, Listening, Processing, Speaking, Error.
- TTS enable/disable checkbox.
- Safe user-facing error messages.

### Architecture

```text
Typed text ───────────────┐
                          ├─> existing Stage 4 pipeline
Stage 5 microphone -> STT ┘          ↓
                              Stage 2 ActionManager
                                      ↓
                                  text response
                                  ├─> GUI display
                                  └─> Stage 6 TTS -> audio
```

The GUI does not execute shell commands, PowerShell, arbitrary executables, or Windows actions directly.

### Installation

Install the project dependencies on Windows 11:

```text
python -m pip install -r requirements.txt
```

This includes PySide6 for the desktop GUI.

### Running

```text
python main.py
```

The GUI starts after configuration is loaded. Stage 7 no longer uses the terminal as the primary interface.

### Microphone

Use the microphone selector to choose an available input device. **Start Listening** performs one explicit Stage 5 recording. **Stop Listening** requests cancellation of the current bounded recording. There is no wake word, always-listening mode, or background recording.

### TTS

The `Speak responses` checkbox controls the existing Stage 6 TTS pipeline. Disabling it prevents the TTS provider from being called while assistant responses continue to appear as text.

### Testing without GUI hardware

The existing Stage 1–6 automated tests remain independent of GUI hardware. Stage 7 source/integration checks verify that GUI commands are routed to the existing pipelines and that the GUI contains no direct Windows action execution.

A full GUI runtime smoke test requires PySide6 and a Windows desktop session. A headless Linux environment cannot validate the native Windows GUI/audio behavior.

### Current limitations

- The GUI requires PySide6.
- Native GUI runtime testing requires a graphical environment.
- Windows microphone and audio hardware must be tested on the target Windows 11 machine.
- No Stage 8 functionality is included.
- No wake word, always-listening mode, background recording, new Windows actions, or autonomous computer control is included.

## Stage 8 — Safe file and application discovery

Stage 8 adds **candidate discovery only**. It does not replace Stage 2
execution, does not execute discovered applications, and does not create a
second command-processing system.

### Architecture

```text
User input
  -> existing Stage 3/4 interpretation
  -> Stage 8 discovery when the target is unresolved
  -> Stage 2 ActionManager validation
  -> existing Windows action
```

The discovery package is:

```text
discovery/
├── __init__.py
├── models.py
├── file_discovery.py
├── folder_discovery.py
├── application_discovery.py
└── manager.py
```

`commands/discovery_pipeline.py` is the orchestration adapter. It uses the
existing Stage 4 pipeline first, then asks discovery for candidates only when
needed. A discovered candidate is still passed to the existing `ActionManager`
for validation and execution.

### File and folder discovery

By default, only these user locations are searchable:

- `%USERPROFILE%/Downloads`
- `%USERPROFILE%/Documents`
- `%USERPROFILE%/Desktop`

Additional project directories can be explicitly configured in the user
`config/config.yaml`. The shipped defaults use `{home}` as the current user's
profile directory.

Searches have configurable:

- maximum recursion depth;
- maximum result count;
- timeout;
- separate file/folder roots.

File results include name, path, type, size, modification time, relevance, and
source. Folder results include name, path, modification time, relevance, and
source. Queries such as `downloaded yesterday` use file modification time as a
safe approximation; the assistant does not claim to know the true download
history.

Invalid, missing, inaccessible, or system-sensitive roots are skipped rather
than causing arbitrary filesystem traversal. The assistant never scans an
entire drive by default.

### Application discovery

Application discovery checks Windows Start Menu shortcuts and, on Windows,
known uninstall-registration information. Discovery returns application names
and safe shortcut/registration metadata. It never launches a discovered
application.

The Stage 2 application allowlist remains mandatory. A discovered application
that is not configured as approved cannot be launched automatically.

### Ambiguity

Discovery never randomly selects among multiple candidates. Multiple matches
produce a structured ambiguity result and the GUI can display a clarification
request. No ActionManager execution occurs until a single safe candidate has
been resolved.

### Security restrictions

- No `subprocess`, shell, PowerShell, or arbitrary executable execution.
- Discovery does not call `ActionManager`.
- The existing ActionManager remains the only execution layer.
- Discovered application paths are never treated as trusted executable paths.
- Application launches still require the configured Stage 2 allowlist name.
- File and folder candidates are still validated by Stage 2 before opening.
- HTTP(S) URL validation remains unchanged.
- No whole-drive recursive scan is enabled by default.
- No persistent indexing database is created in Stage 8.

### Configuration

The shipped defaults contain:

```yaml
discovery:
  enabled: true
  max_depth: 4
  max_results: 20
  timeout: 2.0
  search_roots:
    files:
      - "{home}/Downloads"
      - "{home}/Documents"
      - "{home}/Desktop"
    folders:
      - "{home}/Downloads"
      - "{home}/Documents"
      - "{home}/Desktop"
  applications:
    start_menu: true
    registry: true
```

Edit the generated user `config/config.yaml`, not the shipped default file.

### Performance and GUI behavior

Discovery is synchronous at the discovery-library level but has bounded
search depth/result count/time. The Stage 7 GUI continues to call the command
pipeline from `QThread` workers, so discovery does not run on the Qt GUI thread.
No permanent index or background scanner is introduced.

### Testing

Stage 8 tests use temporary directories and mocks. They cover file/folder/app
discovery, configured roots, result limits, invalid/missing/permission-denied
locations, ambiguity and no-results handling, execution-layer separation,
security validation, GUI integration, and background-worker routing.

Run the complete regression suite with:

```powershell
pytest -v
python -m compileall -q .
```

Stage 8 does not implement persistent memory, conversation memory,
personalization, or any Stage 9 functionality.

## Stage 9 — Memory and User Settings

Stage 9 adds a small, explicit, privacy-conscious persistence layer in `user_data/`.

### Persistent settings

Only these settings may be persisted:

- `tts_enabled`
- `tts_voice`
- `tts_rate`
- `tts_volume`
- `microphone_index`
- `llm_provider`
- `llm_model`

Saved settings are applied at runtime on startup and do not rewrite the main YAML configuration. The GUI persists the TTS enabled state and selected microphone when changed.

### Explicit memory

Supported memory categories are limited to:

- preferred application
- preferred folder
- supported assistant preferences: `response_style`, `preferred_language`, `confirmation_mode`

Supported operations are save, retrieve, update, delete, and clear. Memory is only changed after an explicit memory request or an explicit API call to the memory manager. Normal conversation is not automatically archived.

### Storage and privacy

User data is stored locally in a small JSON document under the user's local application-data directory. Writes use a temporary file followed by atomic replacement. There is no database server and no telemetry.

The application does **not** persist:

- passwords
- API keys
- authentication tokens
- credentials
- microphone recordings
- arbitrary shell/PowerShell commands
- conversation history
- unrestricted personal profiles

Corrupted local storage is discarded safely and replaced with an empty supported data structure when possible.

### Security

Stored application names are checked against the existing application allowlist before use. Stored folders are checked for an absolute path and revalidated for existence/type before use. Memory does not execute anything and has no access to Windows action APIs. Existing Stage 2 `ActionManager` validation remains the only execution layer.

LLM memory responses use a strict structured schema. The LLM cannot write files directly. Unsupported categories, operations, fields, secret-like values, and invalid data are rejected.

### GUI

Stage 9 adds only two small controls to the existing Stage 7 header:

- **Settings** — shows persisted supported settings and memory count.
- **Clear Memory** — explicitly asks for confirmation before clearing all supported memory.

The existing Stage 7 conversation, microphone, and TTS controls remain unchanged.

### Testing

Stage 9 tests use temporary storage and mocked components. They never modify the user's real persistent data or scan the real Windows filesystem. The tests cover settings persistence/recovery, all supported memory operations, explicit-only behavior, secret rejection, stored-target validation, LLM memory validation, GUI integration, and background worker architecture.

Stage 10 is included in this release.

## Stage 10 — Error Handling and Full Security Audit

Stage 10 is a reliability and security hardening pass over the existing Stage 1–9 architecture. It does not add a new execution capability and does not change the trust model.

### Security model and trust boundaries

The command path remains:

```text
User typed/recognized input
  -> Stage 3/4 interpretation
  -> strict LLM validation when LLM is enabled
  -> Stage 8 discovery when a target is unresolved
  -> Stage 9 memory handling only for explicit supported memory requests
  -> Stage 2 validation
  -> ActionManager
  -> isolated Windows/browser boundary
```

The following are untrusted and are never executed directly:

- raw user/voice text;
- LLM output;
- discovery metadata;
- stored memory values;
- URLs and paths returned by the LLM.

`ActionManager` remains the only execution dispatcher. Discovery and memory have no Windows execution API access.

### Structured errors

`core/errors.py` provides `ErrorInfo` with:

- category;
- safe user-facing message;
- internal diagnostic text;
- recoverability.

Major pipelines attach structured error information to their existing result objects while keeping the public messages concise. GUI workers convert unexpected exceptions into safe messages instead of allowing them to escape the worker thread.

### Error handling

Recoverable failures are normalized for:

- configuration;
- LLM/network operations;
- microphone and speech recognition;
- TTS synthesis/playback;
- discovery;
- ActionManager execution;
- local settings/memory storage;
- GUI worker execution;
- native Windows/browser operations.

The GUI continues to display text responses when TTS fails and continues to use background workers for command and voice operations.

### LLM security

LLM output is treated as untrusted structured data. The validator rejects:

- unknown actions;
- malformed JSON;
- unexpected fields;
- shell/PowerShell/cmd requests;
- arbitrary executable paths;
- unauthorized application names;
- unsafe URL schemes such as `javascript:` and `file:`;
- URLs containing embedded credentials;
- malformed/control-character input;
- file/folder results outside configured safe discovery roots when they originate from the LLM.

The deterministic Stage 3 parser remains the fallback for ordinary user requests when the LLM is unavailable or returns invalid data.

Configured application names are still allowlisted. No raw LLM text is passed to the Windows execution layer.

### Network security

The LLM and speech providers are the only components that intentionally perform network requests. Configured non-local HTTP endpoints are rejected; remote providers must use HTTPS. Local HTTP endpoints remain available for development/testing on loopback addresses.

Provider response sizes and timeouts have explicit safe bounds. Network failures and malformed provider responses become structured failures instead of application crashes.

### Logging security

A central log filter redacts common credential forms, including bearer tokens, API keys, passwords, secrets, and authentication tokens.

Normal action logging no longer records full file paths or URLs unnecessarily. Unexpected exception handling avoids printing raw exception contents when those contents could contain private data.

No microphone transcript is logged as content; the existing voice path records only safe operational information such as transcript length.

### Privacy audit

Verified behavior:

- no telemetry system;
- no hidden microphone recording;
- no permanent microphone audio storage;
- no automatic conversation archive;
- no unrestricted profiling;
- memory remains explicit;
- supported settings/memory are the only persistent user data;
- secret-like settings and memory values are rejected;
- TTS remains local through Windows SAPI/pyttsx3;
- network access occurs only through explicitly configured LLM/STT providers.

Stage 10 does not add analytics, tracking, conversation-history storage, or background recording.

### Failure recovery coverage

The Stage 10 test suite covers recovery from:

- unavailable network/provider;
- provider timeout;
- malformed provider responses;
- invalid LLM JSON;
- prompt-injection-style LLM output;
- unavailable/missing microphone paths through existing Stage 5 coverage;
- TTS failures;
- discovery permission failures;
- missing files/applications;
- invalid configuration;
- corrupted user data;
- unexpected internal exceptions at execution and GUI worker boundaries.

### Known limitations

- Stage 10 is a source/test audit; it is not a formal third-party penetration test.
- Windows-specific GUI, registry, Start Menu, SAPI, and hardware behavior still requires validation on the target Windows 11 machine.
- Local JSON user data is not encrypted at rest; the storage layer only avoids persisting unsupported secrets and relies on the normal per-user Windows filesystem boundary.
- The application allowlist configuration is trusted configuration and should be protected like other local application configuration.
- The final Windows executable has not been built.
- No Stage 11 functionality is included.

### Stage 10 verification

Run:

```powershell
pytest -v
python -m compileall -q .
```

Stage 10 adds a dedicated positive/negative security and reliability suite in `tests/test_stage10.py` and preserves all previous Stage 1–9 tests.

Stage 12 is not included in this release.

## Stage 11 — Performance, Resource Management, and Code Cleanup

Stage 11 improves responsiveness and resource lifecycle without changing the
established security model or adding a second execution path.

### Performance behavior

- GUI command and voice work continues to run in `QThread` workers.
- Microphone enumeration is performed by a dedicated GUI worker instead of
  blocking the Qt GUI thread during startup/refresh.
- Conversation message widgets are bounded to 200 retained messages so a long
  session cannot grow the widget tree without limit.
- Discovery remains bounded by configured roots, recursion depth, result count,
  timeout, and cancellation. Application discovery now observes the same
  timeout/cancellation policy as file/folder discovery.
- No permanent filesystem/application index is created.
- HTTP timeouts and response-size limits are preserved.
- Settings writes skip no-op updates to avoid unnecessary atomic disk writes.

### Resource management

- Microphone shutdown requests capture cancellation and stops the sounddevice
  backend when available.
- Speech pipeline shutdown releases microphone/provider resources.
- TTS pipeline shutdown prevents new speech and closes audio/provider resources.
- Windows SAPI provider tracks its active engine and requests engine stop during
  application shutdown.
- Windows audio playback is synchronously serialized and can be purged during
  shutdown.
- GUI shutdown gives active workers a bounded grace period before closing.

There is still no wake-word mode, continuous recording, or background
microphone capture.

### Startup and shutdown

Startup performs configuration and pipeline construction before showing the
window. Microphone enumeration is deferred to a background GUI worker so device
enumeration does not block the first paint/event loop.

On close, active voice capture is cancelled first, worker threads receive a
bounded wait period, then speech and TTS resources are explicitly closed.

### Dependencies

`requirements.txt` was reviewed for Stage 11. The existing dependencies remain
because they are used by the real application: `sounddevice`/`numpy` for
microphone capture, `PyYAML` for configuration, `pyttsx3` for local Windows
SAPI TTS, `PySide6` for the desktop GUI, and `pytest` for tests. No new network
or runtime dependency was introduced.

### Code cleanup

Removed genuinely unused imports and dead helper code in touched modules and
fixed application-discovery initialization so configured/start-menu application
discovery is available through `DiscoveryManager` without changing the
ActionManager execution boundary.

### Known limitations

- Network calls remain bounded by their existing timeouts, but a remote provider
  request already in progress cannot be forcefully cancelled by the GUI worker;
  shutdown therefore uses a bounded GUI wait rather than unsafe thread killing.
- The local SAPI engine is requested to stop during shutdown, but pyttsx3/SAPI
  cancellation is ultimately controlled by the Windows speech engine.
- Actual Windows audio, microphone, and Qt shutdown behavior still requires
  validation on the target Windows 11 machine.
- No Windows executable or installer is created in this stage.

## Stage 12 — Windows Build and Final Release

The project uses PyInstaller for the Windows 11 release build.

### Development setup

1. Create/activate a Windows Python environment.
2. Install runtime dependencies from `requirements.txt`.
3. Install the build dependency: `python -m pip install -r requirements-build.txt`.
4. Run the source application with `python main.py`.

### Build the EXE

From the project root on Windows PowerShell:

```powershell
.\scripts\build_windows.ps1
```

This performs a clean PyInstaller build and places the release executable at:

```text
release\VoiceAssistant\VoiceAssistant.exe
```

For a console/debug build:

```powershell
.\scripts\build_windows.ps1 -Debug
```

### Packaged configuration

The bundled `config/default_config.yaml` is a read-only default. In a packaged deployment, the editable user configuration is created under the user's `%LOCALAPPDATA%\Voice Assistant\config\config.yaml` directory. User settings and explicit memory are also kept under the per-user local application-data directory.

The release contains no API keys or other secrets.

### Environment variables

When a remote provider is enabled, set its configured environment variable before launching the application. The defaults are:

- `ASSISTANT_LLM_API_KEY` for the LLM provider.
- `ASSISTANT_SPEECH_API_KEY` for the speech provider.

Never place credentials in source code, `default_config.yaml`, the PyInstaller spec, or the release directory.

### Packaged smoke test

On Windows, after building:

```powershell
.\scripts\smoke_test_windows.ps1
```

This verifies that the packaged executable starts and can close cleanly. Functional microphone, TTS, and remote-LLM checks should be performed on the target Windows machine with the corresponding hardware/provider configured.

### Release security

The executable uses the same command-processing and security architecture as the source application. Packaging does not add shell execution, PowerShell, arbitrary executable launching, or a second command path. LLM output remains untrusted and must pass the existing validators and `ActionManager` boundary.

### Final release limitations

PyInstaller must be run on Windows for the Windows executable. PyInstaller does not support creating a Windows executable from this Linux verification environment. Therefore the repository contains the reproducible Windows build configuration and scripts, but the final `.exe` must be generated on a Windows 11 build host.

## Russian language support

The assistant now has Russian as its default user language.

- The desktop GUI is localized in Russian.
- Typed commands support Russian phrases such as `открой файл ...`, `открой папку ...`, `открой https://...`, and `запусти ...`.
- Speech recognition sends the configured `speech.language` value, defaulting to `ru`.
- The LLM instruction explicitly supports Russian natural-language requests and asks for Russian user-facing messages.
- Common safe action/error messages are translated to Russian before being displayed or spoken.
- The existing security pipeline is unchanged: Russian input is still interpreted and then validated by the same validators and executed only through `ActionManager`.

To change the speech recognition language, edit the user configuration's `speech.language` value. No API keys are stored in the configuration defaults.
