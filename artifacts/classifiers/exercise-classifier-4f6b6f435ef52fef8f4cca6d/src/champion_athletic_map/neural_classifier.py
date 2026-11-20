"""Small bag-of-tokens classifier with explicit padding and unknown-token rules."""

import math

import torch
from torch import nn


MODEL_VERSION = "masked-mean-neural-classifier-1"


class NeuralExerciseClassifier(nn.Module):
    """Learn token embeddings and classify their masked mean using raw logits."""

    def __init__(self, vocab_size, num_classes, embedding_dim=64, hidden_dim=64,
                 dropout=0.2, max_sequence_length=81, padding_idx=0, unknown_idx=1):
        dimensions = (vocab_size, num_classes, embedding_dim, hidden_dim, max_sequence_length)
        if any(type(value) is not int for value in dimensions):
            raise TypeError("invalid_neural_model_configuration")
        if (vocab_size < 2 or num_classes < 2 or embedding_dim < 1
                or hidden_dim < 1 or max_sequence_length < 1):
            raise ValueError("invalid_neural_model_configuration")
        if type(padding_idx) is not int or type(unknown_idx) is not int:
            raise TypeError("invalid_neural_model_configuration")
        if padding_idx != 0 or unknown_idx != 1:
            raise ValueError("invalid_neural_model_configuration")
        if type(dropout) is not float:
            raise TypeError("invalid_neural_model_configuration")
        if not math.isfinite(dropout) or not 0.0 <= dropout < 1.0:
            raise ValueError("invalid_neural_model_configuration")

        super().__init__()
        self.vocab_size = vocab_size
        self.num_classes = num_classes
        self.embedding_dim = embedding_dim
        self.hidden_dim = hidden_dim
        self.dropout_probability = dropout
        self.max_sequence_length = max_sequence_length
        self.padding_idx = padding_idx
        self.unknown_idx = unknown_idx

        self.embedding = nn.Embedding(vocab_size, embedding_dim,
                                      padding_idx=padding_idx, dtype=torch.float32, device="cpu")
        self.hidden = nn.Linear(embedding_dim, hidden_dim, dtype=torch.float32, device="cpu")
        self.activation = nn.ReLU()
        self.dropout = nn.Dropout(p=dropout)
        self.output = nn.Linear(hidden_dim, num_classes, dtype=torch.float32, device="cpu")
        with torch.no_grad():
            self.embedding.weight[padding_idx].zero_()
            self.embedding.weight[unknown_idx].zero_()

    def _check_inputs(self, input_ids, mask):
        if not isinstance(input_ids, torch.Tensor) or not isinstance(mask, torch.Tensor):
            raise TypeError("invalid_neural_input_contract")
        if input_ids.dtype != torch.long or mask.dtype != torch.bool:
            raise TypeError("invalid_neural_input_contract")
        if (input_ids.ndim != 2 or mask.ndim != 2 or input_ids.shape != mask.shape
                or input_ids.shape[0] < 1 or input_ids.shape[1] < 1
                or input_ids.shape[1] > self.max_sequence_length):
            raise ValueError("invalid_neural_input_contract")
        if input_ids.device != mask.device or input_ids.device != self.embedding.weight.device:
            raise ValueError("invalid_neural_input_contract")
        if bool(((input_ids < 0) | (input_ids >= self.vocab_size)).any()):
            raise ValueError("invalid_neural_input_contract")
        if not bool(torch.equal(mask, input_ids.ne(self.padding_idx))):
            raise ValueError("invalid_neural_input_contract")
        if not bool(mask.any(dim=1).all()):
            raise ValueError("invalid_neural_input_contract")
        if bool((mask[:, 1:] & ~mask[:, :-1]).any()):
            raise ValueError("invalid_neural_input_contract")

    def pooled_representation(self, input_ids, mask):
        """Average valid positions; UNK contributes to the count even when zero."""
        self._check_inputs(input_ids, mask)
        embeddings = self.embedding(input_ids)
        valid = mask.unsqueeze(-1).to(dtype=embeddings.dtype)
        denominator = mask.sum(dim=1, keepdim=True).to(dtype=embeddings.dtype)
        return (embeddings * valid).sum(dim=1) / denominator

    def forward(self, input_ids, mask):
        pooled = self.pooled_representation(input_ids, mask)
        hidden = self.activation(self.hidden(pooled))
        return self.output(self.dropout(hidden))
