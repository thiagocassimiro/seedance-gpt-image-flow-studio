# Contribuindo

## Preparação local

Use Python 3.11+ em um ambiente virtual dentro do projeto ou apenas `PYTHONPATH=src`. Não instale dependências globalmente e não inicie servidores.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

## Antes do pull request

```powershell
$env:PYTHONPATH = "src"
$env:PYTHONIOENCODING = "utf-8"
python scripts/check_publication.py
python -m unittest discover -s tests -t . -v
```

## Regras do projeto

- Testes e revisões não podem chamar APIs ou CLIs pagas.
- Não inclua credenciais, URLs assinadas, filmes, manifestos ou dados de clientes.
- Preço desconhecido permanece desconhecido; nunca invente valores.
- Não adicione retry, fallback de modelo, aprovação automática ou paralelismo pago sem uma decisão explícita de design.
- Preserve versões anteriores e o histórico dos manifestos.
- Revisores independentes somente apontam problemas e não alteram arquivos.
- Não afirme avaliação de movimento ou áudio quando somente frames foram inspecionados.
- Adicione testes offline para qualquer correção de segurança, idempotência, paths, payloads, custos ou recuperação.

Escolha testes pequenos e determinísticos, usando transportes e subprocessos simulados. A CI não contém segredos e executa apenas validação de publicação e testes offline no Windows.
