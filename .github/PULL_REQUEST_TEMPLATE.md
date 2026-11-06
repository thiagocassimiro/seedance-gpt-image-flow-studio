## Resumo

Descreva a mudança e o motivo.

## Validação

- [ ] `python scripts/check_publication.py` passou.
- [ ] `python -m unittest discover -s tests -t . -v` passou.
- [ ] Nenhuma API/CLI paga foi chamada.
- [ ] Testes offline foram adicionados ou atualizados quando necessário.

## Segurança e produção

- [ ] Não incluí credenciais, URLs assinadas, dados de clientes ou arquivos de `projects/`.
- [ ] Não usei `git add -f` para contornar o `.gitignore`.
- [ ] Preços desconhecidos continuam desconhecidos.
- [ ] Não introduzi retry, fallback, aprovação automática ou paralelismo pago.
- [ ] Versões e clipes anteriores são preservados.
- [ ] Limitações de movimento/áudio estão declaradas corretamente.

## Notas para o revisor

Inclua paths e resultados, nunca segredos ou URLs assinadas.
