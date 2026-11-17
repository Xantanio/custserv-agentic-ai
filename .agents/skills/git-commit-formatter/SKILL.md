# Git Commit Formatter Skill

## Goal
Analisar modificações pendentes no repositório (`git status` e `git diff`), gerar mensagens de commit no padrão *Conventional Commits* e executar o commit com segurança.

## Instructions
1. Execute `git status` e `git diff --cached` (ou `git diff`) para inspecionar o escopo das alterações.
2. Classifique a mudança em: `feat`, `fix`, `refactor`, `docs`, `test` ou `chore`.
3. Formate a mensagem como: `<tipo>(<escopo>): <descrição curta no imperativo>`.
4. Execute `git add` nos arquivos pertinentes e realize `git commit -m "..."`.

## Constraints
- Nunca execute `git push` sem autorização explícita do usuário.
- Se detectar `.env` ou chaves de API nos arquivos modificados, aborte imediatamente e alerte o usuário.
