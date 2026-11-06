class StudioError(Exception):
    """Erro operacional seguro para exibição sem segredos."""


class ValidationError(StudioError):
    """Entrada, configuração ou estado inválido."""


class ApprovalError(StudioError):
    """Uma barreira obrigatória antes de pagamento não foi satisfeita."""


class DuplicateSubmissionError(StudioError):
    """A mesma operação paga já foi reservada ou enviada."""


class AmbiguousSubmissionError(StudioError):
    """O resultado da submissão é desconhecido; reenvio é proibido."""


class ToolMissingError(StudioError):
    """Ferramenta local necessária não foi encontrada."""
