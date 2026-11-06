# Regras obrigatórias do AI Video Studio

## Princípio de produção

Detectar erros no texto antes da imagem e na imagem antes do vídeo pago. Não pular revisões para economizar tempo.

## Limites de ação

- Não instalar programas globalmente, não iniciar servidores e não criar interface web sem pedido explícito.
- Não criar `.env`, não persistir credenciais e nunca imprimir `ARK_API_KEY` ou `OPENAI_API_KEY`.
- Usar exclusivamente a API oficial BytePlus ModelArk para vídeo. Não usar intermediários.
- Não trocar modelo automaticamente. O modelo do shot é sempre explícito.
- Preço desconhecido permanece `null`/`unknown`; nunca copiar preços do guia ou estimar sem fonte.
- Toda chamada paga exige aprovação humana prévia, registrada contra o payload e a estimativa exatos.
- `submit --approved` não cria aprovação: ele apenas verifica uma aprovação já registrada.
- Não repetir uma submissão após timeout ou erro ambíguo. Recuperar pelo task ID; nunca reenviar automaticamente.
- Não executar gerações pagas em paralelo e não cancelar tarefas sem autorização específica.
- Imagens usam a CLI `gpt-image` existente, sempre com `--model` explícito e uma imagem por chamada.
- Rascunhos: `gpt-image-2.5-flare`, começando em `low`. Edições com referências e controle preciso: `gpt-image-2.5-sunburst`.
- Nunca apagar ou sobrescrever clipes, frames, manifestos ou versões. Atualizações de estado preservam histórico.
- Revisores independentes somente leem e apontam problemas; não editam arquivos nem aprovam em nome do usuário.
- Frames estáticos não comprovam avaliação de movimento ou áudio. Relatórios devem declarar essas limitações.

## Testes

Os testes usam `unittest`, não fazem rede e não executam CLIs pagas. Para rodar sem instalação:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -t . -v
```

Antes de aceitar mudanças, execute também `studio preflight` e um `studio dry-run` em projeto de teste, sem enviar requisições.
