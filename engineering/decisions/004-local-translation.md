# Decision 004 — Local Sugoi, bounded scheduling, and English layout

Status: accepted and implemented, 2026-11-13.

## Context

The user requested Sugoi V4 through CTranslate2, swappable model backends, and English in the
stabilized overlay. All processing remains local, with ordinary 16 GB PCs as the eventual target.
Previously agreed automatic text sizing and memory/SQLite caching are needed for this slice.

## Choice

Use the [Sugoi V4 CT2 conversion](https://huggingface.co/entai2965/sugoi-v4-ja-en-ctranslate2/tree/71d67eb8e73ec2f5aaefc0689e03a4eb843d3a2b)
at revision `71d67eb8e73ec2f5aaefc0689e03a4eb843d3a2b`, including both SentencePiece tokenizers.
Pin lengths and SHA-256 digests for every required asset. Explicit setup downloads about 1.11 GB;
runtime validates local files and never downloads. Keep upstream README/license with the weights.
The supplied [license](https://huggingface.co/entai2965/sugoi-v4-ja-en-ctranslate2/blob/71d67eb8e73ec2f5aaefc0689e03a4eb843d3a2b/LICENSE)
limits use to research involving information analysis and excludes commercial use. The private
prototype does not establish broader permission or make the weights suitable for unrestricted bundling.

Use [CTranslate2](https://opennmt.net/CTranslate2/python/ctranslate2.Translator.html) on CPU with
int8 computation, two intra-op threads, one model worker, and batches of four distinct sources.
Fast CPU uses beam two; Wider search uses beam five. These are decoding profiles of the same model.
Wider search can change quality in either direction. No CUDA installation is required. Reject
overlong input and unterminated output visibly instead of hiding truncation.

Keep one `TranslationBackend` protocol with identity, batched translation, and cleanup. A new model
is a separate adapter registered in `app`; the UI, tracker, and cache need no model-specific logic.
Backend changes drain an active call and unload before loading. An adapter's cache identity includes
model/tokenizer revision, CT2/SentencePiece versions, language pair, precision, decoding limits/settings,
and adapter version. Future context or glossary support must become part of the cache key.

The coordinator supplies confirmed tracks. One worker replaces its desired set (maximum 128) and
coalesces identical text instead of appending jobs. Initial text needs two consistent observations
or a static 350 ms settling interval. Prior committed text remains eligible during pending changes
and one missed detection; its English stays stable. Moving a track changes only layout. Every result
is checked against generation, current desired request, source text, and content revision.

Use a 512-entry in-process LRU backed by SQLite with a 20,000-row cap. SQLite belongs to the worker,
not the GUI, and disk failures fall back to memory with a visible warning. No Redis installation or
service is needed. Successful stale work may be cached but cannot revive an obsolete overlay.

Use measured Qt font layout at stable physical bounds. Automatic sizing has a readability floor
and limited shrink/widen/wrap behavior; manual sizing remains fixed. Constrain boxes to the client,
show an ellipsis for remaining overflow, and retain full text in the inspector. Pending/untranslated
regions leave the original text unobscured. Diagnostic boxes are available with English disabled.

## Consequences

The app now has a complete local path without a GPU toolkit or external service. Startup still has
validation/loading cost and a transient memory peak when quantizing the supplied weights. All slow
operations stay off Qt's thread; native inference cannot be force-cancelled mid-call.

This first adapter works per OCR region. Paragraph grouping, context, glossaries, competing models,
GPU presets, and overlap avoidance need separate evaluation. Passing synthetic checks does not
establish translation accuracy, game frame-time impact, or sustained memory usage on midrange PCs.
