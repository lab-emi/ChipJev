"""ChipLaya: a typed decision model for analog circuit design.

ChipLaya answers closed-option questions about a free-text amplifier design request
(circuit class, objective, input stage, input device, stage count, later stages,
compensation, output buffer) with one probability distribution per question, in one
batched forward pass. It is the Laya multilingual decision model (Convai Innovations),
run through a PyTorch port of Laya-MLX, with 35M of its parameters fine-tuned on circuit
design development data. ChipJev (https://github.com/lab-emi/ChipJev) is the circuit
design agent built around it.

schema       the typed questions and option cards (the model's interface)
model        ChipLaya: load a release and answer design requests
weights      the released fine-tuned weights and their SHA-256
finetune     templated parse data, soft-label training and the parsing evaluation
laya_torch   Laya on CUDA, MPS or CPU (PyTorch port of Laya-MLX, Apache-2.0)

Importing the package does not import PyTorch; loading a model does.
"""

from .model import ChipLaya
from .schema import CLASS_OF, OBJECTIVE, PARSE_QUESTIONS, state_text, topology_questions

__version__ = "1.0.1"
__all__ = ["ChipLaya", "CLASS_OF", "OBJECTIVE", "PARSE_QUESTIONS", "state_text",
           "topology_questions", "__version__"]
