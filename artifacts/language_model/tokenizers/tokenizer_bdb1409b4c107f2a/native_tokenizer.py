"""Candidate text encoder built from the installed model's native tokenizer tables.

This module does not render Ollama chat templates, infer BOS/EOS policy, or
establish backend prompt counts. Those are separate integration checks.
"""

import hashlib
import json
import re

import regex
from tokenizers import Tokenizer
from tokenizers.models import BPE


LLAMA_BPE_PATTERN = (
    r"(?:'[sS]|'[tT]|'[rR][eE]|'[vV][eE]|'[mM]|'[lL][lL]|'[dD])"
    r"|[^\r\n\p{L}\p{N}]?\p{L}+|\p{N}{1,3}"
    r"| ?[^\s\p{L}\p{N}]+[\r\n]*|\s*[\r\n]+|\s+(?!\S)|\s+"
)


def byte_alphabet():
    """Map each UTF-8 byte to the reversible GPT-2 vocabulary character."""
    visible = list(range(33, 127)) + list(range(161, 173)) + list(range(174, 256))
    values = list(visible)
    extra = 0
    for value in range(256):
        if value not in visible:
            visible.append(value)
            values.append(256 + extra)
            extra += 1
    return dict(zip(visible, map(chr, values)))


def inspect_native_tables(info):
    if info.get("tokenizer.ggml.model") != "gpt2" or info.get("tokenizer.ggml.pre") != "llama-bpe":
        raise ValueError("Unsupported native tokenizer family")
    tokens, kinds, merges = (info[key] for key in
                             ("tokenizer.ggml.tokens", "tokenizer.ggml.token_type", "tokenizer.ggml.merges"))
    if (not isinstance(tokens, list) or not tokens or not all(type(x) is str and x for x in tokens)
            or len(set(tokens)) != len(tokens) or not isinstance(kinds, list) or len(kinds) != len(tokens)
            or any(type(x) is not int or x not in (1, 3) for x in kinds)
            or not isinstance(merges, list) or not merges):
        raise ValueError("Native tables require unique token strings, normal/control types and explicit merges")
    normal = {text: index for index, (text, kind) in enumerate(zip(tokens, kinds)) if kind == 1}
    special = {text: index for index, (text, kind) in enumerate(zip(tokens, kinds)) if kind == 3}
    alphabet = byte_alphabet()
    allowed = set(alphabet.values())
    if not special or any(char not in normal for char in alphabet.values()):
        raise ValueError("Native byte alphabet or control-token table is incomplete")
    if any(any(char not in allowed for char in text) for text in normal):
        raise ValueError("A normal token is outside the reversible byte alphabet")
    pairs = []
    seen = set()
    for text in merges:
        if type(text) is not str or len(text.split(" ")) != 2:
            raise ValueError("Unsupported native merge representation")
        pair = tuple(text.split(" "))
        if pair in seen or any(part not in normal for part in pair) or "".join(pair) not in normal:
            raise ValueError("Duplicate or unbound native merge")
        pairs.append(pair)
        seen.add(pair)
    for name in ("tokenizer.ggml.bos_token_id", "tokenizer.ggml.eos_token_id"):
        index = info.get(name)
        if type(index) is not int or not 0 <= index < len(tokens) or kinds[index] != 3:
            raise ValueError("Native BOS/EOS identity is not a control token")
    return {"tokens": tuple(tokens), "kinds": tuple(kinds), "normal": normal, "special": special, "pairs": pairs}


def build_model_json(info):
    """Construct a fixed BPE object; no fitting or corpus-derived vocabulary is used."""
    tables = inspect_native_tables(info)
    model = BPE(vocab=tables["normal"], merges=tables["pairs"], cache_capacity=0,
                dropout=None, unk_token=None, byte_fallback=False, ignore_merges=True)
    tokenizer = Tokenizer(model)
    return tokenizer.to_str()


class NativeTokenizerCandidate:
    """Encode content or explicitly rendered control tokens; never add chat overhead implicitly."""

    def __init__(self, info, model_json, max_input_characters=100_000):
        if type(max_input_characters) is not int or max_input_characters <= 0:
            raise ValueError("Invalid technical input-length limit")
        self._tables = inspect_native_tables(info)
        self._bpe = Tokenizer.from_str(model_json)
        settings = json.loads(self._bpe.to_str())
        if (self._bpe.get_vocab() != self._tables["normal"]
                or settings.get("added_tokens") != [] or settings.get("normalizer") is not None
                or settings.get("pre_tokenizer") is not None or settings.get("post_processor") is not None
                or settings.get("truncation") is not None or settings.get("padding") is not None
                or settings["model"].get("ignore_merges") is not True
                or settings["model"].get("unk_token") is not None
                or settings["model"].get("dropout") is not None
                or settings["model"].get("byte_fallback") is not False
                or [tuple(pair) for pair in settings["model"]["merges"]] != self._tables["pairs"]):
            raise ValueError("Serialized BPE differs from the native-table contract")
        self._alphabet = byte_alphabet()
        self._inverse = {char: value for value, char in self._alphabet.items()}
        self._pieces = regex.compile(LLAMA_BPE_PATTERN)
        names = sorted(self._tables["special"], key=lambda text: (-len(text), text))
        self._controls = re.compile("|".join(re.escape(text) for text in names))
        self._ranks = {pair: rank for rank, pair in enumerate(self._tables["pairs"])}
        self._bos = info["tokenizer.ggml.bos_token_id"]
        self._eos = info["tokenizer.ggml.eos_token_id"]
        self._max_characters = max_input_characters
        self._initial_state = self.state_fingerprint()

    def state_fingerprint(self):
        state = {"model": json.loads(self._bpe.to_str()), "special": self._tables["special"],
                 "pattern": LLAMA_BPE_PATTERN, "bos": self._bos, "eos": self._eos,
                 "max_characters": self._max_characters}
        return hashlib.sha256(json.dumps(state, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()

    def verify_state(self):
        if self.state_fingerprint() != self._initial_state:
            raise RuntimeError("Candidate tokenizer state changed")
        return True

    def _validate_text(self, text):
        if type(text) is not str:
            raise TypeError("Text must be a string")
        if len(text) > self._max_characters:
            raise ValueError("Input exceeds the technical character limit; nothing was truncated")
        text.encode("utf-8", errors="strict")

    def _reference_piece(self, text):
        if text in self._tables["normal"]:
            return [self._tables["normal"][text]]
        symbols = list(text)
        while len(symbols) > 1:
            candidates = [(self._ranks[(symbols[i], symbols[i + 1])], i)
                          for i in range(len(symbols) - 1) if (symbols[i], symbols[i + 1]) in self._ranks]
            if not candidates:
                break
            _, index = min(candidates)
            symbols[index:index + 2] = [symbols[index] + symbols[index + 1]]
        return [self._tables["normal"][symbol] for symbol in symbols]

    def _ordinary(self, text, reference):
        output = []
        end = 0
        for match in self._pieces.finditer(text, timeout=10):
            if match.start() != end:
                raise ValueError("Pre-tokenizer did not preserve every input character")
            piece = "".join(self._alphabet[value] for value in match.group().encode("utf-8"))
            if reference and len(piece) > 4096:
                raise ValueError("Reference checker piece exceeds its technical limit")
            output.extend(self._reference_piece(piece) if reference
                          else self._bpe.encode(piece, add_special_tokens=False).ids)
            end = match.end()
        if end != len(text):
            raise ValueError("Pre-tokenizer left unmatched input")
        return output

    def encode(self, text, *, parse_special=False, add_bos=False, add_eos=False, reference=False):
        """Preserve text exactly; all control-token and boundary choices are explicit."""
        self._validate_text(text)
        if any(type(flag) is not bool for flag in (parse_special, add_bos, add_eos, reference)):
            raise TypeError("Encoding flags must be Boolean")
        output = []
        if parse_special:
            start = 0
            for match in self._controls.finditer(text):
                output.extend(self._ordinary(text[start:match.start()], reference))
                output.append(self._tables["special"][match.group()])
                start = match.end()
            output.extend(self._ordinary(text[start:], reference))
        else:
            output = self._ordinary(text, reference)
        if add_bos:
            output.insert(0, self._bos)
        if add_eos:
            output.append(self._eos)
        return output

    def count(self, text, **options):
        return len(self.encode(text, **options))

    def decode(self, ids):
        """Reconstruct the exact UTF-8 bytes for a complete encoded sequence."""
        if not isinstance(ids, (list, tuple)):
            raise TypeError("Token IDs must be a list or tuple")
        result = bytearray()
        for index in ids:
            if type(index) is not int or not 0 <= index < len(self._tables["tokens"]):
                raise ValueError("Invalid token ID")
            text = self._tables["tokens"][index]
            if self._tables["kinds"][index] == 3:
                result.extend(text.encode("utf-8"))
            else:
                result.extend(self._inverse[char] for char in text)
        return bytes(result).decode("utf-8", errors="strict")
