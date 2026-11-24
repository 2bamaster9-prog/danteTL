"""Fixed-shape llama.cpp decoding for independent menu labels, on the model owner."""

from collections.abc import Callable, Sequence
from concurrent.futures import Future
from contextlib import ExitStack
from dataclasses import dataclass, field
from typing import Any

from dantetl.languages.target import TargetLanguage
from dantetl.translation.backend import BatchResult, RequestRejected, Source


@dataclass(slots=True)
class _Label:
    source: Source
    prompt: list[int]
    future: Future[BatchResult] = field(default_factory=Future)
    output: list[int] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Sampling:
    temperature: float = 0.0
    top_k: int = 40
    top_p: float = 0.95
    seed: int | None = None

    def sampler(self, api: Any, resources: ExitStack) -> Any:
        if self.temperature == 0:
            sampler = api.llama_sampler_init_greedy()
            resources.callback(api.llama_sampler_free, sampler)
            return sampler

        # Both bindings expose the same llama.cpp sampler API. Each slot owns its
        # chain and seed, including the completion sampler's default min-p filter.
        chain = api.llama_sampler_chain_init(api.llama_sampler_chain_default_params())
        resources.callback(api.llama_sampler_free, chain)
        api.llama_sampler_chain_add(chain, api.llama_sampler_init_top_k(self.top_k))
        api.llama_sampler_chain_add(chain, api.llama_sampler_init_top_p(self.top_p, 1))
        api.llama_sampler_chain_add(chain, api.llama_sampler_init_min_p(0.05, 1))
        api.llama_sampler_chain_add(chain, api.llama_sampler_init_temp(self.temperature))
        seed = self.seed if self.seed is not None else api.LLAMA_DEFAULT_SEED
        api.llama_sampler_chain_add(chain, api.llama_sampler_init_dist(seed))
        return chain


class LlamaLabelDecoder:
    def __init__(
        self,
        api: Any,
        model: Any,
        width: int,
        prompt: Callable[[str, TargetLanguage], str],
        finish: Callable[[Any], str],
        stops: Sequence[str],
        limit: int,
        target: TargetLanguage,
        sampling: Sampling = Sampling(),
    ) -> None:
        self.width = width
        self._api, self._model = api, model
        self._prompt, self._finish, self._limit = prompt, finish, limit
        self._stops = [s.encode() for s in stops]
        self._labels: dict[int, _Label] = {}
        self._positions = [0] * width
        self._retained = [0] * width
        self._prefix: list[int] = []
        self._target: TargetLanguage | None = None
        self._resources = ExitStack()
        try:
            if api.llama_model_has_encoder(model.model):
                raise ValueError("Parallel label decoding requires a decoder-only model")
            sample = self._tokens(prompt("A", target))
            # Allow room for a short label in templates with longer instructions.
            self._capacity = min(
                model.n_ctx(), max(512, ((len(sample) + limit + 32 + 127) // 128) * 128)
            )
            if len(sample) + limit > self._capacity:
                raise ValueError("Model template exceeds the available context")
            params = type(model.context_params).from_buffer_copy(model.context_params)
            # Hybrid/recurrent state cannot generally rewind to the prompt prefix.
            # Keep one immutable native sequence to restore that state on slot reuse.
            self._checkpoint = bool(
                api.llama_model_is_recurrent(model.model) or api.llama_model_is_hybrid(model.model)
            )
            sequences = width + int(self._checkpoint)
            params.n_ctx = sequences * self._capacity
            # llama.cpp reserves one possible output per sequence, including the
            # checkpoint. Generation uses width entries; prefill can end with a shorter batch.
            params.n_seq_max = params.n_batch = params.n_ubatch = sequences
            params.kv_unified = True
            self._ctx = api.llama_init_from_model(model.model, params)
            if not self._ctx:
                raise RuntimeError("Could not allocate the menu context")
            self._resources.callback(api.llama_free, self._ctx)
            self._memory = api.llama_get_memory(self._ctx)
            if not self._memory or api.llama_n_seq_max(self._ctx) != sequences:
                raise RuntimeError("Runtime did not allocate the requested menu sequences")
            self._batch = api.llama_batch_init(width, 0, 1)
            self._resources.callback(api.llama_batch_free, self._batch)
            self._samplers = [sampling.sampler(api, self._resources) for _ in range(width)]
            self._prepare_prefix(target, sample)
        except BaseException:
            self.close()
            raise

    def _tokens(self, prompt: str) -> list[int]:
        return self._model.tokenize(prompt.encode(), add_bos=False, special=True)

    def _decode(self, tokens: list[int]) -> None:
        batch = self._batch
        batch.n_tokens = self.width
        for slot, token in enumerate(tokens):
            batch.token[slot] = token
            batch.pos[slot] = self._positions[slot]
            batch.n_seq_id[slot] = 1
            batch.seq_id[slot][0] = slot
            batch.logits[slot] = True
        rc = self._api.llama_decode(self._ctx, batch)
        if rc:
            raise RuntimeError(f"Menu decode returned {rc}")
        for slot in range(self.width):
            self._positions[slot] += 1

    def _prepare_prefix(self, target: TargetLanguage, sample: list[int] | None = None) -> None:
        if self._target == target:
            return
        assert not self._labels
        self._api.llama_memory_clear(self._memory, True)
        first = sample if sample is not None else self._tokens(self._prompt("A", target))
        second = self._tokens(self._prompt("海", target))
        if not first or not second:
            raise ValueError("Model template produced no prompt tokens")
        common = self._model.longest_token_prefix(first, second)
        # Leave a real token to evaluate for logits, even for a constant template.
        length = min(common, min(len(first), len(second)) - 1, self._capacity - self._limit - 1)
        self._prefix = first[:length]
        self._padding = first[0]
        self._retained = [length] * self.width
        # Prefill once on sequence zero. No logits are consumed until a real
        # label's suffix has been evaluated; generation retains its fixed shape.
        batch = self._batch
        for start in range(0, length, self.width):
            chunk = self._prefix[start : start + self.width]
            batch.n_tokens = len(chunk)
            for i, token in enumerate(chunk):
                batch.token[i] = token
                batch.pos[i] = start + i
                batch.n_seq_id[i] = 1
                batch.seq_id[i][0] = 0
                batch.logits[i] = False
            rc = self._api.llama_decode(self._ctx, batch)
            if rc:
                raise RuntimeError(f"Menu prefix decode returned {rc}")
        self._api.llama_synchronize(self._ctx)
        if length:
            for slot in range(1, self.width + int(self._checkpoint)):
                self._api.llama_memory_seq_cp(self._memory, 0, slot, -1, -1)
        self._positions = [length] * self.width
        self._target = target

    def _release(self, slot: int) -> None:
        prefix = self._retained[slot]
        if self._positions[slot] != prefix:
            if not self._api.llama_memory_seq_rm(self._memory, slot, prefix, -1):
                # Recurrent and hybrid architectures can require a full sequence reset.
                if not self._api.llama_memory_seq_rm(self._memory, slot, -1, -1):
                    raise RuntimeError("Could not clear a menu sequence")
                if self._checkpoint and prefix:
                    self._api.llama_memory_seq_cp(self._memory, self.width, slot, -1, -1)
                else:
                    self._retained[slot] = prefix = 0
            self._positions[slot] = prefix
        self._labels.pop(slot, None)

    def _discard_cancelled(self) -> None:
        for slot, label in tuple(self._labels.items()):
            if label.future.cancelled():
                self._release(slot)

    def reset(self) -> None:
        for label in self._labels.values():
            label.future.cancel()
        self._labels.clear()
        # On the next submission rebuild all native sequence state, including
        # architectures that can discard only an entire recurrent sequence.
        self._target = None

    def submit(self, source: Source, target: TargetLanguage) -> Future[BatchResult] | None:
        self._discard_cancelled()
        self._prepare_prefix(target)
        try:
            tokens = self._tokens(self._prompt(source[0], target))
        except RequestRejected:
            return None
        if not 0 < len(tokens) <= self._capacity - self._limit:
            return None  # The primary context has the full per-request token budget.
        slot = next(i for i in range(self.width) if i not in self._labels)
        prefix = self._retained[slot]
        if len(tokens) <= prefix or tokens[:prefix] != self._prefix[:prefix]:
            self._retained[slot] = 0
        self._release(slot)  # Discard any padding consumed while this slot was idle.
        self._api.llama_sampler_reset(self._samplers[slot])
        label = _Label(source, tokens)
        self._labels[slot] = label
        return label.future

    def step(self) -> None:
        self._discard_cancelled()
        if not self._labels:
            return
        tokens = []
        for slot, pos in enumerate(self._positions):
            label = self._labels.get(slot)
            if label is None:
                if pos >= self._capacity:
                    self._release(slot)
                tokens.append(self._padding)
            elif pos < len(label.prompt):
                tokens.append(label.prompt[pos])
            else:
                tokens.append(label.output[-1])
        self._decode(tokens)
        for slot, label in tuple(self._labels.items()):
            if self._positions[slot] < len(label.prompt):
                continue
            token = self._api.llama_sampler_sample(self._samplers[slot], self._ctx, slot)
            end = self._api.llama_vocab_is_eog(self._model._model.vocab, token)
            if not end:
                label.output.append(token)
            raw = self._model.detokenize(label.output, prev_tokens=label.prompt)
            stop = min((i for s in self._stops if (i := raw.find(s)) >= 0), default=-1)
            if not end and stop < 0 and len(label.output) < self._limit:
                continue
            text = raw[:stop] if stop >= 0 else raw
            choice = {
                "text": text.decode("utf-8", errors="ignore"),
                "finish_reason": "stop" if end or stop >= 0 else "length",
            }
            try:
                answer = self._finish({"choices": [choice]})
            except RequestRejected as error:
                result: BatchResult = ({}, {label.source: str(error)})
            else:
                result = ({label.source: answer}, {})
            self._release(slot)
            label.future.set_result(result)

    def close(self) -> None:
        self._resources.close()
