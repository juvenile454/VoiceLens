# Local models and distribution

VoiceLens uses multilingual Whisper models converted to **CTranslate2** format. OpenAI `.pt` files and whisper.cpp GGML/GGUF files cannot be used directly. The supported model catalog is `settings.WHISPER_MODELS`.

## Official sources

These pages describe the converted models and provide the files. VoiceLens displays these addresses as text and never accesses them itself.

| Model | Upstream source |
|---|---|
| Tiny | [Systran/faster-whisper-tiny](https://huggingface.co/Systran/faster-whisper-tiny) |
| Base | [Systran/faster-whisper-base](https://huggingface.co/Systran/faster-whisper-base) |
| Small | [Systran/faster-whisper-small](https://huggingface.co/Systran/faster-whisper-small) |
| Medium | [Systran/faster-whisper-medium](https://huggingface.co/Systran/faster-whisper-medium) |
| Large v2 | [Systran/faster-whisper-large-v2](https://huggingface.co/Systran/faster-whisper-large-v2) |
| Large v3 | [Systran/faster-whisper-large-v3](https://huggingface.co/Systran/faster-whisper-large-v3) |

Small is a reasonable starting point. Use Base or Tiny on machines where latency or memory matters more than accuracy; the estimates in settings are approximate, not guaranteed memory limits.

## Offline discovery

Search order for a model:

1. `VOICELENS_MODEL_PATH`, if assigned to that size.
2. `$XDG_DATA_HOME/voicelens/models/<id>` (default `~/.local/share/voicelens/models/<id>`).
3. The configured Hugging Face cache: `HF_HUB_CACHE`, then legacy `HUGGINGFACE_HUB_CACHE`, then `HF_HOME/hub`, otherwise `XDG_CACHE_HOME/huggingface/hub` (default `~/.cache/huggingface/hub`).

For an arbitrarily named custom folder, also set `VOICELENS_MODEL_ID` to the catalog ID, for example `tiny`. A recognizable model-folder or cache name determines the ID automatically; an unrecognized folder without an explicit ID retains the legacy Small assignment. The ID labels your choice; file inspection cannot certify that the weights are the claimed size.

A folder needs nonempty, readable `model.bin`, `config.json`, `tokenizer.json`, and either `vocabulary.txt` or `vocabulary.json`. Keep `preprocessor_config.json` as well when supplied upstream. Incomplete snapshots are reported; another complete snapshot can still be used. This is a completeness check, not a checksum or semantic validation of the model.

On first use, `settings.initial_model()` chooses a complete local model. A saved model choice is preserved even if the files later become unavailable, so VoiceLens does not silently change transcription quality. Use settings to choose a replacement.

## Obtaining a model

On an internet-connected machine, use the upstream file page and obtain a complete folder. Copy it into the corresponding VoiceLens model directory on the target machine. For Hugging Face caches, copy the blob targets as well as snapshot symlinks, or materialize the symlinks while copying. A Git LFS pointer is not a model weight file.

An optional **manual online preparation command**, run outside VoiceLens using a Hugging Face CLI already installed in a dedicated environment, is:

```sh
hf download Systran/faster-whisper-small --local-dir /path/to/models/small
```

That command contacts Hugging Face and downloads the model. It is not run by `install.py`, the GUI or the worker. Copy the resulting folder to the offline machine, then run `install.py --check`. Do not add model weights to Git.

For reproducible model bundles, record the upstream snapshot revision and checksums after downloading and verifying that exact snapshot. This source release includes no model archives; its source checksums do not cover externally obtained models.

## Linking and redistribution

Checked against upstream documentation on 2026-09-13:

- OpenAI explicitly releases Whisper code and weights under MIT: [Whisper README](https://github.com/openai/whisper#license), [MIT license](https://github.com/openai/whisper/blob/main/LICENSE).
- The converted Small model declares MIT and describes its conversion: [Systran model card](https://huggingface.co/Systran/faster-whisper-small).
- faster-whisper has its own [MIT license](https://github.com/SYSTRAN/faster-whisper/blob/master/LICENSE); CTranslate2 has its own [MIT license](https://github.com/OpenNMT/CTranslate2/blob/master/LICENSE).

Linking the upstream models lets users obtain the original files without bloating this source repository. The MIT grant also permits redistribution, provided its required copyright and permission notices are retained. If model bundles are offered later, check the exact selected model revision, include the applicable upstream notices and check the licenses of any additionally bundled code. Do not assume that every fine-tune or third-party model uses the same license.

The distribution approach is **source code plus upstream model links**, with no bundled weights. VoiceLens itself is licensed under the [MIT License](../LICENSE); that application license does not replace the separate upstream licenses for models and dependencies.
