from ctypes import Structure, c_uint
from os.path import commonprefix
from types import SimpleNamespace
from unittest.mock import Mock

from dantetl.languages.target import ENGLISH
from dantetl.translation.backends.label_decoder import LlamaLabelDecoder


def test_independent_labels_survive_full_sequence_resets_and_prompt_prefix_changes():
    """A recurrent runtime refuses suffix deletion. The published answer echoes its own prompt."""

    class Params(Structure):
        _fields_ = [
            (name, c_uint) for name in ("n_ctx", "n_seq_max", "n_batch", "n_ubatch", "kv_unified")
        ]

    api, model = Mock(), Mock()
    model.context_params = Params()
    model.n_ctx.return_value = 2048
    model.tokenize.side_effect = lambda data, **_: list(data)
    model.detokenize.side_effect = lambda tokens, **_: bytes(tokens)
    model.longest_token_prefix.side_effect = lambda a, b: len(commonprefix((a, b)))
    api.llama_sampler_init_greedy.side_effect = object
    api.llama_model_has_encoder.return_value = False
    api.llama_model_is_recurrent.return_value = True
    api.llama_n_seq_max.return_value = 3

    def initialize(_, params):
        assert params.n_ubatch >= params.n_seq_max and params.n_batch >= params.n_seq_max
        return object()

    api.llama_init_from_model.side_effect = initialize
    states: list[list[int]] = [[], [], []]
    batch = SimpleNamespace(
        token=[0, 0], pos=[0, 0], seq_id=[[0], [0]], n_seq_id=[0, 0], logits=[False, False]
    )
    api.llama_batch_init.return_value = batch
    api.llama_memory_clear.side_effect = lambda *_: [s.clear() for s in states]

    def remove(memory, slot, start, end):
        if start > 0:
            return False
        states[slot].clear()
        return True

    def decode(context, rows):
        for i in range(rows.n_tokens):
            if not rows.logits[i]:
                assert rows.seq_id[i][0] == 0
            state = states[rows.seq_id[i][0]]
            assert rows.pos[i] == len(state)
            state.append(rows.token[i])
        return 0

    def sample(sampler, context, slot):
        # Prompts end in '>'. Return their last source byte, then end generation.
        tokens = states[slot]
        return tokens[-2] if tokens[-1] == ord(">") else 0

    api.llama_memory_seq_rm.side_effect = remove
    api.llama_memory_seq_cp.side_effect = lambda mem, src, dst, a, b: states.__setitem__(
        dst, states[src].copy()
    )
    api.llama_decode.side_effect = decode
    api.llama_sampler_sample.side_effect = sample
    api.llama_vocab_is_eog.side_effect = lambda vocab, token: token == 0
    decoder = LlamaLabelDecoder(
        api,
        model,
        2,
        lambda s, t: ("alternate:" if s.startswith("/") else "prefix:") + s + ">",
        lambda r: r["choices"][0]["text"],
        [],
        32,
        ENGLISH,
    )
    try:
        assert states == [list(b"prefix:")] * 3
        assert api.llama_decode.call_count == 4
        first = decoder.submit(("X", ()), ENGLISH)
        withdrawn = decoder.submit(("discard", ()), ENGLISH)
        assert first and withdrawn
        decoder.step()
        assert withdrawn.cancel()
        alternate = decoder.submit(("/Y", ()), ENGLISH)
        assert alternate
        for _ in range(30):
            decoder.step()
        assert first.result(0)[0] == {("X", ()): "X"}
        assert alternate.result(0)[0] == {("/Y", ()): "Y"}
        assert (
            api.llama_sampler_reset.call_args_list[0] != api.llama_sampler_reset.call_args_list[1]
        )
        assert (
            api.llama_sampler_reset.call_args_list[1] == api.llama_sampler_reset.call_args_list[2]
        )
    finally:
        decoder.close()
