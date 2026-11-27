# Optional GLiNER.cpp runtime build

This POC route uses the Apache-2.0 upstream GLiNER.cpp source at `af99d2b1fddbfde644e07b159730a76f876ae517` and its tokenizers-cpp submodule at `c586c52f93f7b060753bd2388eb96a105cb7374d`. The embedded sentencepiece revision is `e0f0f966959108415183d6cbe7a9051ca8bc2da1`. Keep these revisions pinned when reproducing the measurements.

The upstream GLiNER CMake config treats `TOKENIZER_CPP_ROOTDIR` as a literal path, and the sentencepiece build needs C++20 with the tested current toolchain. Apply the root fix from the GLiNER checkout and the sentencepiece fix from the tokenizers-cpp checkout:

```sh
git apply /path/to/officekit/scripts/pii_cpp_runtime/gliner-root-fix.patch
git -C deps/tokenizers-cpp apply /path/to/officekit/scripts/pii_cpp_runtime/sentencepiece-cxx20.patch
```

Build upstream GLiNER.cpp with `TOKENIZER_CPP_ROOTDIR` set to its checked-out tokenizers-cpp submodule. Then configure this daemon using `scripts/pii_cpp_runtime/CMakeLists.txt` and the upstream library, ONNX Runtime headers/library, and tokenizer headers. The compiled daemon and all model/runtime assets are external build outputs; none are checked in or included in the default OfficeKit sidecar.

At evaluation time set `OFFICEKIT_PII_CONTEXT_RUNTIME=cpp`, `OFFICEKIT_PII_CONTEXT_CPP_BINARY` to the daemon, and `OFFICEKIT_PII_CONTEXT_MODEL` to the local model directory. Model inference is local and does not download files.
